//
// DelayedTask — at most one delayed action on an injected scheduler.
//
// See spec/11-threading.md §6.3 and ADR-0219. `DelayedTask` is the portable
// form of a timer, a debounce and a polling loop. It runs each action on the
// injected Combine `Scheduler`, never through `Dispatcher` (spec/11 §6.2).
//
// Thread safety: every state change happens under `lock`. The task never
// calls the scheduler or an action while it holds the lock. A generation
// counter makes a replaced or cancelled action a no-op, even when the
// scheduler fires it while `schedule`, `cancel` or `dispose` runs.
//
import Foundation
import Combine

/// Holds at most one pending action on an injected scheduler.
///
/// - `schedule(after:_:)` replaces the pending action and restarts the delay.
/// - `cancel()` cancels the pending action.
/// - `isPending` is `false` again when the action starts, so an action can
///   call `schedule(after:_:)` to repeat a polling loop.
/// - `dispose()` cancels the pending action, and later calls have no effect.
///
/// Pass `DispatchQueue.main` to run actions on the main thread, and a
/// `VirtualTimeScheduler` in tests. Releasing the task cancels its pending
/// action, as releasing an `AnyCancellable` does. Swift actions cannot throw.
public final class DelayedTask: @unchecked Sendable {

    private let scheduleAction: (TimeInterval, @escaping () -> Void) -> AnyCancellable
    private let lock = NSLock()
    private var generation: UInt64 = 0
    private var pending = false
    private var disposed = false
    private var handle: AnyCancellable?

    /// - Parameter scheduler: The clock that runs the actions. The task never
    ///   disposes it.
    public init<S: Scheduler>(scheduler: S) {
        scheduleAction = { delay, action in scheduleOnce(on: scheduler, after: delay, action) }
    }

    /// `true` from `schedule(after:_:)` until the action starts, `cancel()`
    /// or `dispose()`.
    public var isPending: Bool {
        lock.lock()
        defer { lock.unlock() }
        return pending
    }

    /// Cancels the pending action, if any, and runs `action` once after
    /// `delay` seconds. A zero or negative delay runs the action at the
    /// scheduler's next opportunity, never inside this call. Has no effect
    /// after `dispose()`.
    public func schedule(after delay: TimeInterval, _ action: @escaping () -> Void) {
        lock.lock()
        if disposed {
            lock.unlock()
            return
        }
        let replaced = handle
        handle = nil
        generation &+= 1
        let current = generation
        pending = true
        lock.unlock()
        replaced?.cancel()

        let token = scheduleAction(delay) { [weak self] in
            self?.run(current, action)
        }

        lock.lock()
        if current == generation, pending, !disposed {
            handle = token
            lock.unlock()
        } else {
            lock.unlock()
            token.cancel()
        }
    }

    /// Cancels the pending action. Has no effect when no action is pending.
    /// An action that already started runs to its end.
    public func cancel() {
        lock.lock()
        let cancelled = takePendingLocked()
        lock.unlock()
        cancelled?.cancel()
    }

    /// Cancels the pending action. Later `schedule(after:_:)` and `cancel()`
    /// calls have no effect. A second call has no effect.
    public func dispose() {
        lock.lock()
        if disposed {
            lock.unlock()
            return
        }
        disposed = true
        let cancelled = takePendingLocked()
        lock.unlock()
        cancelled?.cancel()
    }

    /// Clears the pending state and returns its token. Call with `lock` held.
    private func takePendingLocked() -> AnyCancellable? {
        guard pending else { return nil }
        generation &+= 1
        pending = false
        let taken = handle
        handle = nil
        return taken
    }

    private func run(_ scheduled: UInt64, _ action: () -> Void) {
        lock.lock()
        guard scheduled == generation, pending, !disposed else {
            lock.unlock()
            return
        }
        pending = false
        let finished = handle
        handle = nil
        lock.unlock()
        // The action has started, so this cancel has no effect. It releases
        // the token outside the lock.
        finished?.cancel()
        action()
    }
}
