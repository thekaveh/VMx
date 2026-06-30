//
// VirtualTimeScheduler — deterministic, time-advancing Combine `Scheduler`.
//
// See spec/16-notifications.md §6/§7 and ADR-0031. This is the Swift analogue
// of the TypeScript `FakeScheduler` (tests/unit/notifications/fakeScheduler.ts):
// it tracks a settable virtual `now` and fires scheduled work synchronously
// when `advance(to:)` / `advance(by:)` crosses the work's due time.
//
// Contrast with the Inc-3 `ManualScheduler` (same directory): that primitive
// BUFFERS all work and runs it on a flat `flush()` with no notion of time —
// it proves *deferral* for the threading tests. `VirtualTimeScheduler` instead
// models virtual TIME: each scheduled action carries a due virtual instant, and
// `advance(to:)` runs every action whose due time is ≤ the new `now`, in
// due-time order. The notification VMs read `now` to derive opacity decay and
// schedule their lifespan-expiry timer at `start + lifespan`.
//
// Time unit: SECONDS (Swift idiom; `TimeInterval`). The virtual instant and
// the `Stride` are both `Double` seconds, so a lifespan of `10` advanced to
// `5` yields opacity `0.5`. `SchedulerTimeIntervalConvertible.seconds(_:)`
// therefore maps 1:1; `milliseconds`/`microseconds`/`nanoseconds` scale down.
//
import Foundation
import Combine

/// A Combine `Scheduler` with a virtual, advance-only clock. Scheduled work is
/// enqueued keyed by its due virtual instant and run deterministically by
/// `advance(to:)` / `advance(by:)`. Used by `NotificationVM` / `ConfirmationVM`
/// for opacity decay and the lifespan auto-dismiss timer (NOTIF-011..016).
public final class VirtualTimeScheduler: Combine.Scheduler {

    // MARK: - Associated types

    /// Virtual instant, measured in seconds. `Strideable` so it satisfies the
    /// `Scheduler` associated-type requirement; advancing moves `now` forward.
    public struct SchedulerTimeType: Strideable {

        /// Virtual interval between two instants, in seconds. Must conform to
        /// `SignedNumeric` + `Comparable` (Strideable) AND
        /// `SchedulerTimeIntervalConvertible` (Combine `Scheduler`).
        public struct Stride: SchedulerTimeIntervalConvertible,
                              Comparable, SignedNumeric {

            /// The interval in seconds.
            public var value: Double

            public init(_ value: Double) { self.value = value }

            // ── SchedulerTimeIntervalConvertible ─────────────────────────
            // Seconds map 1:1; finer units scale down so a `.milliseconds(500)`
            // delay is 0.5 virtual seconds.
            public static func seconds(_ s: Int) -> Stride { Stride(Double(s)) }
            public static func seconds(_ s: Double) -> Stride { Stride(s) }
            public static func milliseconds(_ ms: Int) -> Stride {
                Stride(Double(ms) / 1_000)
            }
            public static func microseconds(_ us: Int) -> Stride {
                Stride(Double(us) / 1_000_000)
            }
            public static func nanoseconds(_ ns: Int) -> Stride {
                Stride(Double(ns) / 1_000_000_000)
            }

            // ── Comparable ───────────────────────────────────────────────
            public static func < (lhs: Stride, rhs: Stride) -> Bool {
                lhs.value < rhs.value
            }

            // ── AdditiveArithmetic ───────────────────────────────────────
            public static var zero: Stride { Stride(0) }
            public static func + (lhs: Stride, rhs: Stride) -> Stride {
                Stride(lhs.value + rhs.value)
            }
            public static func - (lhs: Stride, rhs: Stride) -> Stride {
                Stride(lhs.value - rhs.value)
            }

            // ── ExpressibleByIntegerLiteral / Numeric ────────────────────
            public init(integerLiteral value: Int) { self.value = Double(value) }
            public init?<T: BinaryInteger>(exactly source: T) {
                guard let v = Double(exactly: source) else { return nil }
                self.value = v
            }
            public typealias Magnitude = Double
            public var magnitude: Double { Swift.abs(value) }
            public static func * (lhs: Stride, rhs: Stride) -> Stride {
                Stride(lhs.value * rhs.value)
            }
            public static func *= (lhs: inout Stride, rhs: Stride) {
                lhs = lhs * rhs
            }
            // `SignedNumeric.negate()` / prefix `-` come from the protocol's
            // default implementations.
        }

        /// The instant, in seconds.
        public var seconds: Double

        public init(_ seconds: Double = 0) { self.seconds = seconds }

        public func distance(to other: SchedulerTimeType) -> Stride {
            Stride(other.seconds - seconds)
        }

        public func advanced(by n: Stride) -> SchedulerTimeType {
            SchedulerTimeType(seconds + n.value)
        }
    }

    public typealias SchedulerOptions = Never

    // MARK: - Queue

    /// One enqueued action. Reference type so the `AnyCancellable` returned by
    /// `enqueue` flips the same `cancelled` flag the queue holds.
    private final class ScheduledItem {
        let dueTime: Double
        let seq: Int
        let work: () -> Void
        var cancelled = false

        init(dueTime: Double, seq: Int, work: @escaping () -> Void) {
            self.dueTime = dueTime
            self.seq = seq
            self.work = work
        }
    }

    private let lock = NSRecursiveLock()
    private var currentSeconds: Double = 0
    private var queue: [ScheduledItem] = []
    private var nextSeq = 0

    public init(now: Double = 0) {
        self.currentSeconds = now
    }

    // MARK: - Scheduler conformance

    public var now: SchedulerTimeType {
        lock.lock()
        defer { lock.unlock() }
        return SchedulerTimeType(currentSeconds)
    }

    public var minimumTolerance: SchedulerTimeType.Stride { SchedulerTimeType.Stride(0) }

    /// Immediate work — enqueued at the current virtual instant (mirrors the TS
    /// `FakeScheduler.schedule(work, 0)`), so it runs on the next `advance`.
    public func schedule(
        options: SchedulerOptions?,
        _ action: @escaping () -> Void
    ) {
        lock.lock()
        let due = currentSeconds
        lock.unlock()
        _ = enqueue(dueTime: due, action)
    }

    /// Delayed work — enqueued at the absolute due instant `date`.
    public func schedule(
        after date: SchedulerTimeType,
        tolerance: SchedulerTimeType.Stride,
        options: SchedulerOptions?,
        _ action: @escaping () -> Void
    ) {
        _ = enqueue(dueTime: date.seconds, action)
    }

    /// Repeating work — the virtual clock never re-fires on its own, so the
    /// repeating schedule degenerates to a single action at `date`. The
    /// returned token cancels that pending action.
    public func schedule(
        after date: SchedulerTimeType,
        interval: SchedulerTimeType.Stride,
        tolerance: SchedulerTimeType.Stride,
        options: SchedulerOptions?,
        _ action: @escaping () -> Void
    ) -> Cancellable {
        enqueue(dueTime: date.seconds, action)
    }

    // MARK: - Cancellable convenience

    /// Schedule `action` at the absolute virtual instant `date`, returning a
    /// cancellation token. Distinct from the protocol `schedule(after:…)`
    /// overloads (which return `Void`) so callers — e.g. the notification VMs'
    /// lifespan-expiry timer — can cancel a pending action.
    @discardableResult
    public func schedule(
        at date: SchedulerTimeType,
        _ action: @escaping () -> Void
    ) -> AnyCancellable {
        enqueue(dueTime: date.seconds, action)
    }

    @discardableResult
    private func enqueue(
        dueTime: Double,
        _ work: @escaping () -> Void
    ) -> AnyCancellable {
        lock.lock()
        let item = ScheduledItem(dueTime: dueTime, seq: nextSeq, work: work)
        nextSeq += 1
        queue.append(item)
        // Stable order: by due time, then insertion sequence for ties.
        queue.sort { ($0.dueTime, $0.seq) < ($1.dueTime, $1.seq) }
        lock.unlock()
        return AnyCancellable { item.cancelled = true }
    }

    // MARK: - Time advancement

    /// Advance the virtual clock to `newNow`, running every enqueued action
    /// whose due time is ≤ `newNow.seconds`, in due-time order. An action that
    /// schedules further work is picked up within the same advance if its due
    /// time is also ≤ the target. `now` is set to each fired action's due time
    /// just before it runs, and to `newNow` once the queue is drained — so work
    /// observes the correct virtual instant.
    public func advance(to newNow: SchedulerTimeType) {
        let target = newNow.seconds
        while true {
            lock.lock()
            guard let first = queue.first, first.dueTime <= target else {
                currentSeconds = Swift.max(currentSeconds, target)
                lock.unlock()
                return
            }
            queue.removeFirst()
            if !first.cancelled {
                currentSeconds = first.dueTime
            }
            lock.unlock()
            if !first.cancelled {
                first.work()  // may enqueue more (re-locks via enqueue)
            }
        }
    }

    /// Advance the virtual clock by `interval`, firing all newly-due work.
    public func advance(by interval: SchedulerTimeType.Stride) {
        let target: Double
        lock.lock()
        target = currentSeconds + interval.value
        lock.unlock()
        advance(to: SchedulerTimeType(target))
    }

    /// Ergonomic seconds-based variant of `advance(to:)`.
    public func advance(toSeconds seconds: Double) {
        advance(to: SchedulerTimeType(seconds))
    }
}
