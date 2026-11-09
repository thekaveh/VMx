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

    /// #1326 — a composite on D1 whose first child is a background child on
    /// D2. The walk waits for that child; everything after the wait runs on
    /// D1's foreground, and the background child settles on D2's.
    func testResumedWalkRunsOnTheOwnersForeground() throws {
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
        // Children added before `construct()`: the walk, not population,
        // starts them.
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
        defer { subscription.cancel() }
        try composite.addResult(b).get()
        try composite.addResult(x).get()

        try composite.construct()
        XCTAssertTrue(waitUntil { composite.status == .constructed })
        XCTAssertTrue(composite.current === x)
        let constructLog = log.all
        for entry in [
            "x:constructing", "x.onConstruct", "x:constructed", "selector",
            "onCurrentChanged", "x.isCurrent", "c.current", "c:constructed",
        ] {
            XCTAssertTrue(constructLog.contains("\(entry)@d1-fg"), "\(entry) on d1: \(constructLog)")
        }
        XCTAssertTrue(constructLog.contains("b:constructed@d2-fg"), "\(constructLog)")

        try composite.destruct()
        XCTAssertTrue(waitUntil { composite.status == .destructed })
        let destructLog = log.all
        for entry in ["x:destructing", "x.onDestruct", "x:destructed", "c.onDestruct", "c:destructed"] {
            XCTAssertTrue(destructLog.contains("\(entry)@d1-fg"), "\(entry) on d1: \(destructLog)")
        }
        XCTAssertTrue(destructLog.contains("b:destructed@d2-fg"), "\(destructLog)")
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
