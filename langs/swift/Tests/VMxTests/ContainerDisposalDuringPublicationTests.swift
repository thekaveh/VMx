//
// ContainerDisposalDuringPublicationTests.swift — a container whose disposal
// is requested or deferred during a change sends no hub message for it
// (spec/01 §1.4, spec/06 §4/§4.2/§4.3, spec/07 §1, ADR-0190).
//
// Claimed IDs: COMP-049.
//
import Combine
import XCTest
@testable import VMx

/// Records every container `CollectionChangedMessage` delivered on one hub.
private final class DisposalHubRecorder {
    private(set) var messages: [CollectionChangedMessage<ComponentVMBase>] = []

    func record(_ message: CollectionChangedMessage<ComponentVMBase>) {
        messages.append(message)
    }

    func from(_ sender: AnyObject) -> [CollectionChangedMessage<ComponentVMBase>] {
        messages.filter { $0.senderObject === sender }
    }
}

final class ContainerDisposalDuringPublicationTests: XCTestCase {

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
        _ name: String,
        onCurrentChanged: ((ComponentVMBase?) -> Void)? = nil
    ) -> CompositeVM<ComponentVMBase> {
        CompositeVM<ComponentVMBase>(
            name: name,
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE,
            onCurrentChanged: onCurrentChanged
        )
    }

    private func group(_ hub: MessageHub, _ name: String) -> GroupVM<ComponentVMBase> {
        GroupVM<ComponentVMBase>(
            name: name,
            hub: hub,
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    private func record(_ hub: MessageHub) -> DisposalHubRecorder {
        let recorder = DisposalHubRecorder()
        hub.messages
            .compactMap { $0 as? CollectionChangedMessage<ComponentVMBase> }
            .sink { recorder.record($0) }
            .store(in: &cancellables)
        return recorder
    }

    /// Subscribes to `events` and disposes `container` on the first local
    /// event with `action`. Returns the local events seen with that action.
    private func disposeOnLocalEvent(
        _ events: AnyPublisher<CollectionChangedEvent, Never>,
        _ action: CollectionChangedAction,
        dispose: @escaping () -> Void
    ) -> () -> Int {
        var seen = 0
        events
            .sink { event in
                guard event.action == action else { return }
                seen += 1
                if seen == 1 { dispose() }
            }
            .store(in: &cancellables)
        return { seen }
    }

    // ── COMP-049 ─────────────────────────────────────────────────────────

    /// COMP-049 — a transfer whose old composite disposes itself from
    /// `onCurrentChanged(nil)` publishes only the new composite's `Add`.
    func testCOMP049TransferFromSelfDisposingOldCompositePublishesOnlyNewAdd() throws {
        let hub = MessageHub()
        weak var oldRef: CompositeVM<ComponentVMBase>?
        let old = composite(hub, "old") { value in
            if value == nil { oldRef?.dispose() }
        }
        oldRef = old
        let new = composite(hub, "new")
        let x = child(hub, "x")
        try old.addResult(x).get()
        try old.setCurrent(x)
        var localRemoves = 0
        old.collectionChanged
            .sink { if $0.action == .remove { localRemoves += 1 } }
            .store(in: &cancellables)
        let recorder = record(hub)

        try new.addResult(x).get()

        XCTAssertTrue(recorder.from(old).isEmpty, "the disposing old composite sends nothing")
        XCTAssertEqual(recorder.from(new).map(\.action), [.add])
        XCTAssertEqual(recorder.messages.count, 1)
        XCTAssertEqual(localRemoves, 1, "the local Remove is still delivered")
        XCTAssertEqual(old.status, .disposed)
        XCTAssertTrue(new.at(0) === x)
    }

    /// COMP-049 — a composite whose local subscriber disposes it during an
    /// `Add` sends no hub message for that change.
    func testCOMP049CompositeAddDisposedByLocalSubscriberPublishesNothing() throws {
        let hub = MessageHub()
        let p = composite(hub, "p")
        let localAdds = disposeOnLocalEvent(p.collectionChanged, .add) { p.dispose() }
        let recorder = record(hub)

        _ = p.addResult(child(hub, "c"))

        XCTAssertEqual(localAdds(), 1)
        XCTAssertTrue(recorder.from(p).isEmpty)
        XCTAssertEqual(p.status, .disposed)
    }

    /// COMP-049 — a composite whose local subscriber disposes it during a
    /// `Move` sends no hub message for that change.
    func testCOMP049CompositeMoveDisposedByLocalSubscriberPublishesNothing() throws {
        let hub = MessageHub()
        let p = composite(hub, "p")
        try p.addResult(child(hub, "a")).get()
        try p.addResult(child(hub, "b")).get()
        let localMoves = disposeOnLocalEvent(p.collectionChanged, .move) { p.dispose() }
        let recorder = record(hub)

        try p.move(from: 0, to: 1)

        XCTAssertEqual(localMoves(), 1)
        XCTAssertTrue(recorder.from(p).isEmpty)
        XCTAssertEqual(p.status, .disposed)
    }

    /// COMP-049 — a group whose local subscriber disposes it during an `Add`
    /// sends no hub message for that change.
    func testCOMP049GroupAddDisposedByLocalSubscriberPublishesNothing() throws {
        let hub = MessageHub()
        let g = group(hub, "g")
        let localAdds = disposeOnLocalEvent(g.collectionChanged, .add) { g.dispose() }
        let recorder = record(hub)

        _ = g.addResult(child(hub, "c"))

        XCTAssertEqual(localAdds(), 1)
        XCTAssertTrue(recorder.from(g).isEmpty)
        XCTAssertEqual(g.status, .disposed)
    }

    /// COMP-049 — a group whose local subscriber disposes it during a `Move`
    /// sends no hub message for that change.
    func testCOMP049GroupMoveDisposedByLocalSubscriberPublishesNothing() throws {
        let hub = MessageHub()
        let g = group(hub, "g")
        try g.addResult(child(hub, "a")).get()
        try g.addResult(child(hub, "b")).get()
        let localMoves = disposeOnLocalEvent(g.collectionChanged, .move) { g.dispose() }
        let recorder = record(hub)

        try g.move(from: 0, to: 1)

        XCTAssertEqual(localMoves(), 1)
        XCTAssertTrue(recorder.from(g).isEmpty)
        XCTAssertEqual(g.status, .disposed)
    }
}
