//
// NotificationHubTests.swift — NOTIF-001..008 conformance.
//
// Claimed IDs: NOTIF-001, NOTIF-002, NOTIF-003, NOTIF-004, NOTIF-005,
//              NOTIF-006, NOTIF-007, NOTIF-008.
//
// See spec/16-notifications.md §1-2, ADR-0013.
//
// Ordering guarantee for post → resolve tests:
//   Each test that calls resolve() after post() first awaits an
//   XCTestExpectation fulfilled when the notification appears in the `pending`
//   snapshot. Because the continuation is stored *before* `pending` emits
//   (see NotificationHub.post), this ensures the waiter is registered before
//   resolve() is invoked — preventing the resolve-races-post race.
//
// Reference-type recorders are used for all snapshot captures in @escaping
// Combine sink closures to avoid value-copy semantics on var arrays.
//
import XCTest
import Combine
@testable import VMx

// Disambiguate VMx.Notification from Foundation.Notification.
private typealias Notif = VMx.Notification

// MARK: - Helpers

/// Snapshot log for pending emissions — reference type for @escaping captures.
private final class SnapshotRecorder {
    var snapshots: [[Notif]] = []
}

// MARK: - Tests

final class NotificationHubTests: XCTestCase {

    // MARK: NOTIF-001

    /// NOTIF-001 — post(_:) suspends and returns the reaction value when resolved.
    func testNotif001PostThenResolveReturnsReaction() async {
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "info")
        var cancellables = Set<AnyCancellable>()

        // Wait for n to appear in pending — guarantees the continuation is stored.
        let appeared = expectation(description: "NOTIF-001: n appears in pending")
        appeared.assertForOverFulfill = false
        hub.pending.sink { snapshot in
            if snapshot.contains(where: { $0 === n }) { appeared.fulfill() }
        }.store(in: &cancellables)

        let t = Task { await hub.post(n) }
        await fulfillment(of: [appeared], timeout: 2.0)

        hub.resolve(n, .approve)
        let reaction = await t.value

        XCTAssertEqual(reaction, .approve,
                       "NOTIF-001: post should return the reaction passed to resolve")
    }

    // MARK: NOTIF-002

    /// NOTIF-002 — post(_:) adds the notification to the pending snapshot.
    func testNotif002PostAddsToPending() async {
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "info")
        let recorder = SnapshotRecorder()
        var cancellables = Set<AnyCancellable>()

        let appeared = expectation(description: "NOTIF-002: n appears in pending")
        appeared.assertForOverFulfill = false
        hub.pending.sink { [recorder] snapshot in
            recorder.snapshots.append(snapshot)
            if snapshot.contains(where: { $0 === n }) { appeared.fulfill() }
        }.store(in: &cancellables)

        let t = Task { await hub.post(n) }
        await fulfillment(of: [appeared], timeout: 2.0)

        XCTAssertTrue(
            recorder.snapshots.last?.contains(where: { $0 === n }) == true,
            "NOTIF-002: n must appear in the pending snapshot after post"
        )

        // Clean up the dangling task.
        hub.resolve(n, .approve)
        _ = await t.value
    }

    // MARK: NOTIF-003

    /// NOTIF-003 — resolve(_:_:) removes the notification from the pending snapshot.
    func testNotif003ResolveRemovesFromPending() async {
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "info")
        let recorder = SnapshotRecorder()
        var cancellables = Set<AnyCancellable>()

        let appeared = expectation(description: "NOTIF-003: n appears in pending")
        appeared.assertForOverFulfill = false
        hub.pending.sink { [recorder] snapshot in
            recorder.snapshots.append(snapshot)
            if snapshot.contains(where: { $0 === n }) { appeared.fulfill() }
        }.store(in: &cancellables)

        let t = Task { await hub.post(n) }
        await fulfillment(of: [appeared], timeout: 2.0)

        hub.resolve(n, .approve)
        _ = await t.value  // drain so pending has updated before we assert

        XCTAssertFalse(
            recorder.snapshots.last?.contains(where: { $0 === n }) == true,
            "NOTIF-003: n must be removed from the pending snapshot after resolve"
        )
    }

    // MARK: NOTIF-004

    /// NOTIF-004 — NotificationType has exactly {error, notification, confirmation}.
    func testNotif004NotificationTypeCases() {
        let cases = NotificationType.allCases
        XCTAssertEqual(cases.count, 3,
                       "NOTIF-004: NotificationType must have exactly 3 cases")
        XCTAssertTrue(cases.contains(.error),        "NOTIF-004: must include .error")
        XCTAssertTrue(cases.contains(.notification), "NOTIF-004: must include .notification")
        XCTAssertTrue(cases.contains(.confirmation), "NOTIF-004: must include .confirmation")
    }

    // MARK: NOTIF-005

    /// NOTIF-005 — NotificationReaction has exactly {pending, approve, reject}.
    func testNotif005NotificationReactionCases() {
        let cases = NotificationReaction.allCases
        XCTAssertEqual(cases.count, 3,
                       "NOTIF-005: NotificationReaction must have exactly 3 cases")
        XCTAssertTrue(cases.contains(.pending), "NOTIF-005: must include .pending")
        XCTAssertTrue(cases.contains(.approve), "NOTIF-005: must include .approve")
        XCTAssertTrue(cases.contains(.reject),  "NOTIF-005: must include .reject")
    }

    // MARK: NOTIF-006

    /// NOTIF-006 — the resolved awaitable carries the reaction value (.reject case).
    func testNotif006ResolvedAwaitableCarriesReaction() async {
        let hub = NotificationHub()
        let n = Notif(type: .confirmation, message: "delete?")
        var cancellables = Set<AnyCancellable>()

        let appeared = expectation(description: "NOTIF-006: n appears in pending")
        appeared.assertForOverFulfill = false
        hub.pending.sink { snapshot in
            if snapshot.contains(where: { $0 === n }) { appeared.fulfill() }
        }.store(in: &cancellables)

        let t = Task { await hub.post(n) }
        await fulfillment(of: [appeared], timeout: 2.0)

        hub.resolve(n, .reject)
        let reaction = await t.value

        XCTAssertEqual(reaction, .reject,
                       "NOTIF-006: awaitable must carry the .reject reaction value")
    }

    // MARK: NOTIF-007

    /// NOTIF-007 — two distinct Confirmation notifications resolve independently.
    func testNotif007TwoNotificationsResolveIndependently() async {
        let hub = NotificationHub()
        let nA = Notif(type: .confirmation, message: "x")
        let nR = Notif(type: .confirmation, message: "y")
        var cancellables = Set<AnyCancellable>()

        let bothAppeared = expectation(description: "NOTIF-007: both notifications in pending")
        bothAppeared.assertForOverFulfill = false
        hub.pending.sink { snapshot in
            let hasA = snapshot.contains(where: { $0 === nA })
            let hasR = snapshot.contains(where: { $0 === nR })
            if hasA && hasR { bothAppeared.fulfill() }
        }.store(in: &cancellables)

        let tA = Task { await hub.post(nA) }
        let tR = Task { await hub.post(nR) }
        await fulfillment(of: [bothAppeared], timeout: 2.0)

        hub.resolve(nA, .approve)
        hub.resolve(nR, .reject)

        let rA = await tA.value
        let rR = await tR.value

        XCTAssertEqual(rA, .approve, "NOTIF-007: nA must resolve with .approve")
        XCTAssertEqual(rR, .reject,  "NOTIF-007: nR must resolve with .reject")
    }

    // MARK: NOTIF-008

    /// NOTIF-008 — resolving a notification not in pending is a no-op (no crash, pending unchanged).
    func testNotif008ResolveAbsentIsNoOp() async {
        let hub = NotificationHub()
        let posted = Notif(type: .confirmation, message: "real")
        let orphan = Notif(type: .notification,  message: "stray")
        let recorder = SnapshotRecorder()
        var cancellables = Set<AnyCancellable>()

        let appeared = expectation(description: "NOTIF-008: posted appears in pending")
        appeared.assertForOverFulfill = false
        hub.pending.sink { [recorder] snapshot in
            recorder.snapshots.append(snapshot)
            if snapshot.contains(where: { $0 === posted }) { appeared.fulfill() }
        }.store(in: &cancellables)

        let t = Task { await hub.post(posted) }
        await fulfillment(of: [appeared], timeout: 2.0)

        // Resolve an orphan — must not crash and must not alter pending.
        let countBefore = recorder.snapshots.count
        hub.resolve(orphan, .approve)
        let countAfter = recorder.snapshots.count

        XCTAssertEqual(countBefore, countAfter,
                       "NOTIF-008: resolving an absent notification must not emit a new pending snapshot")
        XCTAssertTrue(
            recorder.snapshots.last?.contains(where: { $0 === posted }) == true,
            "NOTIF-008: pending must still contain the originally posted notification"
        )

        // Clean up the dangling task.
        hub.resolve(posted, .approve)
        _ = await t.value
    }
}
