//
// HubCollectionChangesTests.swift — containers publish their collection changes
// on the message hub (spec/01 §1.4, spec/06 §4, spec/07, ADR-0142).
//
// Claimed IDs: COMP-042, COMP-043, COMP-044, COMP-045, GRP-012, GRP-013.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import Combine
import XCTest
@testable import VMx

private enum HubCollectionTestError: Error {
    case constructFailed
}

/// Records every container `CollectionChangedMessage` delivered on one hub.
private final class HubCollectionRecorder {
    private(set) var messages: [CollectionChangedMessage<ComponentVMBase>] = []

    func record(_ message: CollectionChangedMessage<ComponentVMBase>) {
        messages.append(message)
    }
}

/// One log of a container's local events and hub messages, in delivery order.
private final class DeliveryLog {
    private(set) var entries: [String] = []

    func append(_ entry: String) {
        entries.append(entry)
    }
}

final class HubCollectionChangesTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    private func child(_ hub: MessageHub, _ name: String) -> ComponentVM {
        ComponentVM(name: name, hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
    }

    private func composite(
        _ hub: MessageHub,
        _ name: String = "composite"
    ) -> CompositeVM<ComponentVMBase> {
        CompositeVM<ComponentVMBase>(
            name: name,
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    private func group(
        _ hub: MessageHub,
        _ name: String = "group"
    ) -> GroupVM<ComponentVMBase> {
        GroupVM<ComponentVMBase>(
            name: name,
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    private func record(_ hub: MessageHub) -> HubCollectionRecorder {
        let recorder = HubCollectionRecorder()
        hub.messages
            .compactMap { $0 as? CollectionChangedMessage<ComponentVMBase> }
            .sink { recorder.record($0) }
            .store(in: &cancellables)
        return recorder
    }

    private func interleave(
        _ local: AnyPublisher<CollectionChangedEvent, Never>,
        from container: ComponentVMBase,
        on hub: MessageHub
    ) -> DeliveryLog {
        let log = DeliveryLog()
        local
            .sink { event in
                log.append("local:\(event.action):\(event.oldIndex):\(event.newIndex)")
            }
            .store(in: &cancellables)
        hub.messages
            .compactMap { $0 as? CollectionChangedMessage<ComponentVMBase> }
            .filter { $0.senderObject === container }
            .sink { message in
                log.append("hub:\(message.action):\(message.oldIndex):\(message.newIndex)")
            }
            .store(in: &cancellables)
        return log
    }

    /// Each local entry is immediately followed by its matching hub entry.
    private func assertHubFollowsEachLocalEvent(_ entries: [String], localEvents: Int) {
        XCTAssertEqual(entries.count, localEvents * 2)
        for index in stride(from: 0, to: entries.count - 1, by: 2) {
            let local = entries[index]
            XCTAssertTrue(local.hasPrefix("local:"), "entry \(index) must be local: \(local)")
            XCTAssertEqual(entries[index + 1], "hub:" + String(local.dropFirst("local:".count)))
        }
    }

    // ── COMP-042 ─────────────────────────────────────────────────────────

    /// COMP-042 — each local composite event is followed by exactly one hub
    /// message sent by the composite, with the same action, positions, and
    /// items; replacement keeps the local Remove + Add decomposition.
    func testCOMP042PublishesOneHubMessageAfterEachLocalEvent() throws {
        let hub = MessageHub()
        let parent = composite(hub)
        let a = child(hub, "a")
        let b = child(hub, "b")
        let c = child(hub, "c")
        let d = child(hub, "d")
        let log = interleave(parent.collectionChanged, from: parent, on: hub)
        let recorder = record(hub)

        parent.add(a)
        parent.insert(b, at: 0)
        try parent.move(from: 0, to: 1)
        parent.replace(at: 0, with: c)
        parent.removeAt(1)
        XCTAssertTrue(parent.remove(c))
        parent.add(d)
        parent.clear()

        assertHubFollowsEachLocalEvent(log.entries, localEvents: 9)
        let messages = recorder.messages
        XCTAssertEqual(messages.count, 9)
        XCTAssertTrue(messages.allSatisfy { $0.senderObject === parent })
        XCTAssertTrue(messages.allSatisfy { $0.senderName == parent.name })
        XCTAssertEqual(
            messages.map(\.action),
            [.add, .add, .move, .remove, .add, .remove, .remove, .add, .reset]
        )
        XCTAssertEqual(messages.map(\.index), [0, 0, 1, 0, 0, 1, 0, 0, -1])
        XCTAssertEqual(messages.map(\.oldIndex), [-1, -1, 0, 0, -1, 1, 0, -1, -1])
        XCTAssertEqual(messages.map(\.newIndex), [0, 0, 1, -1, 0, -1, -1, 0, -1])
        guard messages.count == 9 else { return }
        XCTAssertEqual(messages[0].newItems.count, 1)
        XCTAssertTrue(messages[0].newItems.first === a)
        XCTAssertTrue(messages[2].newItems.first === b)
        XCTAssertTrue(messages[2].oldItems.first === b)
        XCTAssertTrue(messages[3].oldItems.first === a)
        XCTAssertTrue(messages[4].newItems.first === c)
        XCTAssertTrue(messages[5].oldItems.first === b)
        XCTAssertTrue(messages[8].newItems.isEmpty)
        XCTAssertTrue(messages[8].oldItems.isEmpty)
    }

    /// COMP-042 — the local event is delivered first, and both channels
    /// observe the committed membership.
    func testCOMP042BothChannelsObserveCommittedMembership() {
        let hub = MessageHub()
        let parent = composite(hub)
        let a = child(hub, "a")
        var order: [String] = []
        var localSawMember: [Bool] = []
        var hubSawMember: [Bool] = []
        parent.collectionChanged
            .sink { _ in
                order.append("local")
                localSawMember.append(parent.snapshot().contains { $0 === a })
            }
            .store(in: &cancellables)
        hub.messages
            .compactMap { $0 as? CollectionChangedMessage<ComponentVMBase> }
            .sink { _ in
                order.append("hub")
                hubSawMember.append(parent.snapshot().contains { $0 === a })
            }
            .store(in: &cancellables)

        parent.add(a)
        XCTAssertTrue(parent.remove(a))

        XCTAssertEqual(order, ["local", "hub", "local", "hub"])
        XCTAssertEqual(localSawMember, [true, false])
        XCTAssertEqual(hubSawMember, [true, false])
    }

    // ── COMP-043 ─────────────────────────────────────────────────────────

    /// COMP-043 — nothing is published while any batch scope (including a
    /// nested one) is active; one hub Reset follows the local Reset when the
    /// outermost scope completes.
    func testCOMP043BatchPublishesOneResetAfterLocalReset() throws {
        let hub = MessageHub()
        let parent = composite(hub)
        let log = interleave(parent.collectionChanged, from: parent, on: hub)
        let recorder = record(hub)

        let outer = parent.batchUpdate()
        parent.add(child(hub, "a"))
        let inner = parent.batchUpdate()
        parent.add(child(hub, "b"))
        try parent.move(from: 0, to: 1)
        inner.dispose()
        XCTAssertEqual(log.entries, [])
        XCTAssertTrue(recorder.messages.isEmpty)
        outer.dispose()

        XCTAssertEqual(log.entries, ["local:reset:-1:-1", "hub:reset:-1:-1"])
        XCTAssertEqual(recorder.messages.count, 1)
        XCTAssertTrue(recorder.messages.first?.senderObject === parent)
        XCTAssertEqual(recorder.messages.first?.index, -1)
    }

    /// COMP-043 — an empty batch, or one holding only a same-index move,
    /// publishes nothing.
    func testCOMP043EmptyOrSameIndexBatchPublishesNothing() throws {
        let hub = MessageHub()
        let parent = composite(hub)
        parent.add(child(hub, "a"))
        let recorder = record(hub)

        parent.batchUpdate().dispose()
        let batch = parent.batchUpdate()
        try parent.move(from: 0, to: 0)
        batch.dispose()

        XCTAssertTrue(recorder.messages.isEmpty)
    }

    // ── COMP-044 ─────────────────────────────────────────────────────────

    /// COMP-044 — a transfer publishes the old container's Remove before the
    /// new container's Add.
    func testCOMP044TransferPublishesOldRemoveBeforeNewAdd() throws {
        let hub = MessageHub()
        let oldParent = composite(hub, "old")
        let newParent = group(hub, "new")
        let moved = child(hub, "moved")
        oldParent.add(moved)
        let recorder = record(hub)

        try newParent.addResult(moved).get()

        let messages = recorder.messages
        XCTAssertEqual(messages.count, 2)
        XCTAssertTrue(messages.first?.senderObject === oldParent)
        XCTAssertEqual(messages.first?.action, .remove)
        XCTAssertTrue(messages.first?.oldItems.first === moved)
        XCTAssertTrue(messages.last?.senderObject === newParent)
        XCTAssertEqual(messages.last?.action, .add)
        XCTAssertTrue(messages.last?.newItems.first === moved)
    }

    /// COMP-044 — a rejected duplicate add, a cycle, an invalid index, a
    /// transfer rolled back by a failing construct hook, and a same-index move
    /// each publish no CollectionChangedMessage.
    func testCOMP044FailedMutationsPublishNothing() throws {
        let hub = MessageHub()
        let parent = composite(hub, "parent")
        let outer = composite(hub, "outer")
        let a = child(hub, "a")
        parent.add(a)
        outer.add(parent)
        let source = composite(hub, "source")
        let failing = ComponentVM(
            name: "failing",
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            onConstruct: { throw HubCollectionTestError.constructFailed }
        )
        source.add(failing)
        let destination = CompositeVM<ComponentVMBase>(
            name: "destination",
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            autoConstructOnAdd: true
        )
        try destination.construct()
        let recorder = record(hub)

        if case .failure(.duplicate) = parent.addResult(a) {
            // Expected.
        } else {
            XCTFail("re-adding a member must be rejected as a duplicate")
        }
        if case .failure(.cycle) = parent.addResult(outer) {
            // Expected.
        } else {
            XCTFail("adding an ancestor beneath its descendant must report cycle")
        }
        if case .failure(.attachmentFailed) = parent.insertResult(child(hub, "late"), at: 99) {
            // Expected.
        } else {
            XCTFail("an out-of-range insert must be rejected")
        }
        if case .failure(.attachmentFailed) = destination.addResult(failing) {
            // Expected.
        } else {
            XCTFail("a failing construct hook must roll the transfer back")
        }
        try parent.move(from: 0, to: 0)

        XCTAssertTrue(source.snapshot().contains { $0 === failing })
        XCTAssertEqual(destination.count, 0)
        XCTAssertEqual(parent.count, 1)
        XCTAssertTrue(recorder.messages.isEmpty)
    }

    // ── COMP-045 ─────────────────────────────────────────────────────────

    /// COMP-045 — inside a hub transaction the composite's messages are
    /// deferred, then delivered in mutation order when it completes.
    func testCOMP045HubTransactionDefersMessagesInOrder() throws {
        let hub = MessageHub()
        let parent = composite(hub)
        let a = child(hub, "a")
        let b = child(hub, "b")
        let recorder = record(hub)
        var deliveredInsideTransaction: [Int] = []

        try hub.batch {
            parent.add(a)
            parent.add(b)
            deliveredInsideTransaction.append(recorder.messages.count)
        }

        XCTAssertEqual(deliveredInsideTransaction, [0])
        XCTAssertEqual(recorder.messages.map(\.action), [.add, .add])
        XCTAssertEqual(recorder.messages.map(\.newIndex), [0, 1])
        XCTAssertTrue(recorder.messages.allSatisfy { $0.senderObject === parent })
    }

    /// COMP-045 — once the composite is disposed, no further
    /// CollectionChangedMessage from it reaches the hub, including a pending
    /// batch's Reset and a mutation the disposed composite still performs.
    func testCOMP045DisposedCompositePublishesNothing() throws {
        let hub = MessageHub()
        let parent = composite(hub)
        parent.add(child(hub, "a"))
        parent.add(child(hub, "b"))
        let pending = parent.batchUpdate()
        try parent.move(from: 0, to: 1)
        let recorder = record(hub)

        parent.dispose()
        pending.dispose()
        if case .success = parent.addResult(child(hub, "late")) {
            XCTFail("a disposed composite must reject admission")
        }
        try? parent.move(from: 0, to: 1)

        XCTAssertTrue(recorder.messages.filter { $0.senderObject === parent }.isEmpty)
    }

    /// COMP-045 — mutating through a forwarding composite wrapper publishes
    /// each change once, sent by the wrapped composite.
    func testCOMP045ForwardingWrapperPublishesEachChangeOnce() throws {
        let hub = MessageHub()
        let parent = composite(hub)
        let wrapper = ForwardingCompositeVM<ComponentVMBase>(parent)
        let a = child(hub, "a")
        let recorder = record(hub)

        wrapper.add(a)
        let batch = wrapper.batchUpdate()
        wrapper.add(child(hub, "b"))
        batch.dispose()
        XCTAssertTrue(wrapper.remove(a))

        XCTAssertEqual(recorder.messages.map(\.action), [.add, .reset, .remove])
        XCTAssertTrue(recorder.messages.allSatisfy { $0.senderObject === parent })
        XCTAssertFalse(recorder.messages.contains { $0.senderObject === wrapper })
    }

    // ── GRP-012 ──────────────────────────────────────────────────────────

    /// GRP-012 — each local group event is followed by exactly one hub message
    /// sent by the group, with the same action and positions; a mutation that
    /// raises no local event publishes nothing.
    func testGRP012PublishesOneHubMessageAfterEachLocalEvent() throws {
        let hub = MessageHub()
        let peers = group(hub)
        let a = child(hub, "a")
        let b = child(hub, "b")
        let c = child(hub, "c")
        let stranger = child(hub, "stranger")
        let log = interleave(peers.collectionChanged, from: peers, on: hub)
        let recorder = record(hub)

        peers.add(a)
        peers.insert(b, at: 0)
        try peers.move(from: 0, to: 1)
        try peers.move(from: 1, to: 1)
        peers.replace(at: 0, with: c)
        XCTAssertTrue(peers.remove(b))
        XCTAssertFalse(peers.remove(stranger))
        peers.clear()

        assertHubFollowsEachLocalEvent(log.entries, localEvents: 7)
        XCTAssertEqual(recorder.messages.count, 7)
        XCTAssertTrue(recorder.messages.allSatisfy { $0.senderObject === peers })
        XCTAssertEqual(
            recorder.messages.map(\.action),
            [.add, .add, .move, .remove, .add, .remove, .reset]
        )
    }

    /// GRP-012 — once the group is disposed, no further message from it
    /// reaches the hub.
    func testGRP012DisposedGroupPublishesNothing() throws {
        let hub = MessageHub()
        let peers = group(hub)
        let a = child(hub, "a")
        peers.add(a)
        peers.add(child(hub, "b"))
        let recorder = record(hub)

        peers.dispose()
        if case .success = peers.addResult(child(hub, "late")) {
            XCTFail("a disposed group must reject admission")
        }
        try? peers.move(from: 0, to: 1)
        _ = peers.remove(a)
        peers.clear()

        XCTAssertTrue(recorder.messages.filter { $0.senderObject === peers }.isEmpty)
    }

    // ── GRP-013 ──────────────────────────────────────────────────────────

    /// GRP-013 — nothing is published inside a (nested) batch, one hub Reset
    /// follows the local Reset on outermost completion, and an empty batch
    /// publishes nothing.
    func testGRP013BatchPublishesOneResetAndEmptyBatchNothing() {
        let hub = MessageHub()
        let peers = group(hub)
        let log = interleave(peers.collectionChanged, from: peers, on: hub)

        peers.batchUpdate().dispose()
        XCTAssertEqual(log.entries, [])
        let outer = peers.batchUpdate()
        peers.add(child(hub, "a"))
        let inner = peers.batchUpdate()
        peers.add(child(hub, "b"))
        inner.dispose()
        XCTAssertEqual(log.entries, [])
        outer.dispose()

        XCTAssertEqual(log.entries, ["local:reset:-1:-1", "hub:reset:-1:-1"])
    }
}
