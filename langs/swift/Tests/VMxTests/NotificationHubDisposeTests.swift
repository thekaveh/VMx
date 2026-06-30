//
// NotificationHubDisposeTests.swift — NOTIF-017 conformance.
//
// Claimed IDs: NOTIF-017.
//
// See spec/16-notifications.md §2, ADR-0013, ADR-0037 (Post-after-Dispose
// race generalised to all flavors).
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
        let completedExpectation = expectation(description: "NOTIF-017: pending completes on dispose")
        hub.pending.sink(
            receiveCompletion: { [completionFlag] completion in
                if case .finished = completion {
                    completionFlag.completed = true
                    completedExpectation.fulfill()
                }
            },
            receiveValue: { _ in }
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
        hub.dispose()

        // In-flight post must resolve with .pending.
        let reaction = await inFlightTask.value
        XCTAssertEqual(reaction, .pending,
                       "NOTIF-017: in-flight post must resolve with .pending after dispose")

        // `pending` must complete.
        await fulfillment(of: [completedExpectation], timeout: 2.0)
        XCTAssertTrue(completionFlag.completed,
                      "NOTIF-017: pending must complete (.finished) on dispose")

        // Post AFTER dispose must return .pending immediately without enqueuing
        // (must not hang).
        let late = Notif(type: .notification, message: "late")
        let lateReaction = await hub.post(late)
        XCTAssertEqual(lateReaction, .pending,
                       "NOTIF-017: post after dispose must return .pending immediately")

        // Resolve after dispose must be a no-op (no crash).
        let ghost = Notif(type: .notification, message: "ghost")
        hub.resolve(ghost, .approve)  // must not crash

        // Double-dispose must be a no-op (no crash).
        hub.dispose()
    }
}
