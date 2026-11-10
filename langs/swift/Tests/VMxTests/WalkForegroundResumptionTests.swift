//
// WalkForegroundResumptionTests.swift — #1326 regression tests.
//
// A child walk that waited and did not continue at once resumes on the
// walking VM's own foreground dispatcher (spec/02 §6, ADR-0218 rule 3).
// Later sibling starts, the `current` change, `isCurrent` changes and
// consumer callbacks then run there, not on the dispatcher of the child that
// settled last. A walk whose waits all end at once runs on the caller. Every
// wait is bounded, so a regression fails instead of hanging.
//
import Combine
import Foundation
import XCTest
@testable import VMx

final class WalkForegroundResumptionTests: XCTestCase {
    private static let queueKey = DispatchSpecificKey<String>()

    /// The label of the dispatcher queue this code runs on, or `caller`.
    private static var here: String {
        DispatchQueue.getSpecific(key: queueKey) ?? "caller"
    }

    /// A dispatcher with its own serial foreground and background queues.
    private final class QueueDispatcher: Dispatcher {
        private let foreground: DispatchQueue
        private let background: DispatchQueue
        private let holdLock = NSLock()
        private var held = false

        init(_ name: String) {
            foreground = DispatchQueue(label: "\(name)-fg")
            background = DispatchQueue(label: "\(name)-bg")
            foreground.setSpecific(key: WalkForegroundResumptionTests.queueKey, value: "\(name)-fg")
            background.setSpecific(key: WalkForegroundResumptionTests.queueKey, value: "\(name)-bg")
        }

        func scheduleForeground(_ work: @escaping () -> Void) {
            let box = UncheckedSendableBox(work)
            foreground.async { box.value() }
        }

        func scheduleBackground(_ work: @escaping () -> Void) {
            let box = UncheckedSendableBox(work)
            background.async { box.value() }
        }

        /// Holds background work until `releaseBackground()`. A background
        /// child then stays in its transient status, so the walk must wait.
        func holdBackground() {
            holdLock.withLock {
                guard !held else { return }
                held = true
                background.suspend()
            }
        }

        func releaseBackground() {
            holdLock.withLock {
                guard held else { return }
                held = false
                background.resume()
            }
        }

        // libdispatch traps when a suspended queue is released.
        deinit { releaseBackground() }

        /// Returns `true` once every foreground block scheduled so far has
        /// run, or `false` after `hangGuard`.
        func drainForeground() -> Bool {
            let drained = DispatchSemaphore(value: 0)
            foreground.async { drained.signal() }
            return drained.wait(timeout: .now() + hangGuard) == .success
        }
    }

    /// A thread-safe log of `event@queue` entries.
    private final class Log: @unchecked Sendable {
        private let lock = NSLock()
        private var entries: [String] = []
        func append(_ entry: String) { lock.withLock { entries.append("\(entry)@\(here)") } }
        var all: [String] { lock.withLock { entries } }
    }

    private func waitUntil(_ condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(hangGuard)
        while !condition() {
            if Date() >= deadline { return false }
            usleep(1_000)
        }
        return true
    }

    /// A composite on D1 whose first child `b` is a background child on D2,
    /// and whose second child `x` is a foreground child on D1. Every event is
    /// logged with the queue it ran on.
    private struct Fixture {
        let d1: QueueDispatcher
        let d2: QueueDispatcher
        let log: Log
        let x: ComponentVM
        let composite: CompositeVM<ComponentVM>
        let subscription: AnyCancellable
    }

    private func makeFixture() throws -> Fixture {
        let hub = MessageHub()
        let d1 = QueueDispatcher("d1")
        let d2 = QueueDispatcher("d2")
        let log = Log()
        let b = try ComponentVM.builder()
            .name("b").services(hub: hub, dispatcher: d2).background(true).build()
        let x = try ComponentVM.builder()
            .name("x").services(hub: hub, dispatcher: d1)
            .onConstruct { log.append("x.onConstruct") }
            .onDestruct { log.append("x.onDestruct") }
            .build()
        let composite = CompositeVM<ComponentVM>(
            name: "c", hub: hub, dispatcher: d1,
            onDestruct: { log.append("c.onDestruct") },
            currentSelector: { members in
                log.append("selector")
                return members.first { $0 === x }
            },
            onCurrentChanged: { current in
                if current != nil { log.append("onCurrentChanged") }
            }
        )
        let subscription = hub.messages.sink { message in
            if let status = message as? ConstructionStatusChangedMessage {
                log.append("\(status.senderName):\(status.status)")
            } else if let change = message as? PropertyChangedMessage,
                      change.propertyName == "isCurrent" || change.propertyName == "current" {
                log.append("\(change.senderName).\(change.propertyName)")
            }
        }
        // Children added before `construct()`: the walk, not population,
        // starts them.
        try composite.addResult(b).get()
        try composite.addResult(x).get()
        return Fixture(d1: d1, d2: d2, log: log, x: x, composite: composite, subscription: subscription)
    }

    /// Waits until the composite reaches `status` and the D1 foreground
    /// block that committed it has ended. The status changes before that
    /// block publishes it and releases the in-flight transition.
    private func waitForCommit(_ f: Fixture, _ status: ConstructionStatus) -> Bool {
        waitUntil { f.composite.status == status } && f.d1.drainForeground()
    }

    private static let constructEntries = [
        "x:constructing", "x.onConstruct", "x:constructed", "selector",
        "onCurrentChanged", "x.isCurrent", "c.current", "c:constructed",
    ]
    private static let destructEntries = [
        "x:destructing", "x.onDestruct", "x:destructed", "c.onDestruct", "c:destructed",
    ]

    /// #1326 — the walk waits for the background child `b`; everything after
    /// the wait runs on D1's foreground, and `b` settles on D2's. D2's
    /// background queue is held until `construct()` returns, so `b` cannot
    /// settle before the walk reads its status. Without the hold, a slow
    /// caller lets `b` settle first; the walk then never waits and runs on
    /// the caller, which ADR-0218 rule 3 also allows.
    func testResumedWalkRunsOnTheOwnersForeground() throws {
        let f = try makeFixture()
        defer { f.subscription.cancel() }

        f.d2.holdBackground()
        try f.composite.construct()
        // The walk is waiting for `b`.
        XCTAssertEqual(f.composite.status, .constructing)
        f.d2.releaseBackground()
        XCTAssertTrue(waitForCommit(f, .constructed))
        XCTAssertTrue(f.composite.current === f.x)
        let constructLog = f.log.all
        for entry in Self.constructEntries {
            XCTAssertTrue(constructLog.contains("\(entry)@d1-fg"), "\(entry) on d1: \(constructLog)")
        }
        XCTAssertTrue(constructLog.contains("b:constructed@d2-fg"), "\(constructLog)")

        f.d2.holdBackground()
        try f.composite.destruct()
        XCTAssertEqual(f.composite.status, .destructing)
        f.d2.releaseBackground()
        XCTAssertTrue(waitForCommit(f, .destructed))
        let destructLog = f.log.all
        for entry in Self.destructEntries {
            XCTAssertTrue(destructLog.contains("\(entry)@d1-fg"), "\(entry) on d1: \(destructLog)")
        }
        XCTAssertTrue(destructLog.contains("b:destructed@d2-fg"), "\(destructLog)")
    }

    /// #1557 — the walk waits for `b`, and the resumed walk ends on D1
    /// before `construct()` or `destruct()` registers the commit step. The
    /// commit step and the terminal publication still run on D1's
    /// foreground, not on the caller (ADR-0218 rule 3). The seam holds the
    /// caller in that window until the resumed walk has ended.
    func testCommitAfterAFinishedResumedWalkRunsOnTheOwnersForeground() throws {
        let f = try makeFixture()
        defer { f.subscription.cancel() }
        // Releases `b`, then returns once the resumed walk's last event
        // `entry` is logged and its D1 foreground block has ended.
        func holdCallerUntilTheWalkEnds(_ entry: String) {
            f.composite.afterHookReleaseForTesting = { [log = f.log, d1 = f.d1, d2 = f.d2, self] in
                d2.releaseBackground()
                XCTAssertTrue(self.waitUntil { log.all.contains(entry) }, "\(entry): \(log.all)")
                XCTAssertTrue(d1.drainForeground())
            }
        }

        holdCallerUntilTheWalkEnds("onCurrentChanged@d1-fg")
        f.d2.holdBackground()
        try f.composite.construct()
        XCTAssertTrue(waitForCommit(f, .constructed))
        let constructLog = f.log.all
        for entry in Self.constructEntries {
            XCTAssertTrue(constructLog.contains("\(entry)@d1-fg"), "\(entry) on d1: \(constructLog)")
        }

        holdCallerUntilTheWalkEnds("c.onDestruct@d1-fg")
        f.d2.holdBackground()
        try f.composite.destruct()
        XCTAssertTrue(waitForCommit(f, .destructed))
        let destructLog = f.log.all
        for entry in Self.destructEntries {
            XCTAssertTrue(destructLog.contains("\(entry)@d1-fg"), "\(entry) on d1: \(destructLog)")
        }
    }

    /// A walk whose children settle at once finishes on the caller, before
    /// `construct()` returns.
    func testWalkThatNeverWaitsFinishesOnTheCaller() throws {
        let hub = MessageHub()
        let d1 = QueueDispatcher("d1")
        let d2 = QueueDispatcher("d2")
        let log = Log()
        let first = try ComponentVM.builder()
            .name("first").services(hub: hub, dispatcher: d2).build()
        let second = try ComponentVM.builder()
            .name("second").services(hub: hub, dispatcher: d1)
            .onConstruct { log.append("second.onConstruct") }
            .build()
        let composite = CompositeVM<ComponentVM>(
            name: "c", hub: hub, dispatcher: d1,
            currentSelector: { members in
                log.append("selector")
                return members.last
            }
        )
        try composite.addResult(first).get()
        try composite.addResult(second).get()

        try composite.construct()

        XCTAssertEqual(composite.status, .constructed)
        XCTAssertTrue(composite.current === second)
        XCTAssertEqual(log.all, ["second.onConstruct@caller", "selector@caller"])
    }
}
