//
// NotificationHub.swift — async notification / confirmation hub.
//
// See spec/16-notifications.md §2 and ADR-0013.
//
// `post` suspends via `withCheckedContinuation`; continuations are keyed by
// `ObjectIdentifier(n)` so two `Notification` instances with the same type
// and message are still resolved independently.
//
// Thread safety: all mutable state is protected by `lock`. The `pending`
// snapshot is captured under the lock but emitted (`subject.send`) AFTER the
// lock is released, so a subscriber that synchronously calls `post`/`resolve`
// from within its sink handler does not re-enter the lock — no deadlock.
//
// Dispose semantics (NOTIF-017, ADR-0037):
//   dispose() is idempotent. Under the lock it captures all stored
//   continuations, clears the waiters map, clears pendingList, and sets
//   `disposed = true`. Outside the lock it resumes every captured continuation
//   with `.pending` and sends `.finished` on the subject — the same
//   send-outside-lock discipline used for normal post/resolve to avoid
//   sink re-entrancy deadlocks.
//   After dispose:
//   - post(_:) returns `.pending` immediately without storing a continuation.
//   - resolve(_:_:) is a no-op.
//
import Foundation
import Combine

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
public final class NotificationHub: NotificationHubProtocol {
    private let subject = CurrentValueSubject<[Notification], Never>([])
    private var pendingList: [Notification] = []
    // A LIST of continuations per notification: re-posting the same still-pending
    // instance attaches another awaiter rather than overwriting (and leaking) the
    // first continuation (double-post SHOULD, ADR-0020 §2.3).
    private var waiters: [ObjectIdentifier: [CheckedContinuation<NotificationReaction, Never>]] = [:]
    private var disposed = false
    private let lock = NSLock()

    public init() {}

    public var pending: AnyPublisher<[Notification], Never> {
        subject.eraseToAnyPublisher()
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
            lock.unlock()
            subject.send(snapshot)  // emitted outside the lock (no sink re-entrancy)
        }
    }

    /// Resolve `n` with `reaction`. No-op if `n` is not pending (NOTIF-008).
    /// No-op after dispose (NOTIF-017).
    /// The continuation is resumed *after* releasing the lock.
    public func resolve(_ n: Notification, _ reaction: NotificationReaction) {
        let continuations: [CheckedContinuation<NotificationReaction, Never>]?
        var snapshot: [Notification]?
        lock.lock()
        guard !disposed else {
            lock.unlock()
            return
        }
        let key = ObjectIdentifier(n)
        continuations = waiters.removeValue(forKey: key)
        if continuations != nil {
            pendingList.removeAll { ObjectIdentifier($0) == key }
            snapshot = pendingList
        }
        lock.unlock()
        // Emit + resume outside the lock so a synchronous re-entrant
        // post/resolve from a subscriber or the continuation body cannot deadlock.
        if let snapshot { subject.send(snapshot) }
        for continuation in continuations ?? [] {
            continuation.resume(returning: reaction)
        }
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
        lock.unlock()
        // Resume and complete outside the lock — mirrors the send-outside-lock
        // discipline to prevent sink re-entrancy deadlocks.
        for continuation in capturedWaiters {
            continuation.resume(returning: .pending)
        }
        subject.send(completion: .finished)
    }
}
