//
// NotificationVMRealTimeTests.swift — notification VMs on a real-time scheduler.
//
// See spec/16-notifications.md §6 and issue #1347. `NotificationVM` and
// `ConfirmationVM` accept any `NotificationScheduler`, so an app passes
// `DispatchQueue.main` and the timers run in real time. These tests make no
// `advance` call. NOTIF-011..016 keep `VirtualTimeScheduler` in
// NotificationVMTests.swift.
//
// The tests run on the main actor, so the VM and its timers share the main
// thread, as in an app.
//
import XCTest
import Combine
@testable import VMx

private typealias Notif = VMx.Notification

private final class RealTimePoster {
    var reaction: NotificationReaction?
    let resolved = XCTestExpectation(description: "post resolved")
}

@MainActor
final class NotificationVMRealTimeTests: XCTestCase {

    /// Post `n` and wait until the hub lists it as pending.
    private func post(_ hub: NotificationHub, _ n: Notif) async -> RealTimePoster {
        let poster = RealTimePoster()
        let registered = expectation(description: "pending registered")
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
        await fulfillment(of: [registered], timeout: 5.0)
        cancellables.removeAll()
        return poster
    }

    private func isPending(_ hub: NotificationHub, _ n: Notif) -> Bool {
        var pending: [Notif] = []
        let cancellable = hub.pending.sink { pending = $0 }
        cancellable.cancel()
        return pending.contains { $0 === n }
    }

    func testNotificationVMExpiresOnDispatchQueueMain() async {
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "toast")
        let poster = await post(hub, n)

        let sut = NotificationVM(
            notification: n, hub: hub, scheduler: DispatchQueue.main, lifespan: 0.2)

        await fulfillment(of: [poster.resolved], timeout: 5.0)
        XCTAssertEqual(poster.reaction, .approve,
                       "the lifespan timer resolves the notification with .approve")
        XCTAssertTrue(sut.isResolved)
        XCTAssertEqual(sut.remaining, 0, accuracy: 0.0001)
        sut.dispose()
    }

    func testNotificationVMDecayTicksOnDispatchQueueMain() async {
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "fading")
        let poster = await post(hub, n)

        let sut = NotificationVM(
            notification: n, hub: hub, scheduler: DispatchQueue.main,
            lifespan: 1.0, tickInterval: 0.05)
        var names: [String] = []
        var firstTickRemaining: TimeInterval?
        var firstTickOpacity: Double?
        let cancellable = sut.propertyChanged.sink { name in
            names.append(name)
            if name == "opacity", firstTickOpacity == nil, !sut.isResolved {
                firstTickRemaining = sut.remaining
                firstTickOpacity = sut.opacity
            }
        }

        await fulfillment(of: [poster.resolved], timeout: 5.0)
        cancellable.cancel()

        let resolvedAt = names.firstIndex(of: "isResolved")
        XCTAssertNotNil(resolvedAt, "the lifespan timer resolves the VM")
        let ticks = names[..<(resolvedAt ?? names.endIndex)]
        XCTAssertTrue(ticks.contains("remaining"),
                      "a decay tick raises remaining before the lifespan ends")
        XCTAssertTrue(ticks.contains("opacity"),
                      "a decay tick raises opacity before the lifespan ends")
        XCTAssertGreaterThan(firstTickRemaining ?? 0, 0)
        XCTAssertLessThan(firstTickOpacity ?? 1, 1)
        XCTAssertEqual(poster.reaction, .approve)
        sut.dispose()
    }

    func testConfirmationVMStaysPendingAfterLifespanOnDispatchQueueMain() async throws {
        let hub = NotificationHub()
        let n = Notif(type: .confirmation, message: "sure?")
        let poster = await post(hub, n)

        let sut = ConfirmationVM(
            notification: n, hub: hub, scheduler: DispatchQueue.main, lifespan: 0.1)

        try await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertFalse(sut.isResolved, "a confirmation does not resolve on expiry")
        XCTAssertTrue(isPending(hub, n), "the hub notification stays pending")
        XCTAssertNil(poster.reaction)
        XCTAssertEqual(sut.remaining, 0, accuracy: 0.0001,
                       "remaining still measures the lifespan in real time")

        sut.rejectCommand.execute()
        await fulfillment(of: [poster.resolved], timeout: 5.0)
        XCTAssertEqual(poster.reaction, .reject)
        sut.dispose()
    }

    func testDisposeCancelsTheRealTimeExpiryTimer() async throws {
        let hub = NotificationHub()
        let n = Notif(type: .notification, message: "gone")
        let poster = await post(hub, n)

        let sut = NotificationVM(
            notification: n, hub: hub, scheduler: DispatchQueue.main, lifespan: 0.1)
        sut.dispose()

        try await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertFalse(sut.isResolved)
        XCTAssertTrue(isPending(hub, n), "a disposed VM never resolves the notification")
        XCTAssertNil(poster.reaction)

        hub.resolve(n, .reject)
        await fulfillment(of: [poster.resolved], timeout: 5.0)
    }

    func testRealTimeSchedulersMeasureSeconds() {
        let queue = DispatchQueue.main
        let start = queue.now
        XCTAssertEqual(queue.seconds(from: start, to: start.advanced(by: .milliseconds(1500))),
                       1.5, accuracy: 0.0001)
        XCTAssertEqual(queue.seconds(from: start.advanced(by: .seconds(2)), to: start),
                       -2, accuracy: 0.0001)

        let runLoop = RunLoop.main
        let date = runLoop.now
        XCTAssertEqual(runLoop.seconds(from: date, to: date.advanced(by: .seconds(3))),
                       3, accuracy: 0.0001)

        let operationQueue = OperationQueue.main
        let instant = operationQueue.now
        XCTAssertEqual(
            operationQueue.seconds(from: instant, to: instant.advanced(by: .seconds(0.25))),
            0.25, accuracy: 0.0001)

        let virtual = VirtualTimeScheduler()
        let origin = virtual.now
        virtual.advance(by: .seconds(4))
        XCTAssertEqual(virtual.seconds(from: origin, to: virtual.now), 4, accuracy: 0.0001)
    }
}
