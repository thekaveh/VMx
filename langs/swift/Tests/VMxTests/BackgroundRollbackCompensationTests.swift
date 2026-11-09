//
// BackgroundRollbackCompensationTests.swift — COMP-054 and GRP-017 (#1372).
//
// A failed add, insert or index replacement that auto-started a background
// child does not wait for that child. When the child's construct settles at
// `Constructed` with no parent, VMx calls its `destruct()`, so the child ends
// `Destructed` (spec/06 §4.2, ADR-0218 rule 7). A queued background
// scheduler drives every case on one thread.
//
import Combine
import Foundation
import XCTest
@testable import VMx

final class BackgroundRollbackCompensationTests: XCTestCase {
    /// The operations a case needs from a composite or a group.
    private struct Container {
        let vm: ComponentVMBase
        let change: (ComponentVM) -> Result<Void, ContainerOwnershipError>
    }

    private enum Operation: String, CaseIterable {
        case add, insert, replace
    }

    /// Runs background hooks and their foreground completions until quiescent.
    private func pump(_ dispatcher: ManualDispatcher) {
        for _ in 0..<10 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    /// A container with auto-construct-on-add and one factory member. A
    /// background member holds the container `Constructing`; a synchronous
    /// one lets it reach `Constructed`.
    private func makeContainer(
        _ kind: String,
        _ operation: Operation,
        hub: MessageHub,
        dispatcher: ManualDispatcher,
        constructing: Bool
    ) throws -> Container {
        let member = try ComponentVM.builder()
            .name("member").services(hub: hub, dispatcher: dispatcher)
            .background(constructing).build()
        if kind == "composite" {
            let vm = CompositeVM<ComponentVM>(
                name: kind, hub: hub, dispatcher: dispatcher,
                childrenFactory: { [member] }, autoConstructOnAdd: true
            )
            return Container(vm: vm, change: { child in
                switch operation {
                case .add: return vm.addResult(child)
                case .insert: return vm.insertResult(child, at: 0)
                case .replace: return vm.replaceResult(at: 0, with: child)
                }
            })
        }
        let vm = GroupVM<ComponentVM>(
            name: kind, hub: hub, dispatcher: dispatcher,
            childrenFactory: { [member] }, autoConstructOnAdd: true
        )
        return Container(vm: vm, change: { child in
            switch operation {
            case .add: return vm.addResult(child)
            case .insert: return vm.insertResult(child, at: 0)
            case .replace: return vm.replaceResult(at: 0, with: child)
            }
        })
    }

    /// The child's `Constructing` publication disposes the container, so the
    /// change fails after it started the child. A background child is still
    /// `Constructing` at the rollback and ends `Destructed` once drained; a
    /// synchronous child is destructed at once.
    private func assertRollbackDestructsChild(
        _ kind: String, constructing: Bool, background: Bool
    ) throws {
        for operation in Operation.allCases {
            let label = "\(kind) \(operation) constructing=\(constructing) background=\(background)"
            let hub = MessageHub()
            let dispatcher = ManualDispatcher()
            let container = try makeContainer(
                kind, operation, hub: hub, dispatcher: dispatcher, constructing: constructing
            )
            try container.vm.construct()
            XCTAssertEqual(
                container.vm.status, constructing ? .constructing : .constructed, label
            )
            let child = try ComponentVM.builder()
                .name("child").services(hub: hub, dispatcher: dispatcher)
                .background(background).build()
            let subscription = hub.messages
                .compactMap { $0 as? ConstructionStatusChangedMessage }
                .filter { $0.senderName == "child" && $0.status == .constructing }
                .sink { _ in container.vm.dispose() }
            defer { subscription.cancel() }

            let result = container.change(child)

            guard case .failure(.attachmentFailed) = result else {
                XCTFail("\(label): expected attachmentFailed, got \(result)")
                continue
            }
            XCTAssertNil(child._ownershipParent, label)
            XCTAssertNil(child._parent, label)
            XCTAssertEqual(container.vm.status, .disposed, label)
            if background {
                XCTAssertEqual(child.status, .constructing, "\(label): no wait for the child")
            }
            pump(dispatcher)
            XCTAssertEqual(child.status, .destructed, label)
            XCTAssertNil(child._ownershipParent, label)
        }
    }

    /// COMP-054 — a failed composite change that auto-started a background
    /// child returns that child to `Destructed` once its construct settles
    /// `Constructed` with no parent; the failed change does not wait for it.
    func testCOMP054RollbackDestructsBackgroundChildOnceItSettles() throws {
        try assertRollbackDestructsChild("composite", constructing: false, background: true)
        try assertRollbackDestructsChild("composite", constructing: true, background: true)
    }

    /// COMP-054 — control: a synchronous child is `Constructed` at the
    /// rollback, which destructs it at once.
    func testCOMP054RollbackDestructsSynchronousChildAtOnce() throws {
        try assertRollbackDestructsChild("composite", constructing: false, background: false)
        try assertRollbackDestructsChild("composite", constructing: true, background: false)
    }

    /// GRP-017 — a failed group change that auto-started a background child
    /// returns that child to `Destructed` once its construct settles
    /// `Constructed` with no parent; the failed change does not wait for it.
    func testGRP017RollbackDestructsBackgroundChildOnceItSettles() throws {
        try assertRollbackDestructsChild("group", constructing: false, background: true)
        try assertRollbackDestructsChild("group", constructing: true, background: true)
    }

    /// GRP-017 — control: a synchronous child is `Constructed` at the
    /// rollback, which destructs it at once.
    func testGRP017RollbackDestructsSynchronousChildAtOnce() throws {
        try assertRollbackDestructsChild("group", constructing: false, background: false)
        try assertRollbackDestructsChild("group", constructing: true, background: false)
    }

    /// A background child that another container adopts before its construct
    /// settles is left alone: it keeps its new parent and stays
    /// `Constructed`.
    func testAdoptedBackgroundChildIsNotDestructed() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let dispatcher = ManualDispatcher()
            let container = try makeContainer(
                kind, .add, hub: hub, dispatcher: dispatcher, constructing: false
            )
            try container.vm.construct()
            let child = try ComponentVM.builder()
                .name("child").services(hub: hub, dispatcher: dispatcher)
                .background(true).build()
            let subscription = hub.messages
                .compactMap { $0 as? ConstructionStatusChangedMessage }
                .filter { $0.senderName == "child" && $0.status == .constructing }
                .sink { _ in container.vm.dispose() }
            defer { subscription.cancel() }
            guard case .failure = container.change(child) else {
                XCTFail("\(kind): expected a failed add")
                continue
            }
            let adopter = GroupVM<ComponentVM>(name: "adopter", hub: hub, dispatcher: dispatcher)
            try adopter.addResult(child).get()

            pump(dispatcher)

            XCTAssertEqual(child.status, .constructed, kind)
            XCTAssertTrue(child._ownershipParent?.ownershipOwner === adopter, kind)
        }
    }
}
