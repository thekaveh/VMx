//
// NotificationsVMTests — scenario tests for NotificationsVM.
//
// Ports NotesShowcase.Tests/ViewModels/NotificationsVMTests.cs (C# Avalonia flavor).
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
// Async fire-and-forget pattern:
//   `Task { _ = await notifHub.post(n) }` + `await Task.yield()` gives the
//   cooperative pool a chance to run the task's synchronous setup (which fires
//   the pending subject) before our assertion. `notifHub.dispose()` at teardown
//   resumes any pending continuations so Tasks complete cleanly.
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - NotificationsVMTests

final class NotificationsVMTests: XCTestCase {

    // MARK: - Helpers

    private struct Fixture {
        let vm: NotificationsVM
        let notifHub: NotificationHub
        let scheduler: VirtualTimeScheduler
    }

    private func build(cap: Int = 5, lifespan: TimeInterval = 5) throws -> Fixture {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let notifHub = NotificationHub()
        let scheduler = VirtualTimeScheduler()
        let vm = try NotificationsVM.builder()
            .name("notifications")
            .services(hub: hub, dispatcher: dispatcher)
            .notificationHub(notifHub)
            .scheduler(scheduler)
            .lifespan(lifespan)
            .cap(cap)
            .build()
        try vm.construct()
        return Fixture(vm: vm, notifHub: notifHub, scheduler: scheduler)
    }

    private func n(_ msg: String) -> VMx.Notification {
        VMx.Notification(type: .notification, message: msg)
    }

    /// Polls until `condition()` returns `true` or the attempt limit is exhausted.
    private func waitUntil(_ condition: @escaping () -> Bool, attempts: Int = 50) async {
        for _ in 0..<attempts {
            if condition() { return }
            await Task.yield()
        }
    }

    // MARK: - Post adds to visible

    func testPostingANotificationAddsAVMToVisible() async throws {
        let f = try build()
        defer { f.notifHub.dispose() }

        Task { _ = await f.notifHub.post(n("Saved")) }
        await Task.yield()

        XCTAssertEqual(1, f.vm.visible.count)
        XCTAssertEqual("Saved", f.vm.visible[0].notification.message)
    }

    // MARK: - Cap drops oldest

    func testCapDropsOldestWhenExceeded() async throws {
        let f = try build(cap: 5)
        defer { f.notifHub.dispose() }

        for i in 0..<7 {
            Task { _ = await f.notifHub.post(self.n("n\(i)")) }
        }
        await waitUntil { f.vm.visible.count == 5 }

        XCTAssertEqual(5, f.vm.visible.count, "Expected cap of 5 after 7 posts")
        // Two oldest dropped; survivors start at n2.
        XCTAssertEqual("n2", f.vm.visible.first?.notification.message,
                       "Expected oldest surviving notification to be 'n2'")
        XCTAssertEqual("n6", f.vm.visible.last?.notification.message,
                       "Expected newest notification to be 'n6'")
    }

    // MARK: - Resolved notifications removed

    func testResolvedNotificationsAreRemovedFromVisible() async throws {
        let f = try build()
        defer { f.notifHub.dispose() }

        let notification = n("x")
        Task { _ = await f.notifHub.post(notification) }
        await Task.yield()
        XCTAssertEqual(1, f.vm.visible.count)

        f.notifHub.resolve(notification, .approve)

        XCTAssertTrue(f.vm.visible.isEmpty,
                      "Expected visible to be empty after resolve")
    }

    // MARK: - Auto-dismiss on lifespan expiry

    func testAutoDismissWhenLifespanExpiresOnTestScheduler() async throws {
        let f = try build(lifespan: 5)
        defer { f.notifHub.dispose() }

        let notification = n("x")
        Task { _ = await f.notifHub.post(notification) }
        await Task.yield()
        XCTAssertEqual(1, f.vm.visible.count)

        // Advance past the 5-second lifespan.
        // VirtualTimeScheduler.advance(by:) fires scheduled work synchronously,
        // which calls NotificationVM.onExpire() → hub.resolve → pending sink →
        // ImmediateDispatcher.scheduleForeground → syncFromPending([]) inline.
        f.scheduler.advance(by: .seconds(6))

        XCTAssertTrue(f.vm.visible.isEmpty,
                      "Expected empty visible after lifespan expiry")
    }

    // MARK: - Dispose

    func testDisposeClearsVisibleAndUnsubscribes() async throws {
        let f = try build()
        defer { f.notifHub.dispose() }

        let n1 = n("x")
        Task { _ = await f.notifHub.post(n1) }
        await Task.yield()
        XCTAssertEqual(1, f.vm.visible.count)

        f.vm.dispose()
        XCTAssertTrue(f.vm.visible.isEmpty, "Expected empty visible after dispose")

        // After dispose, new posts must not produce updates.
        Task { _ = await f.notifHub.post(self.n("y")) }
        await Task.yield()
        XCTAssertTrue(f.vm.visible.isEmpty,
                      "Expected visible to stay empty for new post after dispose")
    }
}
