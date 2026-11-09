//
// NotificationHubDisposeTests.swift — NOTIF-017 and NOTIF-020 conformance.
//
// Claimed IDs: NOTIF-017, NOTIF-020.
//
// See spec/16-notifications.md §2, ADR-0013, ADR-0037 (Post-after-Dispose
// race generalised to all flavors), ADR-0197 (no terminal snapshot; a late
// subscriber receives completion only).
//
// Ordering guarantee:
//   The in-flight post test waits for the notification to appear in the
//   `pending` snapshot (via XCTestExpectation) before calling dispose().
//   Because the continuation is stored *before* the snapshot emits
//   (see NotificationHub.post), this guarantees the waiter is registered
//   before dispose() drains it — preventing the dispose-races-post race.
//
// Reference-type recorders are used for all captures in @escaping Combine
// sink closures to avoid value-copy semantics on var arrays.
//
import XCTest
import Combine
@testable import VMx

// Disambiguate VMx.Notification from Foundation.Notification.
private typealias Notif = VMx.Notification

// MARK: - Helpers

/// Completion flag — reference type for @escaping captures.
private final class CompletionFlag {
    var completed = false
}

/// Records pending values and completions. Callbacks can run on the posting
/// task's thread, so access is serialized by a lock.
private final class PendingEvents {
    private let lock = NSLock()
    private var storedValues: [[Notif]] = []
    private var storedCompletions = 0

    var values: [[Notif]] { lock.withLock { storedValues } }
    var completions: Int { lock.withLock { storedCompletions } }

    func record(_ value: [Notif]) { lock.withLock { storedValues.append(value) } }
    func complete() { lock.withLock { storedCompletions += 1 } }
}

// MARK: - Tests

final class NotificationHubDisposeTests: XCTestCase {

    // MARK: NOTIF-017

    /// NOTIF-017 — dispose resolves in-flight waiters with .pending, completes
    /// `pending`, and is idempotent; post-dispose post returns .pending immediately;
    /// post-dispose resolve is a no-op.
    func testNotif017DisposeSemantics() async {
        let hub = NotificationHub()
        let n = Notif(type: .confirmation, message: "in-flight")
        var cancellables = Set<AnyCancellable>()

        // Subscribe to pending completion BEFORE posting so we don't miss it.
        let completionFlag = CompletionFlag()
        let events = PendingEvents()
        let completedExpectation = expectation(description: "NOTIF-017: pending completes on dispose")
        hub.pending.sink(
            receiveCompletion: { [completionFlag] completion in
                if case .finished = completion {
                    completionFlag.completed = true
                    events.complete()
                    completedExpectation.fulfill()
                }
            },
            receiveValue: { events.record($0) }
        ).store(in: &cancellables)

        // Wait for the in-flight notification to appear in pending before
        // calling dispose() — guarantees the continuation is registered.
        let appeared = expectation(description: "NOTIF-017: n appears in pending")
        appeared.assertForOverFulfill = false
        hub.pending.sink { snapshot in
            if snapshot.contains(where: { $0 === n }) { appeared.fulfill() }
        }.store(in: &cancellables)

        let inFlightTask = Task { await hub.post(n) }
        await fulfillment(of: [appeared], timeout: 2.0)

        // Dispose: drains in-flight waiters with .pending.
        let valuesBeforeDispose = events.values.count
        hub.dispose()

        // In-flight post must resolve with .pending.
        let reaction = await inFlightTask.value
        XCTAssertEqual(reaction, .pending,
                       "NOTIF-017: in-flight post must resolve with .pending after dispose")

        // `pending` must complete.
        await fulfillment(of: [completedExpectation], timeout: 2.0)
        XCTAssertTrue(completionFlag.completed,
                      "NOTIF-017: pending must complete (.finished) on dispose")
        XCTAssertEqual(events.values.count, valuesBeforeDispose,
                       "NOTIF-017: dispose sends no final pending snapshot (ADR-0197)")
        XCTAssertEqual(events.completions, 1,
                       "NOTIF-017: pending completes once")

        // Post AFTER dispose must return .pending immediately without enqueuing
        // (must not hang).
        let late = Notif(type: .notification, message: "late")
        let lateReaction = await hub.post(late)
        XCTAssertEqual(lateReaction, .pending,
                       "NOTIF-017: post after dispose must return .pending immediately")
        // Immediacy note (NOTIF-017 parity): Python `late.done()` / C#
        // `late.IsCompleted` assert the returned future is settled *before*
        // awaiting. Swift's `post` is `async` and yields its value directly with
        // no inspectable Task/Future handle, so "already settled before await" is
        // not expressible. Reaching this assertion is the equivalent proof: a post
        // that enqueued an unresolved waiter would suspend forever and fail by
        // test timeout. See NotificationHub.post disposed branch + ADR-0037 §2.4.

        // Resolve after dispose must be a no-op (no crash).
        let ghost = Notif(type: .notification, message: "ghost")
        hub.resolve(ghost, .approve)  // must not crash

        // Double-dispose must be a no-op (no crash).
        hub.dispose()
    }

    // MARK: NOTIF-020

    /// NOTIF-020 — a `pending` subscription made after dispose receives
    /// completion once and no value (ADR-0197).
    func testNotif020LateSubscriptionReceivesCompletionOnly() async {
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "posted")
        var cancellables = Set<AnyCancellable>()

        let appeared = expectation(description: "NOTIF-020: n appears in pending")
        appeared.assertForOverFulfill = false
        hub.pending.sink { snapshot in
            if snapshot.contains(where: { $0 === n }) { appeared.fulfill() }
        }.store(in: &cancellables)
        let inFlight = Task { await hub.post(n) }
        await fulfillment(of: [appeared], timeout: 2.0)

        hub.dispose()
        let reaction = await inFlight.value
        XCTAssertEqual(reaction, .pending)

        // Full subscriber: values and completion.
        let late = PendingEvents()
        hub.pending.sink(
            receiveCompletion: { _ in late.complete() },
            receiveValue: { late.record($0) }
        ).store(in: &cancellables)
        XCTAssertEqual(late.completions, 1,
                       "NOTIF-020: a late subscriber receives completion once")
        XCTAssertTrue(late.values.isEmpty,
                      "NOTIF-020: a late subscriber receives no value")

        // Value-only subscriber: no value either.
        let valueOnly = PendingEvents()
        hub.pending.sink { valueOnly.record($0) }.store(in: &cancellables)
        XCTAssertTrue(valueOnly.values.isEmpty,
                      "NOTIF-020: a late value-only subscriber receives no value")
    }

    /// A `pending` subscriber that disposes the hub and then subscribes again
    /// in the same callback gets completion only on the new subscription.
    func testReentrantDisposeThenSubscribeReceivesCompletionOnly() async {
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "reentrant")
        var cancellables = Set<AnyCancellable>()
        let late = PendingEvents()
        let lateBox = CancellableBox()
        let firstDone = expectation(description: "first subscriber completes")

        hub.pending.sink(
            receiveCompletion: { _ in firstDone.fulfill() },
            receiveValue: { snapshot in
                guard snapshot.contains(where: { $0 === n }) else { return }
                hub.dispose()
                lateBox.cancellable = hub.pending.sink(
                    receiveCompletion: { _ in late.complete() },
                    receiveValue: { late.record($0) }
                )
            }
        ).store(in: &cancellables)

        let reaction = await hub.post(n)
        XCTAssertEqual(reaction, .pending)
        await fulfillment(of: [firstDone], timeout: 2.0)

        XCTAssertEqual(late.completions, 1)
        XCTAssertTrue(late.values.isEmpty)
        lateBox.cancellable?.cancel()
    }
}

/// Holds a cancellable created inside a callback.
private final class CancellableBox {
    var cancellable: AnyCancellable?
}
