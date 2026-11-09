//
// CompositeInitialCurrentLiveMembershipTests.swift — #705 regression tests.
//
// The initial-current selector's pick is assigned through a non-raising
// validated assignment (spec/06 §3.2): a pick that is no longer a member
// when the construct walk assigns it is a silent no-op. When the walk resumes
// on a thread inside its own uncommitted membership transaction, the
// assignment is also a silent no-op (spec/06 §4.3 rule 4, ADR-0173).
//

import Combine
import Foundation
import XCTest
@testable import VMx

final class CompositeInitialCurrentLiveMembershipTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func currentMessages(from composite: AnyObject, on hub: MessageHub) -> () -> Int {
        let lock = NSLock()
        var count = 0
        hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.sender === composite && $0.propertyName == "current" }
            .sink { _ in
                lock.lock()
                count += 1
                lock.unlock()
            }
            .store(in: &cancellables)
        return {
            lock.lock()
            defer { lock.unlock() }
            return count
        }
    }

    func testPickRemovedByASiblingHookIsANoOp() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        weak var compositeRef: CompositeVM<ComponentVM>?
        let s = try ComponentVM.builder().name("s").services(hub: hub, dispatcher: dispatcher).build()
        let c1 = try ComponentVM.builder()
            .name("c1")
            .services(hub: hub, dispatcher: dispatcher)
            .onConstruct { XCTAssertEqual(compositeRef?.remove(s), true) }
            .build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub, dispatcher: dispatcher)
            .children { [] }
            .current { _ in s }
            .build()
        compositeRef = composite
        composite.add(c1)
        composite.add(s)
        let currentChanges = currentMessages(from: composite, on: hub)

        try composite.construct()

        XCTAssertEqual(composite.status, .constructed)
        XCTAssertNil(composite.current)
        XCTAssertEqual(currentChanges(), 0)
    }

    func testPickRemovedWhileABackgroundSiblingConstructsIsANoOp() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let background = try ComponentVM.builder()
            .name("background").services(hub: hub, dispatcher: dispatcher).background(true).build()
        let s = try ComponentVM.builder().name("s").services(hub: hub, dispatcher: dispatcher).build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub, dispatcher: dispatcher)
            .children { [background, s] }
            .current { _ in s }
            .build()
        let currentChanges = currentMessages(from: composite, on: hub)

        try composite.construct()
        XCTAssertEqual(composite.status, .constructing)
        XCTAssertTrue(composite.remove(s))
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }

        XCTAssertEqual(composite.status, .constructed)
        XCTAssertNil(composite.current)
        XCTAssertEqual(currentChanges(), 0)
    }

    /// The walk resumes on the adding thread before that add admits its child.
    /// Under ADR-0173 rule 4 the assignment there is a silent no-op, so the
    /// composite reaches Constructed with no current child. (#705 selected the
    /// pick by joining the add's transaction; ADR-0173 replaced the join.)
    func testWalkResumingInsideTheAddersUncommittedTransactionIsANoOp() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let lateStarted = DispatchSemaphore(value: 0)
        let releaseLate = DispatchSemaphore(value: 0)
        let addFinished = DispatchSemaphore(value: 0)

        // A background sibling defers the walk. `late` is then added from
        // another thread and auto-constructed inside that add; its hook holds
        // until the background sibling has settled, so the walk resumes on
        // the adding thread inside its membership transaction.
        let late = try ComponentVM.builder()
            .name("late")
            .services(hub: hub, dispatcher: dispatcher)
            .onConstruct { _ = releaseLate.wait(timeout: .now() + hangGuard * 2) }
            .build()
        let picked = try ComponentVM.builder()
            .name("picked").services(hub: hub, dispatcher: dispatcher).build()
        let background = try ComponentVM.builder()
            .name("background").services(hub: hub, dispatcher: dispatcher).background(true).build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub, dispatcher: dispatcher)
            .autoConstructOnAdd()
            .children { [picked, background] }
            .current { children in children.first { $0 === picked } }
            .build()
        let currentChanges = currentMessages(from: composite, on: hub)

        try composite.construct()
        XCTAssertEqual(composite.status, .constructing)
        Thread {
            lateStarted.signal()
            composite.add(late)
            addFinished.signal()
        }.start()
        XCTAssertEqual(lateStarted.wait(timeout: .now() + hangGuard), .success)
        let deadline = Date().addingTimeInterval(hangGuard)
        while late.status != .constructing && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.001)
        }
        XCTAssertEqual(late.status, .constructing)
        dispatcher.flushBackground()
        dispatcher.flushForeground()
        releaseLate.signal()
        XCTAssertEqual(addFinished.wait(timeout: .now() + hangGuard), .success, "the add stalled")
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }

        XCTAssertEqual(composite.status, .constructed)
        XCTAssertNil(composite.current)
        XCTAssertEqual(currentChanges(), 0)
        XCTAssertTrue(composite.canSelectComponent(picked))
    }
}
