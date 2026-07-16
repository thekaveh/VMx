//
// NotificationHub.swift — async notification / confirmation hub.
//
// See spec/16-notifications.md §2 and ADR-0013.
//
// `post` suspends via `withCheckedContinuation`; continuations are keyed by
// `ObjectIdentifier(n)` so two `Notification` instances with the same type
// and message are still resolved independently.
//
// Thread safety: all mutable state and an ordered delivery FIFO are protected
// by `lock`. Snapshot/completion records are enqueued at the state mutation's
// linearization point, then one drainer invokes subscribers after releasing the
// lock. Re-entrant operations append behind the current callback.
//
// Dispose semantics (NOTIF-017, ADR-0037):
//   dispose() is idempotent. Under the lock it captures all stored
//   continuations, clears the waiters map, clears pendingList, sets
//   `disposed = true`, and enqueues terminal delivery. Outside the lock the
//   ordered drainer finishes the subject and resolves every captured waiter
//   with `.pending`.
//   After dispose:
//   - post(_:) returns `.pending` immediately without storing a continuation.
//   - resolve(_:_:) is a no-op.
//
import Foundation
import Combine

private enum NotificationDeliveryContext {
    private static let depthKey = "org.vmx.notification-hub.delivery-depth"

    static var depth: Int {
        get { Thread.current.threadDictionary[depthKey] as? Int ?? 0 }
        set { Thread.current.threadDictionary[depthKey] = newValue }
    }
}

private final class NotificationHubDelivery {
    enum Event {
        case snapshot([Notification], UInt64)
        case finished(UInt64)
    }

    let event: Event
    let afterDelivery: () -> Void
    let completed = DispatchSemaphore(value: 0)

    init(event: Event, afterDelivery: @escaping () -> Void = {}) {
        self.event = event
        self.afterDelivery = afterDelivery
    }
}

// MARK: - Protocol

/// Async notification / confirmation hub contract.
/// See spec/16-notifications.md §2.
public protocol NotificationHubProtocol: AnyObject {
    /// Current pending notifications, backed by a `CurrentValueSubject`.
    /// Replays the latest snapshot to new subscribers.
    var pending: AnyPublisher<[Notification], Never> { get }

    /// Post a notification and suspend until it is resolved.
    ///
    /// - Appends `n` to the pending list and emits a new snapshot.
    /// - Suspends the caller until `resolve(_:_:)` is called for this exact instance.
    /// - Returns the `NotificationReaction` passed to `resolve`.
    /// - After `dispose()`: returns `.pending` immediately without enqueuing.
    func post(_ n: Notification) async -> NotificationReaction

    /// Resolve a previously posted notification with a reaction.
    ///
    /// - Removes `n` from the pending list and emits a new snapshot.
    /// - Resumes the awaitable returned by the original `post` call.
    /// - If `n` is not currently pending, this is a no-op (NOTIF-008).
    /// - After `dispose()`: no-op.
    func resolve(_ n: Notification, _ reaction: NotificationReaction)
}

// MARK: - Default implementation

/// Combine + Swift Concurrency `NotificationHubProtocol`.
public final class NotificationHub: NotificationHubProtocol, @unchecked Sendable {
    private final class PendingSubscriberRecord {
        let subject: CurrentValueSubject<[Notification], Never>
        let startSequence: UInt64

        init(
            subject: CurrentValueSubject<[Notification], Never>,
            startSequence: UInt64
        ) {
            self.subject = subject
            self.startSequence = startSequence
        }
    }

    private final class PendingPublisher: Publisher {
        typealias Output = [Notification]
        typealias Failure = Never

        private weak var hub: NotificationHub?

        init(hub: NotificationHub) {
            self.hub = hub
        }

        func receive<S>(subscriber: S)
        where S: Subscriber, S.Input == Output, S.Failure == Failure {
            guard let hub else {
                Empty<Output, Failure>(completeImmediately: true)
                    .receive(subscriber: subscriber)
                return
            }
            hub.attachPendingSubscriber(subscriber)
        }
    }

    private var pendingList: [Notification] = []
    // A LIST of continuations per notification: re-posting the same still-pending
    // instance attaches another awaiter rather than overwriting (and leaking) the
    // first continuation (double-post SHOULD, ADR-0020 §2.3).
    private var waiters: [ObjectIdentifier: [CheckedContinuation<NotificationReaction, Never>]] = [:]
    private var disposed = false
    private let lock = NSRecursiveLock()
    private var pendingSequence: UInt64 = 0
    private var pendingSubscribers: [UUID: PendingSubscriberRecord] = [:]
    private var deliveries: [NotificationHubDelivery] = []
    private var deliveryHead = 0
    private var drainerThread: UInt64 = 0
    private let beforeDeliveryDrain: (() -> Void)?
    private let afterDeliveryEnqueued: (() -> Void)?

    public init() {
        self.beforeDeliveryDrain = nil
        self.afterDeliveryEnqueued = nil
    }

    /// Deterministic concurrency seam used only by `@testable` regression
    /// tests. Production construction uses `init()` above.
    init(
        beforeDeliveryDrain: @escaping () -> Void,
        afterDeliveryEnqueued: @escaping () -> Void
    ) {
        self.beforeDeliveryDrain = beforeDeliveryDrain
        self.afterDeliveryEnqueued = afterDeliveryEnqueued
    }

    public var pending: AnyPublisher<[Notification], Never> {
        PendingPublisher(hub: self).eraseToAnyPublisher()
    }

    /// Post `n`: append to pending, store the continuation, emit snapshot.
    /// The continuation is stored *before* the snapshot is emitted so that a
    /// subscriber reacting to the emission always finds the waiter in `resolve`.
    /// After dispose: returns `.pending` immediately without enqueuing (NOTIF-017).
    public func post(_ n: Notification) async -> NotificationReaction {
        // The disposed check lives inside the continuation closure (a
        // synchronous context) so the lock is never acquired from this async
        // function body — `NSLock.lock()` is unavailable from async contexts.
        // A disposed post resumes `.pending` immediately, so it never suspends.
        return await withCheckedContinuation { continuation in
            lock.lock()
            if disposed {
                lock.unlock()
                continuation.resume(returning: .pending)
                return
            }
            let key = ObjectIdentifier(n)
            if waiters[key] != nil {
                // Re-post of a still-pending notification: attach this awaiter to
                // the existing waiter list so it resolves together with the first,
                // instead of overwriting and leaking that continuation. Do not
                // re-enqueue into pendingList.
                waiters[key]!.append(continuation)
                lock.unlock()
                return
            }
            pendingList.append(n)
            waiters[key] = [continuation]  // stored before the snapshot is emitted
            let snapshot = pendingList
            pendingSequence &+= 1
            let delivery = enqueueLocked(.snapshot(snapshot, pendingSequence))
            lock.unlock()
            afterDeliveryEnqueued?()
            publish(delivery)
        }
    }

    /// Resolve `n` with `reaction`. No-op if `n` is not pending (NOTIF-008).
    /// No-op after dispose (NOTIF-017).
    /// All continuations awaiting `n` (including double-post re-posters) are
    /// resumed with `reaction` *after* releasing the lock.
    public func resolve(_ n: Notification, _ reaction: NotificationReaction) {
        lock.lock()
        guard !disposed else {
            lock.unlock()
            return
        }
        let key = ObjectIdentifier(n)
        guard let continuations = waiters.removeValue(forKey: key) else {
            lock.unlock()
            return
        }
        pendingList.removeAll { ObjectIdentifier($0) == key }
        let snapshot = pendingList
        pendingSequence &+= 1
        let delivery = enqueueLocked(.snapshot(snapshot, pendingSequence)) {
            for continuation in continuations {
                continuation.resume(returning: reaction)
            }
        }
        lock.unlock()
        afterDeliveryEnqueued?()
        publish(delivery)
    }

    /// Resolve all in-flight waiters with `.pending`, complete `pending`,
    /// and stop accepting new posts. Idempotent (NOTIF-017).
    public func dispose() {
        lock.lock()
        guard !disposed else {
            lock.unlock()
            return
        }
        disposed = true
        let capturedWaiters = waiters.values.flatMap { $0 }
        waiters.removeAll()
        pendingList.removeAll()
        pendingSequence &+= 1
        let delivery = enqueueLocked(.finished(pendingSequence)) {
            for continuation in capturedWaiters {
                continuation.resume(returning: .pending)
            }
        }
        lock.unlock()
        afterDeliveryEnqueued?()
        publish(delivery)
    }

    private typealias DeliveryPlan = (
        delivery: NotificationHubDelivery,
        shouldDrain: Bool,
        shouldWait: Bool
    )

    /// Enqueue while `lock` is held so observable delivery order is the same as
    /// the pending-state mutation order. Subscriber callbacks still run after
    /// the lock is released.
    private func enqueueLocked(
        _ event: NotificationHubDelivery.Event,
        afterDelivery: @escaping () -> Void = {}
    ) -> DeliveryPlan {
        let delivery = NotificationHubDelivery(
            event: event,
            afterDelivery: afterDelivery
        )
        deliveries.append(delivery)
        let caller = Self.currentThreadID
        if drainerThread == 0 {
            drainerThread = caller
            return (delivery, true, false)
        }
        let shouldWait = drainerThread != caller && NotificationDeliveryContext.depth == 0
        return (delivery, false, shouldWait)
    }

    private func publish(_ plan: DeliveryPlan) {
        if plan.shouldDrain {
            beforeDeliveryDrain?()
            drainDeliveries()
        } else if plan.shouldWait {
            plan.delivery.completed.wait()
        }
    }

    /// Drain outside `lock`. Re-entrant operations append behind the current
    /// callback; producers on another thread wait for their own record unless
    /// they are already inside another notification-hub delivery. That global
    /// thread-local exception prevents opposing hubs from waiting on each
    /// other's Combine downstream locks.
    private func drainDeliveries() {
        while true {
            lock.lock()
            guard deliveryHead < deliveries.count else {
                deliveries.removeAll(keepingCapacity: true)
                deliveryHead = 0
                drainerThread = 0
                lock.unlock()
                return
            }
            let delivery = deliveries[deliveryHead]
            deliveryHead += 1
            lock.unlock()

            NotificationDeliveryContext.depth += 1
            switch delivery.event {
            case .snapshot(let snapshot, let sequence):
                deliverSnapshot(snapshot, sequence: sequence)
            case .finished(let sequence):
                finishPendingSubscribers(sequence: sequence)
            }
            delivery.afterDelivery()
            NotificationDeliveryContext.depth -= 1
            delivery.completed.signal()
        }
    }

    private static var currentThreadID: UInt64 {
        UInt64(pthread_mach_thread_np(pthread_self()))
    }

    private func attachPendingSubscriber<S>(_ subscriber: S)
    where S: Subscriber, S.Input == [Notification], S.Failure == Never {
        lock.lock()
        guard !disposed else {
            lock.unlock()
            Empty<[Notification], Never>(completeImmediately: true)
                .receive(subscriber: subscriber)
            return
        }

        let id = UUID()
        let subject = CurrentValueSubject<[Notification], Never>(pendingList)
        pendingSubscribers[id] = PendingSubscriberRecord(
            subject: subject,
            startSequence: pendingSequence
        )
        lock.unlock()

        // CurrentValueSubject synchronously replays its current value from
        // receive(subscriber:). Attach only after the record is registered and
        // the hub lock is released so initial subscriber code cannot form an
        // opposing-hub lock cycle. Any mutation in this gap updates or finishes
        // the registered subject before its downstream attaches.
        subject
            .handleEvents(receiveCancel: { [weak self] in
                self?.detachPendingSubscriber(id)
            })
            .receive(subscriber: subscriber)
    }

    private func detachPendingSubscriber(_ id: UUID) {
        lock.lock()
        pendingSubscribers.removeValue(forKey: id)
        lock.unlock()
    }

    private func deliverSnapshot(
        _ snapshot: [Notification],
        sequence: UInt64
    ) {
        lock.lock()
        let targets = pendingSubscribers.values
            .filter { $0.startSequence < sequence }
            .map(\.subject)
        lock.unlock()
        for target in targets { target.send(snapshot) }
    }

    private func finishPendingSubscribers(sequence: UInt64) {
        lock.lock()
        let targets = pendingSubscribers.values
            .filter { $0.startSequence < sequence }
            .map(\.subject)
        pendingSubscribers.removeAll()
        lock.unlock()
        for target in targets { target.send(completion: .finished) }
    }
}
