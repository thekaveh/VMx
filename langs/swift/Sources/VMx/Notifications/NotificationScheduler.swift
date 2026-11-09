//
// NotificationScheduler — the Combine schedulers that drive notification VMs.
//
// See spec/16-notifications.md §6 and issue #1347. `NotificationVM` reads the
// time that has passed since its construction and arms one-shot timers. A
// Combine `Scheduler` can arm timers, but its `Stride` has no generic
// conversion to seconds. This protocol adds that one conversion.
//
// VMx conforms `VirtualTimeScheduler` (tests) and the Foundation real-time
// schedulers `DispatchQueue`, `RunLoop` and `OperationQueue` (apps). A custom
// scheduler conforms by implementing `seconds(from:to:)`.
//
import Foundation
import Combine

/// A Combine `Scheduler` that can measure the interval between two of its
/// instants in seconds. `NotificationVM` and `ConfirmationVM` accept any
/// conforming scheduler: `DispatchQueue.main` or `RunLoop.main` in an app, and
/// `VirtualTimeScheduler` in tests.
public protocol NotificationScheduler: Scheduler {
    /// The interval from `start` to `end`, in seconds. Negative when `end` is
    /// before `start`.
    func seconds(from start: SchedulerTimeType, to end: SchedulerTimeType) -> TimeInterval
}

extension VirtualTimeScheduler: NotificationScheduler {
    public func seconds(from start: SchedulerTimeType, to end: SchedulerTimeType) -> TimeInterval {
        end.seconds - start.seconds
    }
}

extension DispatchQueue: NotificationScheduler {
    public func seconds(from start: SchedulerTimeType, to end: SchedulerTimeType) -> TimeInterval {
        let from = start.dispatchTime.uptimeNanoseconds
        let to = end.dispatchTime.uptimeNanoseconds
        return to >= from
            ? Double(to - from) / 1_000_000_000
            : -Double(from - to) / 1_000_000_000
    }
}

extension RunLoop: NotificationScheduler {
    public func seconds(from start: SchedulerTimeType, to end: SchedulerTimeType) -> TimeInterval {
        end.date.timeIntervalSince(start.date)
    }
}

extension OperationQueue: NotificationScheduler {
    public func seconds(from start: SchedulerTimeType, to end: SchedulerTimeType) -> TimeInterval {
        end.date.timeIntervalSince(start.date)
    }
}

/// Type-erased view of the scheduler that a notification VM was built with:
/// the seconds since construction, and a cancellable one-shot timer.
struct NotificationClock {
    /// Seconds since the clock was created.
    let elapsed: () -> TimeInterval
    /// Runs `action` on the scheduler after `delay` seconds, unless the
    /// returned token is cancelled first.
    let schedule: (_ delay: TimeInterval, _ action: @escaping () -> Void) -> AnyCancellable

    init<S: NotificationScheduler>(_ scheduler: S) {
        let origin = scheduler.now
        elapsed = { scheduler.seconds(from: origin, to: scheduler.now) }
        if let virtual = scheduler as? VirtualTimeScheduler {
            // The virtual clock removes a cancelled action from its queue.
            schedule = { delay, action in
                virtual.schedule(at: virtual.now.advanced(by: .seconds(delay)), action)
            }
        } else {
            // The Combine one-shot `schedule(after:)` returns no token, so a
            // flag makes a cancelled action a no-op.
            schedule = { delay, action in
                let token = OneShotToken()
                scheduler.schedule(after: scheduler.now.advanced(by: .seconds(delay))) {
                    token.run(action)
                }
                return AnyCancellable { token.cancel() }
            }
        }
    }
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
