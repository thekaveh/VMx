//
// TreeSelection conformance and unit tests.
//
// Claimed IDs: HIER-033..HIER-040 (spec/18 §10, ADR-0164). The
// `TreeSelectionUnitTests` class below adds API checks that claim no ID.
//
import Combine
import XCTest
@testable import VMx

private final class SelectionNode: HierarchicalVM<String, SelectionNode> {}

/// Counts children-factory invocations per node name.
private final class FactoryCounter {
    var calls: [String: Int] = [:]
}

private func makeNode(
    _ name: String,
    hub: MessageHubProtocol,
    counter: FactoryCounter,
    children: @escaping () -> [SelectionNode] = { [] }
) -> SelectionNode {
    SelectionNode(
        model: name,
        childrenFactory: { _ in
            counter.calls[name, default: 0] += 1
            return children()
        },
        hub: hub,
        dispatcher: ImmediateDispatcher.INSTANCE,
        name: name
    )
}

/// `root → [A → [AA], B]`. Root's and A's children are materialized; AA's
/// and B's are not.
private struct SelectionTree {
    let hub: MessageHubProtocol
    let counter: FactoryCounter
    let root: SelectionNode
    let a: SelectionNode
    let b: SelectionNode
    let aa: SelectionNode
}

private func makeTree(
    hub: MessageHubProtocol = MessageHub(),
    aHub: MessageHubProtocol? = nil,
    bHub: MessageHubProtocol? = nil
) -> SelectionTree {
    let counter = FactoryCounter()
    let aa = makeNode("AA", hub: hub, counter: counter)
    let a = makeNode("A", hub: aHub ?? hub, counter: counter) { [aa] }
    let b = makeNode("B", hub: bHub ?? hub, counter: counter)
    let root = makeNode("root", hub: hub, counter: counter) { [a, b] }
    _ = root.children
    _ = a.children
    return SelectionTree(hub: hub, counter: counter, root: root, a: a, b: b, aa: aa)
}

private func assertSucceeds(
    _ result: Result<Void, HierarchyError>,
    file: StaticString = #filePath,
    line: UInt = #line
) {
    if case .failure(let error) = result {
        XCTFail("structural change failed: \(error)", file: file, line: line)
    }
}

/// Records `currentChanged` emissions by node name (`"nil"` for no selection).
private final class SelectionRecorder {
    private(set) var values: [String] = []
    private(set) var completed = false
    private var subscription: AnyCancellable?

    init(_ selection: TreeSelection<String, SelectionNode>) {
        subscription = selection.currentChanged.sink(
            receiveCompletion: { [weak self] _ in self?.completed = true },
            receiveValue: { [weak self] node in self?.values.append(node?.model ?? "nil") }
        )
    }
}

/// Wraps a `MessageHub` and counts live `messages` subscriptions.
private final class ProbeHub: MessageHubProtocol {
    private let inner = MessageHub()
    private(set) var activeSubscriptions = 0

    var messages: AnyPublisher<any Message, Never> {
        inner.messages
            .handleEvents(
                receiveSubscription: { [weak self] _ in self?.activeSubscriptions += 1 },
                receiveCancel: { [weak self] in self?.activeSubscriptions -= 1 }
            )
            .eraseToAnyPublisher()
    }

    func send(_ message: any Message) {
        inner.send(message)
    }
}

final class HierarchicalTreeSelectionTests: XCTestCase {

    /// HIER-033 — a subscriber that selects again while it receives a value
    /// does not reorder the changes for a later subscriber.
    func testHier033ReentrantSelectReachesEverySubscriberInOrder() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        let reselect = selection.currentChanged.sink { [tree] node in
            if node === tree.aa { try? selection.select(tree.a) }
        }
        let recorder = SelectionRecorder(selection)

        try selection.select(tree.aa)

        XCTAssertEqual(recorder.values, ["AA", "A"])
        XCTAssertTrue(selection.current === tree.a)
        reselect.cancel()
    }

    /// HIER-033 — `TreeSelection` selects a member and publishes each change
    /// once; a repeated select and a repeated clear publish nothing.
    func testHier033SelectsMemberAndPublishesEachChangeOnce() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)

        XCTAssertTrue(selection.canSelect(tree.root))
        XCTAssertTrue(selection.canSelect(tree.a))
        XCTAssertTrue(selection.canSelect(tree.aa))
        XCTAssertNil(selection.current)

        try selection.select(tree.aa)
        XCTAssertTrue(selection.current === tree.aa)
        try selection.select(tree.aa)
        XCTAssertTrue(selection.current === tree.aa)

        selection.clear()
        XCTAssertNil(selection.current)
        selection.clear()
        XCTAssertNil(selection.current)

        XCTAssertEqual(recorder.values, ["AA", "nil"])
    }

    /// HIER-034 — `TreeSelection` rejects a detached node, a node of another
    /// tree and a disposed member with `TreeSelectionError.notInTree`; `current`
    /// and `currentChanged` are unchanged and no children factory runs.
    func testHier034RejectsNodeOutsideMaterializedTree() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        try selection.select(tree.a)
        let recorder = SelectionRecorder(selection)

        let detached = makeNode("detached", hub: tree.hub, counter: tree.counter)
        let otherChild = makeNode("otherChild", hub: tree.hub, counter: tree.counter)
        let otherRoot = makeNode("otherRoot", hub: tree.hub, counter: tree.counter) { [otherChild] }
        _ = otherRoot.children
        tree.b.dispose()
        let callsBefore = tree.counter.calls

        for node in [detached, otherChild, otherRoot, tree.b] {
            XCTAssertFalse(selection.canSelect(node), "\(node.model) must not be selectable")
            XCTAssertThrowsError(try selection.select(node)) { error in
                XCTAssertEqual(error as? TreeSelectionError, .notInTree)
            }
            XCTAssertTrue(selection.current === tree.a)
        }

        XCTAssertEqual(recorder.values, [])
        XCTAssertEqual(tree.counter.calls, callsBefore)
        XCTAssertNil(tree.counter.calls["detached"])
        XCTAssertNil(tree.counter.calls["otherChild"])
        XCTAssertNil(tree.counter.calls["B"])
    }

    /// HIER-035 — removing the current node or an ancestor clears the
    /// selection and publishes `nil` once.
    func testHier035RemovingCurrentOrAncestorClearsSelection() throws {
        let ancestorCase = makeTree()
        let first = TreeSelection(root: ancestorCase.root)
        let firstRecorder = SelectionRecorder(first)
        try first.select(ancestorCase.aa)

        ancestorCase.root.removeChild(ancestorCase.a)

        XCTAssertNil(first.current)
        XCTAssertEqual(firstRecorder.values, ["AA", "nil"])

        let selfCase = makeTree()
        let second = TreeSelection(root: selfCase.root)
        let secondRecorder = SelectionRecorder(second)
        try second.select(selfCase.aa)

        selfCase.a.removeChild(selfCase.aa)

        XCTAssertNil(second.current)
        XCTAssertEqual(secondRecorder.values, ["AA", "nil"])
    }

    /// HIER-036 — a move inside the tree keeps the selection; a transfer to
    /// a second tree on a different hub clears it once.
    func testHier036TransferOutClearsMoveInsideKeeps() throws {
        let tree = makeTree()
        let otherHub = MessageHub()
        let otherRoot = makeNode("otherRoot", hub: otherHub, counter: tree.counter)
        let selection = TreeSelection(root: tree.root)
        try selection.select(tree.aa)
        let recorder = SelectionRecorder(selection)

        assertSucceeds(tree.b.addChild(tree.a))
        XCTAssertTrue(tree.a.parent === tree.b)
        XCTAssertTrue(selection.current === tree.aa)
        XCTAssertEqual(recorder.values, [])

        assertSucceeds(otherRoot.addChild(tree.a))
        XCTAssertTrue(tree.a.parent === otherRoot)
        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, ["nil"])
    }

    /// HIER-037 — `invalidateChildren` on an ancestor clears the selection;
    /// the dropped node stays live with a nil parent and is not selectable.
    func testHier037InvalidatingAncestorClearsSelection() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)
        try selection.select(tree.aa)

        tree.a.invalidateChildren()

        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, ["AA", "nil"])
        XCTAssertNil(tree.aa.parent)
        XCTAssertNotEqual(tree.aa.status, .disposed)
        XCTAssertFalse(selection.canSelect(tree.aa))
    }

    /// HIER-038 — disposing the current node or an ancestor clears the
    /// selection; a disposed ancestor stays in the tree.
    func testHier038DisposingCurrentOrAncestorClearsSelection() throws {
        let ancestorCase = makeTree()
        let first = TreeSelection(root: ancestorCase.root)
        let firstRecorder = SelectionRecorder(first)
        try first.select(ancestorCase.aa)

        ancestorCase.a.dispose()

        XCTAssertNil(first.current)
        XCTAssertEqual(firstRecorder.values, ["AA", "nil"])
        XCTAssertFalse(first.canSelect(ancestorCase.aa))
        XCTAssertTrue(ancestorCase.a.parent === ancestorCase.root)
        XCTAssertTrue(ancestorCase.aa.parent === ancestorCase.a)

        let selfCase = makeTree()
        let second = TreeSelection(root: selfCase.root)
        let secondRecorder = SelectionRecorder(second)
        try second.select(selfCase.aa)

        selfCase.aa.dispose()

        XCTAssertNil(second.current)
        XCTAssertEqual(secondRecorder.values, ["AA", "nil"])
        XCTAssertFalse(second.canSelect(selfCase.aa))
    }

    /// HIER-039 — selection does not navigate: no children factory runs, no
    /// node's status, parent or `isCurrent` changes, and no hub message is
    /// published.
    func testHier039SelectionDoesNotNavigate() throws {
        let hub = MessageHub()
        let counter = FactoryCounter()
        let aa = makeNode("AA", hub: hub, counter: counter)
        let a = makeNode("A", hub: hub, counter: counter) { [aa] }
        let b = makeNode("B", hub: hub, counter: counter)
        let root = makeNode("root", hub: hub, counter: counter) { [a, b] }
        _ = root.children
        var received: [any Message] = []
        let hubSubscription = hub.messages.sink { received.append($0) }
        defer { hubSubscription.cancel() }
        let selection = TreeSelection(root: root)
        let nodes = [root, a, b]
        let statuses = nodes.map(\.status)
        let parents = nodes.map(\.parent)
        let currents = nodes.map(\.isCurrent)

        try selection.select(a)

        XCTAssertTrue(selection.current === a)
        XCTAssertNil(counter.calls["A"])
        XCTAssertEqual(counter.calls["root"], 1)
        XCTAssertEqual(nodes.map(\.status), statuses)
        XCTAssertTrue(zip(nodes.map(\.parent), parents).allSatisfy { $0 === $1 })
        XCTAssertEqual(nodes.map(\.isCurrent), currents)
        XCTAssertNil(aa.parent)
        XCTAssertTrue(received.isEmpty)
    }

    /// HIER-040 — a disposed `TreeSelection` is inert: the stream completes
    /// without a value, nothing is selectable, later calls and tree changes do
    /// nothing, and a second dispose does nothing.
    func testHier040DisposedSelectionIsInert() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        try selection.select(tree.aa)
        let recorder = SelectionRecorder(selection)

        selection.dispose()

        XCTAssertTrue(recorder.completed)
        XCTAssertEqual(recorder.values, [])
        XCTAssertNil(selection.current)
        for node in [tree.root, tree.a, tree.b, tree.aa] {
            XCTAssertFalse(selection.canSelect(node))
        }

        let detached = makeNode("detached", hub: tree.hub, counter: tree.counter)
        XCTAssertNoThrow(try selection.select(tree.aa))
        XCTAssertNoThrow(try selection.select(detached))
        selection.clear()
        tree.a.removeChild(tree.aa)
        tree.root.removeChild(tree.a)
        tree.b.dispose()
        XCTAssertNil(selection.current)

        selection.dispose()
        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, [])
    }
}

/// Owner VM forwarding `currentChanged` to its own property notification
/// (spec/14 rule 6).
private final class TreeScreenVM: ComponentVMBase {
    let selection: TreeSelection<String, SelectionNode>

    init(root: SelectionNode, hub: MessageHubProtocol) {
        selection = TreeSelection(root: root)
        super.init(name: "TreeScreenVM", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
        own(selection.currentChanged.sink { [weak self] _ in
            self?._notifyPropertyChanged("selectedNode")
        })
        own { [selection] in selection.dispose() }
    }

    var selectedNode: SelectionNode? { selection.current }
}

final class TreeSelectionUnitTests: XCTestCase {
    /// The root is held weakly: once it is deallocated nothing is selectable,
    /// but `current` keeps its value until `clear()` (ADR-0164 §2.4).
    func testDeallocatedRootLeavesCurrentButBlocksSelection() throws {
        let counter = FactoryCounter()
        let hub = MessageHub()
        let child = makeNode("child", hub: hub, counter: counter)
        var selection: TreeSelection<String, SelectionNode>?
        weak var weakRoot: SelectionNode?
        do {
            let root = makeNode("root", hub: hub, counter: counter, children: { [child] })
            _ = root.children
            weakRoot = root
            selection = TreeSelection(root: root)
            try selection?.select(child)
        }
        XCTAssertNil(weakRoot)
        XCTAssertTrue(selection?.current === child)
        XCTAssertFalse(selection?.canSelect(child) ?? true)
        selection?.clear()
        XCTAssertNil(selection?.current)
    }


    func testSelectsTheRoot() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)

        try selection.select(tree.root)
        tree.root.removeChild(tree.a)

        XCTAssertTrue(selection.current === tree.root)
        XCTAssertEqual(recorder.values, ["root"])
    }

    func testNonStructuralRootLimitsSelectionToItsSubtree() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.a)

        XCTAssertTrue(selection.canSelect(tree.a))
        XCTAssertTrue(selection.canSelect(tree.aa))
        XCTAssertFalse(selection.canSelect(tree.root))
        XCTAssertFalse(selection.canSelect(tree.b))
        XCTAssertThrowsError(try selection.select(tree.root))
        try selection.select(tree.aa)
        XCTAssertTrue(selection.current === tree.aa)
    }

    func testNilIsNeverSelectable() {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        XCTAssertFalse(selection.canSelect(nil))
    }

    /// An intra-tree move re-watches the new path: an event published only by
    /// the new ancestor, on a hub the old path never used, clears.
    func testMoveInsideTreeRewatchesNewPath() throws {
        let bHub = MessageHub()
        let tree = makeTree(bHub: bHub)
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)
        try selection.select(tree.aa)

        assertSucceeds(tree.b.addChild(tree.a))
        XCTAssertTrue(selection.current === tree.aa)
        tree.b.invalidateChildren()

        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, ["AA", "nil"])
    }

    func testMoveInsideTreeThenRemovalFromNewLocationClears() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)
        try selection.select(tree.aa)

        assertSucceeds(tree.b.addChild(tree.a))
        tree.root.removeChild(tree.b)

        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, ["AA", "nil"])
    }

    func testAncestorOnAnotherHubInvalidatedClears() throws {
        let tree = makeTree(aHub: MessageHub())
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)
        try selection.select(tree.aa)

        tree.a.invalidateChildren()

        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, ["AA", "nil"])
    }

    func testAncestorOnAnotherHubRemovedClears() throws {
        let tree = makeTree(aHub: MessageHub())
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)
        try selection.select(tree.aa)

        tree.root.removeChild(tree.a)

        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, ["AA", "nil"])
    }

    func testAncestorOnAnotherHubDisposedClears() throws {
        let tree = makeTree(aHub: MessageHub())
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)
        try selection.select(tree.aa)

        tree.a.dispose()

        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, ["AA", "nil"])
    }

    func testInvalidateSubtreeOnRootClears() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)
        try selection.select(tree.aa)

        tree.root.invalidateSubtree()

        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, ["AA", "nil"])
    }

    func testRootDisposalClears() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)
        try selection.select(tree.aa)

        tree.root.dispose()

        XCTAssertNil(selection.current)
        XCTAssertEqual(recorder.values, ["AA", "nil"])
        XCTAssertFalse(selection.canSelect(tree.root))
    }

    func testUnrelatedTreeChangeKeepsSelection() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        let recorder = SelectionRecorder(selection)
        try selection.select(tree.aa)

        tree.root.removeChild(tree.b)
        tree.b.dispose()

        XCTAssertTrue(selection.current === tree.aa)
        XCTAssertEqual(recorder.values, ["AA"])
    }

    func testReentrantSelectFromSubscriber() throws {
        let tree = makeTree()
        let selection = TreeSelection(root: tree.root)
        var values: [String] = []
        let subscription = selection.currentChanged.sink { node in
            values.append(node?.model ?? "nil")
            if node === tree.aa {
                XCTAssertTrue(selection.current === tree.aa)
                try? selection.select(tree.b)
            }
        }
        defer { subscription.cancel() }

        try selection.select(tree.aa)

        XCTAssertTrue(selection.current === tree.b)
        XCTAssertEqual(values, ["AA", "B"])

        // The watch follows the re-entrant selection: removing B clears.
        tree.root.removeChild(tree.b)
        XCTAssertNil(selection.current)
        XCTAssertEqual(values, ["AA", "B", "nil"])
    }

    func testOwnerForwardsCurrentChangedToPropertyNotification() throws {
        let tree = makeTree()
        let owner = TreeScreenVM(root: tree.root, hub: tree.hub)
        var localNames: [String] = []
        var hubNames: [String] = []
        let local = owner.propertyChanged.sink { localNames.append($0) }
        let hubSubscription = tree.hub.messages.sink { message in
            if let changed = message as? PropertyChangedMessage, changed.senderObject === owner {
                hubNames.append(changed.propertyName)
            }
        }
        defer {
            local.cancel()
            hubSubscription.cancel()
        }

        try owner.selection.select(tree.aa)
        XCTAssertTrue(owner.selectedNode === tree.aa)
        tree.root.removeChild(tree.a)
        XCTAssertNil(owner.selectedNode)

        XCTAssertEqual(localNames, ["selectedNode", "selectedNode"])
        XCTAssertEqual(hubNames, ["selectedNode", "selectedNode"])

        owner.dispose()
        XCTAssertFalse(owner.selection.canSelect(tree.root))
    }

    func testWatchUsesOneSubscriptionPerHubAndDisposeReleasesIt() throws {
        let hub = ProbeHub()
        let otherHub = ProbeHub()
        let tree = makeTree(hub: hub, aHub: otherHub)
        let baseline = hub.activeSubscriptions
        let otherBaseline = otherHub.activeSubscriptions
        let selection = TreeSelection(root: tree.root)

        try selection.select(tree.aa)
        XCTAssertEqual(hub.activeSubscriptions, baseline + 1)
        XCTAssertEqual(otherHub.activeSubscriptions, otherBaseline + 1)

        try selection.select(tree.b)
        XCTAssertEqual(hub.activeSubscriptions, baseline + 1)
        XCTAssertEqual(otherHub.activeSubscriptions, otherBaseline)

        selection.clear()
        XCTAssertEqual(hub.activeSubscriptions, baseline)

        try selection.select(tree.aa)
        selection.dispose()
        XCTAssertEqual(hub.activeSubscriptions, baseline)
        XCTAssertEqual(otherHub.activeSubscriptions, otherBaseline)
    }

    func testHelperDoesNotRetainRoot() {
        weak var weakRoot: SelectionNode?
        var selection: TreeSelection<String, SelectionNode>?
        do {
            let root = makeNode("root", hub: MessageHub(), counter: FactoryCounter())
            weakRoot = root
            selection = TreeSelection(root: root)
            XCTAssertTrue(selection?.canSelect(root) ?? false)
        }
        XCTAssertNil(weakRoot)
        XCTAssertNotNil(selection)
    }
}
