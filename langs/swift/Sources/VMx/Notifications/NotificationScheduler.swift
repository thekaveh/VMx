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
        schedule = { delay, action in scheduleOnce(on: scheduler, after: delay, action) }
    }
}
