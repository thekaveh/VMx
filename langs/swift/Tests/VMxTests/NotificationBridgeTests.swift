//
// NotificationBridgeTests.swift — NOTIF-009/010 conformance.
//
// Claimed IDs: NOTIF-009, NOTIF-010.
//
// See spec/16-notifications.md §3-4, ADR-0013, ADR-0017.
//
// Ordering guarantee (NOTIF-010 reject path):
//   A `CapturedNotifRecorder` (reference type) is attached to `hub.pending`
//   BEFORE the makeConfirm Task starts.  `NotificationHub.post` stores the
//   continuation *before* emitting a snapshot (see NotificationHub.swift), so
//   by the time `fulfillment(of:)` returns (expectation fulfilled inside the
//   sink), the continuation is already registered.  We then call resolve()
//   outside the sink — safe, no risk of resolving-before-post race.
//
import XCTest
import Combine
@testable import VMx

// Disambiguate VMx.Notification from Foundation.Notification.
private typealias Notif = VMx.Notification

// MARK: - Reference-type recorder

/// Captures the first Notification seen in a pending snapshot — reference type
/// so it survives @escaping / async Combine sink closures without value-copy loss.
private final class CapturedNotifRecorder {
    var notification: Notif?
}

// MARK: - Tests

final class NotificationBridgeTests: XCTestCase {

    // MARK: NOTIF-009

    /// NOTIF-009 — NullNotificationHub: post → .approve immediately; resolve is a
    /// no-op (no crash); pending always emits an empty snapshot.
    func testNotif009NullNotificationHub() async {
        let hub: any NotificationHubProtocol = NullNotificationHub.INSTANCE
        let n = Notif(type: .confirmation, message: "x")

        // post returns .approve without any suspension
        let reaction = await hub.post(n)
        XCTAssertEqual(reaction, .approve,
                       "NOTIF-009: NullNotificationHub.post must return .approve immediately")

        // resolve with any reaction must not crash
        hub.resolve(n, .approve)
        hub.resolve(n, .reject)

        // pending always delivers an empty snapshot on subscribe
        var observed: [Notif]?
        var cancellables = Set<AnyCancellable>()
        hub.pending.sink { snapshot in
            observed = snapshot
        }.store(in: &cancellables)
        XCTAssertEqual(observed?.count, 0,
                       "NOTIF-009: NullNotificationHub.pending must always emit []")
    }

    // MARK: NOTIF-010

    /// NOTIF-010 — makeConfirm returns true iff the hub resolves .approve.
    func testNotif010MakeConfirm() async {
        // Approve path: NullNotificationHub auto-approves every post.
        let nullHub: any NotificationHubProtocol = NullNotificationHub.INSTANCE
        let confirmApprove = makeConfirm(nullHub, "ok?")
        let resultApprove = await confirmApprove()
        XCTAssertTrue(resultApprove,
                      "NOTIF-010: makeConfirm must return true when hub resolves .approve")

        // Reject path: real NotificationHub explicitly resolved to .reject.
        let hub = NotificationHub()
        var cancellables = Set<AnyCancellable>()
        let confirmReject = makeConfirm(hub, "ok?")

        // Attach sink BEFORE starting the Task — guarantees the continuation is
        // registered inside hub.post before we call resolve() below.
        let appeared = expectation(description: "NOTIF-010: notification appeared in pending")
        appeared.assertForOverFulfill = false
        let recorder = CapturedNotifRecorder()
        hub.pending.sink { [recorder] snapshot in
            if let n = snapshot.first, recorder.notification == nil {
                recorder.notification = n
                appeared.fulfill()
            }
        }.store(in: &cancellables)

        let t = Task { await confirmReject() }
        await fulfillment(of: [appeared], timeout: 2.0)

        // Resolve outside the sink — safe, no recursive subject.send risk.
        if let n = recorder.notification {
            hub.resolve(n, .reject)
        }
        let resultReject = await t.value
        XCTAssertFalse(resultReject,
                       "NOTIF-010: makeConfirm must return false when hub resolves .reject")
    }
}
