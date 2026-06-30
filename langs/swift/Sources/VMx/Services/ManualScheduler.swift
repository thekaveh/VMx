//
// ManualScheduler / ManualDispatcher — deterministic, manually-pumped
// scheduling primitives for threading conformance (THR-001..004).
//
// See spec/11-threading.md (§3 foreground marshaling, §4 background
// construct). Combine ships no virtual-time / manual `TestScheduler`
// analogue to `Microsoft.Reactive.Testing.TestScheduler` (C#),
// `reactivex`'s `TestScheduler` (Python), or `rxjs`'s `TestScheduler`
// (TypeScript). The cross-flavor THR tests prove *deferral* — zero
// deliveries before the scheduler advances, exactly one after — which a
// synchronous trampoline scheduler cannot demonstrate (it would pass even
// if `.receive(on:)` were removed entirely). To express that contract in
// Combine we hand-roll the two primitives below.
//
// Both BUFFER scheduled work and run it only on an explicit pump
// (`ManualScheduler.flush()`, `ManualDispatcher.flushForeground()` /
// `flushBackground()`). This is a documented, intentional divergence from
// the framework `TestScheduler` the other flavors reuse — captured in the
// Task 9 ADR.
//
import Foundation
import Combine

/// A Combine `Scheduler` that buffers every scheduled action and runs it
/// only when `flush()` is called. A `publisher.receive(on: manual)`
/// subscriber therefore receives nothing until `flush()` — the deterministic
/// virtual-time substitute used by the THR conformance tests.
///
/// Time is virtual and never advances on its own: `now` is a fixed instant
/// and the time-based `schedule(after:…)` overloads buffer their action just
/// like the immediate form. `.receive(on:)` (the only operator the THR tests
/// use) drives the immediate `schedule(options:_:)` overload, so buffering
/// that is what defers delivery.
public final class ManualScheduler: Combine.Scheduler {

    /// Virtual instant. Strideable so it satisfies the `Scheduler`
    /// associated-type requirement; the manual scheduler never actually
    /// advances time, so the concrete value is immaterial.
    public struct SchedulerTimeType: Strideable {

        /// Virtual interval between two `SchedulerTimeType` instants. Must
        /// conform to `SignedNumeric` + `Comparable` (Strideable) AND
        /// `SchedulerTimeIntervalConvertible` (Combine `Scheduler`).
        public struct Stride: SchedulerTimeIntervalConvertible,
                              Comparable, SignedNumeric {

            public var magnitudeValue: Int

            public init(_ value: Int) { self.magnitudeValue = value }

            // ── SchedulerTimeIntervalConvertible ─────────────────────────
            public static func seconds(_ s: Int) -> Stride { Stride(s) }
            public static func seconds(_ s: Double) -> Stride { Stride(Int(s)) }
            public static func milliseconds(_ ms: Int) -> Stride { Stride(ms) }
            public static func microseconds(_ us: Int) -> Stride { Stride(us) }
            public static func nanoseconds(_ ns: Int) -> Stride { Stride(ns) }

            // ── Comparable ───────────────────────────────────────────────
            public static func < (lhs: Stride, rhs: Stride) -> Bool {
                lhs.magnitudeValue < rhs.magnitudeValue
            }

            // ── AdditiveArithmetic ───────────────────────────────────────
            public static var zero: Stride { Stride(0) }
            public static func + (lhs: Stride, rhs: Stride) -> Stride {
                Stride(lhs.magnitudeValue + rhs.magnitudeValue)
            }
            public static func - (lhs: Stride, rhs: Stride) -> Stride {
                Stride(lhs.magnitudeValue - rhs.magnitudeValue)
            }

            // ── ExpressibleByIntegerLiteral / Numeric ────────────────────
            public init(integerLiteral value: Int) { self.magnitudeValue = value }
            public init?<T: BinaryInteger>(exactly source: T) {
                guard let v = Int(exactly: source) else { return nil }
                self.magnitudeValue = v
            }
            public typealias Magnitude = Int
            public var magnitude: Int { Swift.abs(magnitudeValue) }
            public static func * (lhs: Stride, rhs: Stride) -> Stride {
                Stride(lhs.magnitudeValue * rhs.magnitudeValue)
            }
            public static func *= (lhs: inout Stride, rhs: Stride) {
                lhs = lhs * rhs
            }
            // `SignedNumeric.negate()` / prefix `-` come from the protocol's
            // default implementations.
        }

        public var instant: Int

        public init(_ instant: Int = 0) { self.instant = instant }

        public func distance(to other: SchedulerTimeType) -> Stride {
            Stride(other.instant - instant)
        }

        public func advanced(by n: Stride) -> SchedulerTimeType {
            SchedulerTimeType(instant + n.magnitudeValue)
        }
    }

    public typealias SchedulerOptions = Never

    private let lock = NSRecursiveLock()
    private var buffer: [() -> Void] = []

    public init() {}

    public var now: SchedulerTimeType { SchedulerTimeType(0) }
    public var minimumTolerance: SchedulerTimeType.Stride { SchedulerTimeType.Stride(0) }

    public func schedule(
        options: SchedulerOptions?,
        _ action: @escaping () -> Void
    ) {
        enqueue(action)
    }

    public func schedule(
        after date: SchedulerTimeType,
        tolerance: SchedulerTimeType.Stride,
        options: SchedulerOptions?,
        _ action: @escaping () -> Void
    ) {
        enqueue(action)
    }

    public func schedule(
        after date: SchedulerTimeType,
        interval: SchedulerTimeType.Stride,
        tolerance: SchedulerTimeType.Stride,
        options: SchedulerOptions?,
        _ action: @escaping () -> Void
    ) -> Cancellable {
        enqueue(action)
        // Manual scheduler never re-fires on its own, so the repeating
        // schedule degenerates to a single buffered action. A no-op token
        // satisfies the `Cancellable` return contract.
        return AnyCancellable {}
    }

    private func enqueue(_ action: @escaping () -> Void) {
        lock.lock()
        defer { lock.unlock() }
        buffer.append(action)
    }

    /// Drain and run every buffered action in FIFO order. Re-entrancy safe:
    /// each pass snapshots the pending actions under the lock, clears the
    /// buffer, then runs the snapshot with the lock released — so an action
    /// that schedules further work (e.g. a chained `.receive(on:)`) is picked
    /// up by the next pass rather than corrupting the in-flight iteration.
    public func flush() {
        while true {
            lock.lock()
            if buffer.isEmpty {
                lock.unlock()
                return
            }
            let pending = buffer
            buffer.removeAll()
            lock.unlock()
            for action in pending {
                action()
            }
        }
    }
}

/// A `Dispatcher` whose foreground and background targets buffer scheduled
/// closures into separate queues, run only by `flushForeground()` /
/// `flushBackground()`. The per-channel split lets a test pump the two
/// targets independently — e.g. THR-002 asserts a background `construct()`
/// stays `.constructing` until `flushBackground()` advances it to
/// `.constructed`, while the synchronous foreground emission (the
/// `.constructing` transition itself) has already happened inline.
public final class ManualDispatcher: Dispatcher {

    private let lock = NSRecursiveLock()
    private var foregroundBuffer: [() -> Void] = []
    private var backgroundBuffer: [() -> Void] = []

    public init() {}

    public func scheduleForeground(_ work: @escaping () -> Void) {
        lock.lock()
        defer { lock.unlock() }
        foregroundBuffer.append(work)
    }

    public func scheduleBackground(_ work: @escaping () -> Void) {
        lock.lock()
        defer { lock.unlock() }
        backgroundBuffer.append(work)
    }

    /// Drain and run every buffered foreground closure in FIFO order.
    public func flushForeground() {
        drain(\.foregroundBuffer)
    }

    /// Drain and run every buffered background closure in FIFO order.
    public func flushBackground() {
        drain(\.backgroundBuffer)
    }

    /// Re-entrancy-safe drain of one channel (snapshot under the lock, run
    /// with the lock released — mirrors `ManualScheduler.flush()`).
    private func drain(
        _ keyPath: ReferenceWritableKeyPath<ManualDispatcher, [() -> Void]>
    ) {
        while true {
            lock.lock()
            let pending = self[keyPath: keyPath]
            if pending.isEmpty {
                lock.unlock()
                return
            }
            self[keyPath: keyPath] = []
            lock.unlock()
            for work in pending {
                work()
            }
        }
    }
}
