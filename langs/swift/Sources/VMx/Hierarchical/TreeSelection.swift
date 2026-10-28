//
// TreeSelection<TModel, TVM> — opt-in "one current node per tree" helper.
//
// A tree node cannot be the current item of a container: its inherited
// `select()` delegates to the container back-reference, which tree nodes never
// set. A consumer that needs one current node per tree composes this helper on
// the tree's root (ADR-0164). The helper adds no `HierarchicalVM` member and
// implements no capability on the nodes.
//
// Leave-tree detection (spec/18 §10.2): while a node is current, the helper
// subscribes to the hub of every node on the path current..root (one
// subscription per distinct hub) and re-checks membership on any message whose
// sender is a node on that path. Every leave-tree event is published by such a
// node on its own hub:
//   • `removeChild` / a transfer out — the moved node publishes
//     `PropertyChangedMessage("parent")` on its own hub (spec/18 §7, HIER-010),
//     even when the new parent lives in another tree on another hub;
//   • `invalidateChildren` — the invalidated node publishes
//     `PropertyChangedMessage("children")` (spec/18 §5);
//   • disposal — the disposed node publishes
//     `ConstructionStatusChangedMessage(.disposed)` (spec/02).
//
// See spec/18-hierarchical-vm.md §10 and ADR-0164.
//
import Combine

/// Errors from `TreeSelection`.
///
/// - `notInTree`: `select(_:)` received a node that `canSelect(_:)` rejects —
///   the node is not in the root's materialized tree, or the node or one of
///   its ancestors is disposed (HIER-034). The Swift expression of the
///   invalid-operation error the other flavors raise (ADR-0053).
public enum TreeSelectionError: Error, Equatable {
    case notInTree
}

/// Tracks one current node in the materialized tree under a root node
/// (spec/18 §10, ADR-0164).
///
/// - `TModel`: the per-node domain model of the tree.
/// - `TVM`: the concrete node type, as in `HierarchicalVM<TModel, TVM>`. Bound
///   to `AnyObject` for the same reason `HierarchicalVM` is (ADR-0061 §2.1).
///
/// A node is selectable when walking its `parent` links reaches the root (the
/// root itself qualifies) and no node on that path is disposed. The helper reads
/// only `parent`, `status` and `hub`: it never reads `children`, `isLeaf`,
/// `isFirst` or `isLast`, so it never invokes a children factory.
///
/// `current` becomes `nil` when the current node leaves the tree: it or an
/// ancestor is removed, transferred to a parent outside the tree, dropped by an
/// ancestor's `invalidateChildren()`, or disposed. A move inside the tree keeps
/// the selection. The clear happens when the hub delivers the message, so
/// inside a hub transaction it waits for the transaction to end.
///
/// The helper publishes nothing to a message hub and never changes a node's
/// status, parent or `isCurrent`. The owning VM forwards `currentChanged` to its
/// own property notification (spec/14 rule 6), as with `ExpandableState`.
///
/// Ownership: the helper never disposes or detaches a node. It holds the root
/// weakly and the current node strongly. So a root may own its own selection
/// helper without a retain cycle only while the root itself is not current:
/// selecting the root forms a cycle until the selection is cleared or the
/// helper is disposed. Keep the root alive elsewhere. Once the root is
/// deallocated, `canSelect` is `false` for every node, but `current` keeps its
/// value until `clear()` or `dispose()`, because no message announces the
/// deallocation.
///
/// Threading: the helper follows the tree's model. `HierarchicalVM` uses no
/// locks, so the tree and this helper are used from one thread.
public final class TreeSelection<TModel, TVM: AnyObject> {
    private typealias Node = HierarchicalVM<TModel, TVM>

    /// One hub subscription, shared by every path node that uses that hub.
    private struct HubWatch {
        let hub: MessageHubProtocol
        let subscription: AnyCancellable
    }

    private weak var root: Node?
    private var currentNode: TVM?
    private var disposed = false
    private let currentSubject = PassthroughSubject<TVM?, Never>()
    /// Changes made while a value is being delivered wait here, so every
    /// subscriber sees the changes in order (spec/18 §10.3).
    private var pendingValues: [TVM?] = []
    private var emitting = false
    /// The watched path current..root, held weakly like `HierarchicalVM`'s
    /// path cache so the helper never keeps an ancestor alive.
    private var watchedPath: [WeakPathNode<Node>] = []
    private var hubWatches: [HubWatch] = []

    /// Creates a selection helper over the tree under `root`. Nothing is
    /// selected initially. `root` is normally a structural root, but any node
    /// may serve; the helper selects only within the tree below it.
    ///
    /// - Parameter root: the root of the selectable tree. Held weakly.
    public init(root: HierarchicalVM<TModel, TVM>) {
        self.root = root
    }

    /// The current node, or `nil` when nothing is selected. Always `nil` after
    /// `dispose()`.
    public var current: TVM? { currentNode }

    /// Emits the new `current` (or `nil`) once for every effective change.
    /// Hot: it never replays a value to a new subscriber. Emitted after the
    /// state and the hub watch are updated, so a subscriber may call
    /// `select(_:)` or `clear()` re-entrantly. Completes on `dispose()`.
    public var currentChanged: AnyPublisher<TVM?, Never> {
        currentSubject.eraseToAnyPublisher()
    }

    /// `true` when `node` is in the root's materialized tree and selectable:
    /// the helper is not disposed, `node` is non-`nil`, its `parent` chain
    /// reaches the root, and no node from `node` to the root is disposed.
    /// Never invokes a children factory.
    public func canSelect(_ node: TVM?) -> Bool {
        guard !disposed, let node else { return false }
        return selectablePath(from: node) != nil
    }

    /// Makes `node` current and emits it on `currentChanged`. Selecting the
    /// current node again does nothing. After `dispose()` the call does
    /// nothing and does not throw.
    ///
    /// - Throws: `TreeSelectionError.notInTree` when `canSelect(node)` is
    ///   `false`; `current` keeps its value and nothing is emitted.
    public func select(_ node: TVM) throws {
        guard !disposed else { return }
        guard let path = selectablePath(from: node) else {
            throw TreeSelectionError.notInTree
        }
        if currentNode === node { return }
        currentNode = node
        watch(path)
        emit(node)
    }

    /// Sets `current` to `nil` and emits `nil`. Does nothing when nothing is
    /// selected or after `dispose()`.
    public func clear() {
        guard !disposed, currentNode != nil else { return }
        clearSelection()
    }

    /// Releases every hub subscription, sets `current` to `nil` without
    /// emitting, and completes `currentChanged`. Later `select(_:)`, `clear()`
    /// and tree changes do nothing. Never disposes or detaches a node.
    /// Swift disposal does not throw, so every step runs. Idempotent.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        currentNode = nil
        pendingValues.removeAll()
        releaseWatch()
        currentSubject.send(completion: .finished)
    }

    // ── Private ─────────────────────────────────────────────────────────

    /// The path `node`..root when `node` is selectable, otherwise `nil`. Reads
    /// only `parent` links and `status`.
    private func selectablePath(from node: TVM) -> [Node]? {
        guard let root else { return nil }
        var path: [Node] = []
        var cursor: TVM? = node
        while let vm = cursor {
            // Every TVM is a HierarchicalVM<TModel, TVM> (see HierarchicalVM's
            // header); the conditional cast keeps a foreign object non-fatal.
            guard let treeNode = vm as? Node,
                  treeNode.status != .disposed else { return nil }
            path.append(treeNode)
            if treeNode === root { return path }
            cursor = treeNode.parent
        }
        return nil
    }

    /// Watches `path`: one subscription per distinct hub, reusing the
    /// subscriptions of hubs that stay on the path.
    private func watch(_ path: [Node]) {
        watchedPath = path.map { WeakPathNode($0) }
        var next: [HubWatch] = []
        for treeNode in path {
            let hub = treeNode.hub
            if next.contains(where: { $0.hub === hub }) { continue }
            if let existing = hubWatches.first(where: { $0.hub === hub }) {
                next.append(existing)
                continue
            }
            let subscription = hub.messages.sink { [weak self] message in
                self?.onMessage(message)
            }
            next.append(HubWatch(hub: hub, subscription: subscription))
        }
        let dropped = hubWatches.filter { entry in
            !next.contains(where: { $0.hub === entry.hub })
        }
        hubWatches = next
        for entry in dropped { entry.subscription.cancel() }
    }

    private func releaseWatch() {
        let released = hubWatches
        hubWatches = []
        watchedPath = []
        for entry in released { entry.subscription.cancel() }
    }

    /// Delivers `value` after the values already being delivered. A subscriber
    /// that selects or clears re-entrantly queues its change behind this one.
    private func emit(_ value: TVM?) {
        pendingValues.append(value)
        guard !emitting else { return }
        emitting = true
        defer {
            emitting = false
            if disposed { pendingValues.removeAll() }
        }
        while !pendingValues.isEmpty, !disposed {
            currentSubject.send(pendingValues.removeFirst())
        }
    }

    private func clearSelection() {
        currentNode = nil
        releaseWatch()
        emit(nil)
    }

    /// Re-checks membership on any message from a node on the watched path.
    private func onMessage(_ message: any Message) {
        guard !disposed, let current = currentNode else { return }
        let sender = message.senderObject
        guard watchedPath.contains(where: { $0.value === sender }) else { return }
        if let path = selectablePath(from: current) {
            // An intra-tree move changes the ancestors: watch the new path.
            watch(path)
        } else {
            clearSelection()
        }
    }
}
