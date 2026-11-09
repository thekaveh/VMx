//
// CommitStepWindowTests.swift — the commit step of an auto-construct-on-add
// container walk (spec/02 §2.4, spec/06 §5.1, ADR-0186, #1374).
//
// The commit step writes `.constructed` under the membership gate and
// reserves the publication. An add between that step and the publication
// follows the add-after-Constructed rule. A walk abandoned before the commit
// step commits nothing. Both tests use the test-only late-child probe.
//
// NOTE: `swift test` needs full Xcode (XCTest); CI runs it on macos-latest.
//
import Combine
import XCTest
import Foundation
@testable import VMx

final class CommitStepWindowTests: XCTestCase {
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

    private struct Root {
        let vm: ComponentVMBase
        let add: (ComponentVM) -> Bool
        let records: () -> Int
        let setProbe: (((ComponentVMBase, LateChildStage) -> Void)?) -> Void
    }

    /// A container with auto-construct-on-add and one background child, so
    /// `construct()` leaves it Constructing until `dispatcher` is pumped.
    private func makeRoot(
        _ kind: String, hub: MessageHub, dispatcher: ManualDispatcher
    ) throws -> Root {
        let first = try ComponentVM.builder()
            .name("first").services(hub: hub, dispatcher: dispatcher).background(true).build()
        if kind == "composite" {
            let c = CompositeVM<ComponentVM>(
                name: "root", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE,
                autoConstructOnAdd: true
            )
            try c.addResult(first).get()
            return Root(
                vm: c,
                add: { if case .success = c.addResult($0) { return true } else { return false } },
                records: { c.lateStartRecordCountForTesting },
                setProbe: { c.lateChildProbeForTesting = $0 }
            )
        }
        let g = GroupVM<ComponentVM>(
            name: "root", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE,
            autoConstructOnAdd: true
        )
        try g.addResult(first).get()
        return Root(
            vm: g,
            add: { if case .success = g.addResult($0) { return true } else { return false } },
            records: { g.lateStartRecordCountForTesting },
            setProbe: { g.lateChildProbeForTesting = $0 }
        )
    }

    private func pump(_ dispatcher: ManualDispatcher) {
        for _ in 0..<5 {
            dispatcher.flushBackground()
            dispatcher.flushForeground()
        }
    }

    /// An add after the commit step reads `.constructed` and follows the
    /// add-after-Constructed rule: it registers no start record, and the
    /// container publishes `.constructed` once while the child is still
    /// `.constructing`. Until the publication, the transition stays in
    /// flight: every `can*` predicate is false (LIFE-008).
    func testAddInTheCommitStepWindowFollowsTheAddAfterConstructedRule() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let dispatcher = ManualDispatcher()
            let lateDispatcher = ManualDispatcher()
            let root = try makeRoot(kind, hub: hub, dispatcher: dispatcher)
            let late = try ComponentVM.builder()
                .name("late").services(hub: hub, dispatcher: lateDispatcher).background(true).build()

            let rootLog = Locked<[ConstructionStatus]>([])
            let lateAtRootConstructed = Locked<[ConstructionStatus]>([])
            let subscription = hub.messages
                .compactMap { $0 as? ConstructionStatusChangedMessage }
                .filter { $0.senderName == "root" }
                .sink { message in
                    rootLog.mutate { $0.append(message.status) }
                    if message.status == .constructed {
                        lateAtRootConstructed.mutate { $0.append(late.status) }
                    }
                }
            defer { subscription.cancel() }

            try root.vm.construct()
            XCTAssertEqual(root.vm.status, .constructing, kind)

            let statusAtAdd = Locked<ConstructionStatus?>(nil)
            let predicates = Locked<[Bool]>([])
            let added = Locked<Bool?>(nil)
            let recordsAtAdd = Locked<Int?>(nil)
            root.setProbe { child, stage in
                guard child === root.vm, stage == .sealed, added.value == nil else { return }
                statusAtAdd.value = root.vm.status
                predicates.value = [
                    root.vm.canConstruct(), root.vm.canDestruct(), root.vm.canReconstruct(),
                ]
                added.value = root.add(late)
                recordsAtAdd.value = root.records()
            }
            defer { root.setProbe(nil) }
            pump(dispatcher)

            XCTAssertEqual(statusAtAdd.value, .constructed, "\(kind): the add reads Constructed")
            XCTAssertEqual(predicates.value, [false, false, false], "\(kind): the transition is in flight")
            XCTAssertEqual(added.value, true, kind)
            XCTAssertEqual(recordsAtAdd.value, 0, "\(kind): the add registers no start record")
            XCTAssertEqual(rootLog.value, [.constructing, .constructed], "\(kind): one publication")
            XCTAssertEqual(lateAtRootConstructed.value, [.constructing], kind)

            pump(lateDispatcher)
            XCTAssertEqual(late.status, .constructed, kind)
            XCTAssertEqual(root.vm.status, .constructed, kind)
        }
    }

    /// A walk abandoned after the seal's cancellation check and before the
    /// commit step commits nothing: the commit step checks for the abandon
    /// under the lock that writes the status (ADR-0186 rule 6).
    func testAWalkAbandonedBeforeTheCommitStepCommitsNothing() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let dispatcher = ManualDispatcher()
            let root = try makeRoot(kind, hub: hub, dispatcher: dispatcher)
            let rootLog = Locked<[ConstructionStatus]>([])
            let subscription = hub.messages
                .compactMap { $0 as? ConstructionStatusChangedMessage }
                .filter { $0.senderName == "root" }
                .sink { message in rootLog.mutate { $0.append(message.status) } }
            defer { subscription.cancel() }

            try root.vm.construct()
            XCTAssertEqual(root.vm.status, .constructing, kind)

            let abandoned = Locked(false)
            root.setProbe { child, stage in
                guard child === root.vm, stage == .sealing, !abandoned.value else { return }
                abandoned.value = true
                // What a raising hook does before its rollback.
                root.vm._abandonChildTransition()
            }
            defer { root.setProbe(nil) }
            pump(dispatcher)

            XCTAssertTrue(abandoned.value, "\(kind): the seal ran")
            XCTAssertEqual(root.vm.status, .constructing, "\(kind): the abandoned walk wrote no status")
            XCTAssertFalse(rootLog.value.contains(.constructed), "\(kind): \(rootLog.value)")

            root.vm.dispose()
            XCTAssertEqual(rootLog.value, [.constructing, .disposed], kind)
        }
    }
}
