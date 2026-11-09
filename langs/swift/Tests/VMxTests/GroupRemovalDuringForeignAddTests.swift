//
// GroupRemovalDuringForeignAddTests.swift — #728 and ADR-0187 tests.
//
// `GroupVM.remove`, `removeAt` and `clear` never wait for an open membership
// transaction (ADR-0187). On another thread and on the thread that holds the
// transaction, they return at once and leave the group unchanged. Every wait
// is bounded.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private final class SharedValue<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: T
    init(_ value: T) { storage = value }
    var value: T {
        get { lock.withLock { storage } }
        set { lock.withLock { storage = newValue } }
    }
}

final class GroupRemovalDuringForeignAddTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        cancellables.removeAll()
        super.tearDown()
    }

    private func child(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder()
            .name(name)
            .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
    }

    private func names(_ group: GroupVM<ComponentVM>) -> [String] {
        (0..<group.count).map { group.at($0).name }
    }

    /// Thread A adds `c1` and blocks in a `collectionChanged` sink, inside the
    /// group's transaction. Thread B runs `removal`, which must return before
    /// A's add ends.
    private func runRemovalDuringForeignAdd(
        _ removal: @escaping (GroupVM<ComponentVM>) -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) throws -> GroupVM<ComponentVM> {
        let group = GroupVM<ComponentVM>(
            name: "group", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
        try group.addResult(child("existing")).get()
        try group.addResult(child("other")).get()

        let aInSink = DispatchSemaphore(value: 0)
        let bReturned = DispatchSemaphore(value: 0)
        let aDone = DispatchSemaphore(value: 0)
        let bDone = DispatchSemaphore(value: 0)
        let blockOnce = SharedValue(true)
        let aSinkFinished = SharedValue(false)
        let bReturnedEarly = SharedValue(false)
        group.collectionChanged.sink { _ in
            guard blockOnce.value else { return }
            blockOnce.value = false
            aInSink.signal()
            // B returns at once, or (before ADR-0187) waits for this add.
            _ = bReturned.wait(timeout: .now() + 1)
            aSinkFinished.value = true
        }.store(in: &cancellables)

        let c1 = try child("c1")
        Thread.detachNewThread {
            _ = group.addResult(c1)
            aDone.signal()
        }
        XCTAssertEqual(aInSink.wait(timeout: .now() + hangGuard), .success, file: file, line: line)
        Thread.detachNewThread {
            removal(group)
            bReturnedEarly.value = !aSinkFinished.value
            bReturned.signal()
            bDone.signal()
        }

        XCTAssertEqual(aDone.wait(timeout: .now() + hangGuard * 2), .success, "the add hung", file: file, line: line)
        XCTAssertEqual(bDone.wait(timeout: .now() + hangGuard), .success, "the removal hung", file: file, line: line)
        XCTAssertTrue(bReturnedEarly.value, "the removal waited for the add", file: file, line: line)
        return group
    }

    func testRemoveFailsAtOnceDuringAnotherThreadsAdd() throws {
        let removed = SharedValue<Bool?>(nil)
        let group = try runRemovalDuringForeignAdd { group in
            let existing = (0..<group.count).map { group.at($0) }.first { $0.name == "existing" }!
            removed.value = group.remove(existing)
        }
        XCTAssertEqual(removed.value, false)
        XCTAssertEqual(names(group), ["existing", "other", "c1"])
    }

    func testRemoveAtFailsAtOnceDuringAnotherThreadsAdd() throws {
        let group = try runRemovalDuringForeignAdd { $0.removeAt(0) }
        XCTAssertEqual(names(group), ["existing", "other", "c1"])
    }

    func testClearFailsAtOnceDuringAnotherThreadsAdd() throws {
        let group = try runRemovalDuringForeignAdd { $0.clear() }
        XCTAssertEqual(names(group), ["existing", "other", "c1"])
    }

    func testRemoveDuringAnAddOnTheSameThreadIsRefusedWithoutAWait() throws {
        let group = GroupVM<ComponentVM>(
            name: "group", hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
        let existing = try child("existing")
        try group.addResult(existing).get()
        let result = SharedValue<Bool?>(nil)
        group.collectionChanged.sink { _ in
            guard result.value == nil else { return }
            result.value = group.remove(existing)
        }.store(in: &cancellables)

        let done = DispatchSemaphore(value: 0)
        Thread.detachNewThread {
            _ = group.addResult(try! ComponentVM.builder()
                .name("c1")
                .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
                .build())
            done.signal()
        }
        XCTAssertEqual(done.wait(timeout: .now() + hangGuard), .success, "the same-thread removal waited")
        XCTAssertEqual(result.value, false)
        XCTAssertEqual(names(group), ["existing", "c1"])
    }
}
