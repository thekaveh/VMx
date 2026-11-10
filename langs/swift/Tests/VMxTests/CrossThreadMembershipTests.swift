//
// CrossThreadMembershipTests.swift — a membership change fails at once while
// another thread holds the container's membership transaction (spec/06 §4.2,
// spec/07 §4, ADR-0187, #1314).
//
// Claimed IDs: COMP-048, GRP-016.
//
// Thread A adds a child and holds the add's transaction open in a blocking
// `collectionChanged` subscriber. Thread B then tries every membership change.
// Each change must return at once with no change, before A is released. Every
// wait is bounded, so a regression fails instead of hanging.
//
// NOTE: `swift test` needs full Xcode (XCTest); CI runs it on macos-15.
//
import Combine
import XCTest
import Foundation
@testable import VMx

final class CrossThreadMembershipTests: XCTestCase {
    /// The bound on every wait in these tests, in seconds.
    private let bound: TimeInterval = 5

    private final class Locked<T> {
        private let lock = NSLock()
        private var stored: T
        init(_ value: T) { stored = value }
        var value: T {
            get { lock.withLock { stored } }
            set { lock.withLock { stored = newValue } }
        }
        func mutate(_ change: (inout T) -> Void) { lock.withLock { change(&stored) } }
    }

    /// One container under test, seen through closures.
    private struct Container {
        let vm: ComponentVMBase
        let changes: AnyPublisher<CollectionChangedEvent, Never>
        let add: (ComponentVM) -> Result<Void, ContainerOwnershipError>
        let insert: (ComponentVM, Int) -> Result<Void, ContainerOwnershipError>
        let replace: (Int, ComponentVM) -> Result<Void, ContainerOwnershipError>
        let remove: (ComponentVM) -> Bool
        let removeAt: (Int) -> Void
        let clear: () -> Void
        let snapshot: () -> [ComponentVM]
        let current: () -> ComponentVM?
    }

    private func leaf(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder()
            .name(name)
            .services(hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
    }

    private func makeContainer(
        _ kind: String, name: String, factory: (() -> [ComponentVM])? = nil
    ) -> Container {
        if kind == "composite" {
            let c = CompositeVM<ComponentVM>(
                name: name, hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE,
                childrenFactory: factory
            )
            return Container(
                vm: c, changes: c.collectionChanged,
                add: c.addResult, insert: c.insertResult, replace: c.replaceResult,
                remove: c.remove, removeAt: c.removeAt, clear: c.clear,
                snapshot: c.snapshot, current: { c.current }
            )
        }
        let g = GroupVM<ComponentVM>(
            name: name, hub: NullMessageHub.INSTANCE, dispatcher: ImmediateDispatcher.INSTANCE,
            childrenFactory: factory
        )
        return Container(
            vm: g, changes: g.collectionChanged,
            add: g.addResult, insert: g.insertResult, replace: g.replaceResult,
            remove: g.remove, removeAt: g.removeAt, clear: g.clear,
            snapshot: g.snapshot, current: { nil }
        )
    }

    private func isInProgress(_ result: Result<Void, ContainerOwnershipError>) -> Bool {
        guard case .failure(.attachmentFailed(let inner)) = result else { return false }
        return inner is ContainerMembershipTransactionError
    }

    private func isInProgress(_ error: Error) -> Bool {
        guard case ContainerOwnershipError.attachmentFailed(let inner) = error else { return false }
        return inner is ContainerMembershipTransactionError
    }

    private func runCrossThreadChanges(_ kind: String) throws {
        let k = try leaf("k")
        let x = try leaf("x")
        let y = try leaf("y")
        let populated = try leaf("populated")
        let p = makeContainer(kind, name: "p", factory: { [populated] })
        let q = makeContainer(kind, name: "q")
        XCTAssertNoThrow(try p.add(k).get(), kind)
        if let composite = p.vm as? CompositeVM<ComponentVM> { try composite.setCurrent(k) }
        let kParent = k._parent

        let events = Locked<[String]>([])
        let qEvents = Locked<[String]>([])
        let opened = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        let holdOnce = Locked(true)
        let bound = self.bound
        var subscriptions = Set<AnyCancellable>()
        p.changes.sink { event in
            events.mutate { $0.append("\(event)") }
            guard holdOnce.value else { return }
            holdOnce.value = false
            opened.signal()
            _ = release.wait(timeout: .now() + bound)
        }.store(in: &subscriptions)
        q.changes.sink { event in qEvents.mutate { $0.append("\(event)") } }.store(in: &subscriptions)

        // Thread A holds p's membership transaction inside its add.
        let aDone = DispatchSemaphore(value: 0)
        let aResult = Locked<Result<Void, ContainerOwnershipError>?>(nil)
        Thread {
            aResult.value = p.add(x)
            aDone.signal()
        }.start()
        XCTAssertEqual(opened.wait(timeout: .now() + bound), .success, "\(kind): A holds the transaction")
        let heldSnapshot = p.snapshot()

        // Thread B tries every membership change while A holds the transaction.
        let bDone = DispatchSemaphore(value: 0)
        let outcomes = Locked<[String: Bool]>([:])
        Thread {
            var o: [String: Bool] = [:]
            o["add"] = self.isInProgress(p.add(y))
            o["insert"] = self.isInProgress(p.insert(y, 0))
            o["replace"] = self.isInProgress(p.replace(0, y))
            do {
                try p.vm.construct()
                o["population"] = false
            } catch {
                o["population"] = self.isInProgress(error)
            }
            o["transfer"] = self.isInProgress(q.add(k))
            o["remove"] = !p.remove(k)
            p.removeAt(0)
            p.clear()
            outcomes.value = o
            bDone.signal()
        }.start()
        let bFinished = bDone.wait(timeout: .now() + 2)
        XCTAssertEqual(bFinished, .success, "\(kind): B's changes must not wait for A")

        XCTAssertEqual(
            outcomes.value,
            ["add": true, "insert": true, "replace": true, "population": true,
             "transfer": true, "remove": true],
            "\(kind): each change fails with the in-progress error"
        )
        XCTAssertTrue(p.snapshot().elementsEqual(heldSnapshot, by: ===), "\(kind): membership unchanged")
        XCTAssertEqual(p.vm.status, .destructed, "\(kind): the refused population rolled back")
        XCTAssertTrue(k._parent === kParent, "\(kind): k keeps its parent link")
        XCTAssertNil(y._parent, kind)
        XCTAssertNil(populated._parent, kind)
        XCTAssertEqual(q.snapshot().count, 0, "\(kind): the transfer destination is unchanged")
        XCTAssertEqual(qEvents.value, [], kind)
        if kind == "composite" { XCTAssertTrue(p.current() === k, "composite: Current unchanged") }
        XCTAssertEqual(events.value.count, 1, "\(kind): only A's add was published")

        release.signal()
        XCTAssertEqual(aDone.wait(timeout: .now() + bound), .success, "\(kind): A finishes")
        if bFinished != .success { _ = bDone.wait(timeout: .now() + bound) }
        guard case .success = aResult.value else { return XCTFail("\(kind): A's add failed") }

        // After the transaction ends, the same changes succeed.
        XCTAssertNoThrow(try p.add(y).get(), kind)
        XCTAssertTrue(p.remove(y), kind)
        XCTAssertTrue(p.snapshot().elementsEqual([k, x], by: ===), kind)
        subscriptions.removeAll()
    }

    /// COMP-048 — while another thread holds a composite's membership
    /// transaction, add, insert, replacement, population, transfer out,
    /// remove, removeAt and clear fail at once and change nothing.
    func testCOMP048MembershipChangesFailAtOnceDuringAnotherThreadsTransaction() throws {
        try runCrossThreadChanges("composite")
    }

    /// GRP-016 — while another thread holds a group's membership transaction,
    /// add, insert, replacement, population, transfer out, remove, removeAt
    /// and clear fail at once and change nothing.
    func testGRP016MembershipChangesFailAtOnceDuringAnotherThreadsTransaction() throws {
        try runCrossThreadChanges("group")
    }
}
