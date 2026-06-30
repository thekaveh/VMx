//
// NotificationVMTests.swift — NOTIF-011..016 conformance.
//
// Claimed IDs: NOTIF-011, NOTIF-012, NOTIF-013, NOTIF-014, NOTIF-015,
//              NOTIF-016.
//
// See spec/16-notifications.md §6-7, ADR-0031.
//
// Virtual time is driven by `VirtualTimeScheduler` (Sources/VMx/Services):
// `scheduler.advance(toSeconds:)` moves the virtual clock and runs every
// scheduled action whose due time it crosses — deterministic, no real delays.
//
// Time unit is SECONDS throughout (lifespan / opacity / scheduler).
//
// Ordering guarantee for the post → resolve tests:
//   `post(_:_:)` attaches a `hub.pending` sink and awaits an expectation that
//   fulfills once the notification appears in a pending snapshot. Because
//   `NotificationHub.post` stores its continuation BEFORE emitting the snapshot,
//   this guarantees the waiter is registered before any later `hub.resolve`
//   (from the VM's auto-dismiss / command / external resolve) runs — preventing
//   a resolve-races-post hang.
//
// Reference-type recorders (`Poster`, `NameRecorder`, `PendingRecorder`) are
// used for every @escaping / async closure capture to avoid value-copy loss.
//
import XCTest
import Combine
@testable import VMx

// Disambiguate VMx.Notification from Foundation.Notification.
private typealias Notif = VMx.Notification

// MARK: - Reference-type recorders

/// Captures the awaited reaction value returned by `hub.post`, plus an
/// expectation fulfilled when the post resolves.
private final class Poster {
    var reaction: NotificationReaction?
    let resolved = XCTestExpectation(description: "post resolved")
}

/// Records every property name emitted on `propertyChanged`.
private final class NameRecorder {
    var names: [String] = []
}

/// Records the latest `pending` snapshot.
private final class PendingRecorder {
    var last: [Notif] = []
}

// MARK: - Tests

final class NotificationVMTests: XCTestCase {

    /// Post `n` on `hub` and wait until it is registered in `pending`,
    /// returning a `Poster` whose `reaction` / `resolved` are populated once the
    /// awaitable resolves.
    private func post(_ hub: NotificationHub, _ n: Notif) async -> Poster {
        let poster = Poster()
        let registered = expectation(description: "NOTIF: pending registered")
        registered.assertForOverFulfill = false
        var cancellables = Set<AnyCancellable>()
        hub.pending
            .sink { snapshot in
                if snapshot.contains(where: { $0 === n }) { registered.fulfill() }
            }
            .store(in: &cancellables)
        Task {
            poster.reaction = await hub.post(n)
            poster.resolved.fulfill()
        }
        await fulfillment(of: [registered], timeout: 2.0)
        cancellables.removeAll()
        return poster
    }

    // MARK: NOTIF-011

    /// NOTIF-011 — opacity decays linearly 1.0 → 0.5 → 0.0 over the lifespan as
    /// the VirtualTimeScheduler advances.
    func testNotif011OpacityDecaysLinearly() async {
        let scheduler = VirtualTimeScheduler()
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "hi")
        _ = await post(hub, n)
        let sut = NotificationVM(notification: n, hub: hub, scheduler: scheduler, lifespan: 10)

        XCTAssertEqual(sut.opacity, 1.0, accuracy: 0.001,
                       "NOTIF-011: opacity is 1.0 at t0")

        scheduler.advance(toSeconds: 5)
        XCTAssertEqual(sut.opacity, 0.5, accuracy: 0.01,
                       "NOTIF-011: opacity is ~0.5 at lifespan/2")

        scheduler.advance(toSeconds: 10)
        XCTAssertEqual(sut.opacity, 0.0, accuracy: 0.01,
                       "NOTIF-011: opacity is ~0.0 at lifespan")

        sut.dispose()
    }

    // MARK: NOTIF-012

    /// NOTIF-012 — auto-dismiss: at lifespan expiry the VM resolves the hub
    /// notification with `.approve`.
    func testNotif012AutoDismissResolvesApprove() async {
        let scheduler = VirtualTimeScheduler()
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "auto")
        let poster = await post(hub, n)
        let sut = NotificationVM(notification: n, hub: hub, scheduler: scheduler, lifespan: 10)

        XCTAssertFalse(sut.isResolved, "NOTIF-012: not resolved before expiry")

        scheduler.advance(toSeconds: 10)

        XCTAssertTrue(sut.isResolved, "NOTIF-012: resolved at lifespan")
        await fulfillment(of: [poster.resolved], timeout: 2.0)
        XCTAssertEqual(poster.reaction, .approve,
                       "NOTIF-012: auto-dismiss resolves with .approve")

        sut.dispose()
    }

    // MARK: NOTIF-013

    /// NOTIF-013 — ConfirmationVM exposes approve/reject commands resolving the
    /// matching reaction, and does NOT auto-resolve at lifespan expiry.
    func testNotif013ConfirmationCommandsAndNoAutoResolve() async {
        // Approve path — also proves no auto-resolve past the 300 s default.
        let schedulerA = VirtualTimeScheduler()
        let hubA = NotificationHub()
        let nA = Notif(type: .confirmation, message: "approve me")
        let posterA = await post(hubA, nA)
        let sutA = ConfirmationVM(notification: nA, hub: hubA, scheduler: schedulerA)

        schedulerA.advance(toSeconds: 1000)  // well past the 300 s default lifespan
        XCTAssertFalse(sutA.isResolved,
                       "NOTIF-013: ConfirmationVM must NOT auto-resolve at lifespan")

        sutA.approveCommand.execute()
        XCTAssertTrue(sutA.isResolved)
        await fulfillment(of: [posterA.resolved], timeout: 2.0)
        XCTAssertEqual(posterA.reaction, .approve,
                       "NOTIF-013: approveCommand resolves with .approve")
        sutA.dispose()

        // Reject path.
        let schedulerR = VirtualTimeScheduler()
        let hubR = NotificationHub()
        let nR = Notif(type: .confirmation, message: "reject me")
        let posterR = await post(hubR, nR)
        let sutR = ConfirmationVM(notification: nR, hub: hubR, scheduler: schedulerR)

        sutR.rejectCommand.execute()
        XCTAssertTrue(sutR.isResolved)
        await fulfillment(of: [posterR.resolved], timeout: 2.0)
        XCTAssertEqual(posterR.reaction, .reject,
                       "NOTIF-013: rejectCommand resolves with .reject")
        sutR.dispose()
    }

    // MARK: NOTIF-014

    /// NOTIF-014 — a manual `dismissCommand` cancels the lifespan timer:
    /// advancing past expiry does NOT re-resolve (resolves exactly once).
    func testNotif014DismissCancelsTimer() async {
        let scheduler = VirtualTimeScheduler()
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "dismiss")
        let poster = await post(hub, n)
        let sut = NotificationVM(notification: n, hub: hub, scheduler: scheduler, lifespan: 10)

        let names = NameRecorder()
        var cancellables = Set<AnyCancellable>()
        sut.propertyChanged.sink { names.names.append($0) }.store(in: &cancellables)

        sut.dismissCommand.execute()
        XCTAssertTrue(sut.isResolved, "NOTIF-014: dismissed manually")
        await fulfillment(of: [poster.resolved], timeout: 2.0)
        XCTAssertEqual(poster.reaction, .approve)

        // Advance past lifespan — the cancelled timer must not fire again.
        scheduler.advance(toSeconds: 20)
        XCTAssertTrue(sut.isResolved)
        XCTAssertEqual(names.names.filter { $0 == "isResolved" }.count, 1,
                       "NOTIF-014: resolves exactly once; timer cancelled")

        // The notification is gone from pending (resolved once, not twice).
        let pending = PendingRecorder()
        hub.pending.sink { pending.last = $0 }.store(in: &cancellables)
        XCTAssertFalse(pending.last.contains { $0 === n },
                       "NOTIF-014: notification removed from pending")

        cancellables.removeAll()
        sut.dispose()
    }

    // MARK: NOTIF-015

    /// NOTIF-015 — an external `hub.resolve(...)` propagates to `isResolved` and
    /// cancels the timer (advancing past lifespan does not re-fire).
    func testNotif015ExternalResolvePropagates() async {
        let scheduler = VirtualTimeScheduler()
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "hub resolves")
        let poster = await post(hub, n)
        let sut = NotificationVM(notification: n, hub: hub, scheduler: scheduler, lifespan: 60)

        XCTAssertFalse(sut.isResolved, "NOTIF-015: not resolved initially")

        hub.resolve(n, .approve)  // external resolution
        XCTAssertTrue(sut.isResolved, "NOTIF-015: external resolve propagates")
        await fulfillment(of: [poster.resolved], timeout: 2.0)
        XCTAssertEqual(poster.reaction, .approve)

        // The timer was cancelled — no further resolution emissions.
        let names = NameRecorder()
        var cancellables = Set<AnyCancellable>()
        sut.propertyChanged.sink { names.names.append($0) }.store(in: &cancellables)
        scheduler.advance(toSeconds: 60)
        XCTAssertTrue(sut.isResolved)
        XCTAssertEqual(names.names.filter { $0 == "isResolved" }.count, 0,
                       "NOTIF-015: timer cancelled — no re-fire after external resolve")

        cancellables.removeAll()
        sut.dispose()
    }

    // MARK: NOTIF-016

    /// NOTIF-016 — deterministic under the injected scheduler: opacity tracks
    /// virtual time, auto-dismiss fires exactly once, and advancing far past
    /// the lifespan never double-resolves.
    func testNotif016DeterministicSingleResolution() async {
        let scheduler = VirtualTimeScheduler()
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "tick")
        let poster = await post(hub, n)
        let sut = NotificationVM(notification: n, hub: hub, scheduler: scheduler, lifespan: 10)

        let names = NameRecorder()
        var cancellables = Set<AnyCancellable>()
        sut.propertyChanged.sink { names.names.append($0) }.store(in: &cancellables)

        XCTAssertEqual(sut.opacity, 1.0, accuracy: 0.001)
        XCTAssertFalse(sut.isResolved)

        scheduler.advance(toSeconds: 5)
        XCTAssertEqual(sut.opacity, 0.5, accuracy: 0.01)
        XCTAssertFalse(sut.isResolved)

        scheduler.advance(toSeconds: 10)
        XCTAssertTrue(sut.isResolved, "NOTIF-016: auto-dismissed at lifespan")
        XCTAssertEqual(sut.opacity, 0.0, accuracy: 0.01)
        await fulfillment(of: [poster.resolved], timeout: 2.0)
        XCTAssertEqual(poster.reaction, .approve)

        // No double-resolve: advancing far past lifespan is inert.
        scheduler.advance(toSeconds: 110)
        XCTAssertTrue(sut.isResolved)
        XCTAssertEqual(names.names.filter { $0 == "isResolved" }.count, 1,
                       "NOTIF-016: auto-dismiss fires exactly once")

        cancellables.removeAll()
        sut.dispose()
    }
}
