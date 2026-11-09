//
// ScheduleOnce — a cancellable one-shot action on any Combine `Scheduler`.
//
// See spec/11-threading.md §6.1 and ADR-0219. The Combine one-shot
// `schedule(after:)` returns no token, so this helper adds one. The
// notification clock and `DelayedTask` both use it.
//
import Foundation
import Combine

/// Runs `action` once on `scheduler` after `delay` seconds, unless the
/// returned token is cancelled first. A negative delay counts as zero.
/// Releasing the token also cancels the action.
func scheduleOnce<S: Scheduler>(
    on scheduler: S,
    after delay: TimeInterval,
    _ action: @escaping () -> Void
) -> AnyCancellable {
    let delay = Swift.max(0, delay)
    if let virtual = scheduler as? VirtualTimeScheduler {
        // The virtual clock removes a cancelled action from its queue.
        return virtual.schedule(at: virtual.now.advanced(by: .seconds(delay)), action)
    }
    // A flag makes a cancelled action a no-op.
    let token = OneShotToken()
    scheduler.schedule(after: scheduler.now.advanced(by: .seconds(delay))) {
        token.run(action)
    }
    return AnyCancellable { token.cancel() }
}

/// Cancellation flag for one scheduled action. The scheduler can run the
/// action on another thread, so the flag is read and written under a lock.
private final class OneShotToken {
    private let lock = NSLock()
    private var cancelled = false

    func cancel() {
        lock.lock(); cancelled = true; lock.unlock()
    }

    func run(_ action: () -> Void) {
        lock.lock()
        let skip = cancelled
        cancelled = true
        lock.unlock()
        if !skip { action() }
    }
}
