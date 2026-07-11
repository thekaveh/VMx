//
// HierarchicalVM<TModel, TVM> — first-class recursive tree ViewModel.
//
// Each node carries a typed `TModel` and may contain children of the same
// concrete type `TVM`. Children are lazy by default (the factory runs on first
// access, then the result is cached); eager materialization is opt-in via the
// `eagerChildren` constructor flag (wired by the child-construction task — the
// flag is stored here so HIER-007..009 can read it without re-touching the
// init surface).
//
// This is the foundational tree-identity type for the whole hierarchical area;
// later tasks add structural mutation (add/remove/reparent + hub messages),
// capability composition, and the fluent builder.
//
// CRTP (curiously recurring template pattern), ADR-0028 §3.2: `TVM` is the
// concrete subclass — the canonical concrete shape is
// `final class MyNode: HierarchicalVM<MyModel, MyNode>`.
//
// CROSS-FLAVOR DIVERGENCE (documented; for the Task-9 ADR). C#/TS express the
// recursive bound directly (`where TVM : HierarchicalVM<TModel, TVM>` /
// `TVM extends HierarchicalVM<TModel, TVM>`). Swift's compiler REJECTS the
// equivalent class constraint `TVM: HierarchicalVM<TModel, TVM>` as a
// "self-referential generic requirement". So Swift binds `TVM: AnyObject` (the
// closest expressible bound) and recovers the recursive guarantee with two
// isolated, always-safe downcasts:
//   • `selfNode` (`self as! TVM`) — the concrete view of `self`, used wherever a
//     `TVM` is required (parent links, sibling identity, path elements).
//   • `node(_:)` (`vm as! HierarchicalVM<TModel, TVM>`) — the base view of a
//     neighbour, used to read its tree members (`parent`, `children`, `depth`).
// Both are sound because every `TVM` in this design IS a
// `HierarchicalVM<TModel, TVM>` subclass at runtime. Concentrating the casts in
// these two members keeps every other self/neighbour reference cast-free.
//
// See spec/18-hierarchical-vm.md and ADR-0028.
//
import Foundation
import Combine

/// Thrown by `HierarchicalVM.reparentChild(_:)` when the requested reparent
/// would create a cycle (HIER-018): the child is `self` or one of `self`'s
/// ancestors.
public enum HierarchyError: Error {
    case invalidReparent
}

/// Missing-parent retention policy for batch hierarchy ingestion.
public enum MissingParentPolicy: Equatable {
    case park
    case reject
}

/// Typed reason why one batch item was not attached.
public enum BatchAttachRejectionReason: Equatable {
    case duplicateExistingKey
    case duplicateBatchKey
    case alreadyAttached
    case missingParent
    case cycle
    case selectorFailed
    case attachmentFailed
}

/// One typed, non-throwing batch-attachment rejection.
public struct BatchAttachRejection<TVM> {
    public let item: TVM
    public let reason: BatchAttachRejectionReason
    public let detail: String?

    init(item: TVM, reason: BatchAttachRejectionReason, detail: String? = nil) {
        self.item = item
        self.reason = reason
        self.detail = detail
    }
}

/// Structured result of one batch-attachment attempt.
public struct BatchAttachResult<TVM> {
    public let added: [TVM]
    public let duplicates: [TVM]
    public let orphans: [TVM]
    public let rejections: [BatchAttachRejection<TVM>]
}

private struct BatchAttachCandidate<TVM, Key: Hashable> {
    let item: TVM
    let key: Key
    let parentKey: Key?
    let retainIfMissing: Bool
}

/// Abstract recursive tree ViewModel. Concrete subclasses follow the CRTP
/// shape, e.g. `final class MyNode: HierarchicalVM<MyModel, MyNode>`.
///
/// - `TModel`: per-node domain model.
/// - `TVM`: the concrete subclass. Bound to `AnyObject` because Swift cannot
///   express the self-referential class constraint
///   `TVM: HierarchicalVM<TModel, TVM>` (see the file header); the recursive
///   relationship is upheld at runtime via `selfNode` / `node(_:)`.
open class HierarchicalVM<TModel, TVM: AnyObject>: ComponentVMBase {

    // ── Construction inputs ─────────────────────────────────────────────

    /// The domain model carried by this tree node.
    public let model: TModel

    /// Factory that produces this node's children. Invoked once, lazily, on
    /// first access to `children` (or eagerly at construct() time when
    /// `eagerChildren` is set — wired by the child-construction task).
    private let childrenFactory: (TVM) -> [TVM]

    /// When `true`, the full subtree is materialized at construct() time
    /// (depth-first). Stored here so the child-construction task (HIER-008/009)
    /// can read it without re-opening this init surface; the baseline
    /// tree-identity surface (HIER-001..006) does not act on it.
    private let eagerChildren: Bool

    // ── Tree links / caches ─────────────────────────────────────────────

    /// The parent node; `nil` when this node is the root.
    ///
    /// Weak to break the ARC retain cycle: a parent holds strong references to
    /// its children (via the materialized `children` array), so the upward link
    /// must be weak or the whole subtree would leak. `TVM: AnyObject`, so `weak`
    /// is well-formed.
    public private(set) weak var parent: TVM?

    /// Lazily-populated, cached children. `nil` until first materialization.
    private var _children: [TVM]?

    /// Cached root→self path. `nil` until first access. (Invalidation on
    /// reparent is added with the structural-mutation task.)
    private var _pathCache: [TVM]?

    /// Missing-parent items retained on this structural root.
    private var parkedAttachItems: [TVM] = []

    // ── CRTP downcasts (isolated; see file header) ──────────────────────

    /// The concrete-subclass (CRTP) view of `self`. Every `TVM` IS a
    /// `HierarchicalVM<TModel, TVM>` at runtime, but the compiler cannot prove
    /// it through the generic base — so the one `self as! TVM` lives here.
    private var selfNode: TVM { self as! TVM }

    /// The base `HierarchicalVM` view of a neighbour `TVM`, recovered so its
    /// tree members can be read. Sound for the same reason as `selfNode`: every
    /// `TVM` is a `HierarchicalVM<TModel, TVM>` subclass. Isolated here rather
    /// than scattered across `depth` / `isFirst` / `isLast` / path building.
    private func node(_ vm: TVM) -> HierarchicalVM<TModel, TVM> {
        vm as! HierarchicalVM<TModel, TVM>
    }

    // ── Construction ────────────────────────────────────────────────────

    /// - Parameters:
    ///   - model: the per-node domain model.
    ///   - childrenFactory: produces children given the (CRTP) parent node;
    ///     invoked lazily on first `children` access.
    ///   - hub: required message hub (ADR-0052 — no implicit default).
    ///   - dispatcher: required dispatcher (ADR-0052 — no implicit default).
    ///   - name: node name; when empty, defaults to the concrete type name
    ///     (`String(describing: TVM.self)`) — the Swift expression of HIER-017's
    ///     "name defaults to the concrete VM type name". `TVM.self` is used
    ///     rather than `type(of: self)` because `self` is not available before
    ///     `super.init`; under the canonical `final class` CRTP shape the two
    ///     resolve to the same name.
    ///   - hint: optional hint string.
    ///   - eagerChildren: opt-in eager subtree materialization (read by a later
    ///     task; inert for HIER-001..006).
    public init(
        model: TModel,
        childrenFactory: @escaping (TVM) -> [TVM],
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        name: String = "",
        hint: String = "",
        eagerChildren: Bool = false
    ) {
        self.model = model
        self.childrenFactory = childrenFactory
        self.eagerChildren = eagerChildren
        let resolvedName = name.isEmpty ? String(describing: TVM.self) : name
        super.init(
            name: resolvedName,
            hint: hint,
            hub: hub,
            dispatcher: dispatcher
        )
    }

    // ── Tree identity ───────────────────────────────────────────────────

    /// `true` when this node has no parent.
    public var isRoot: Bool { parent == nil }

    /// Distance from the root. Root is 0; a child is `parent.depth + 1`.
    public var depth: Int {
        guard let parent = parent else { return 0 }
        return node(parent).depth + 1
    }

    /// The ordered child nodes. Lazily materialized on first access — the
    /// factory runs once (seeding each child's `parent` to this node), then the
    /// result is cached for the lifetime of the node.
    public var children: [TVM] {
        if let cached = _children { return cached }
        let materialized = materializeChildren()
        _children = materialized
        return materialized
    }

    /// `true` when this node has no children. Accessing this materializes
    /// children if not already done.
    public var isLeaf: Bool { children.isEmpty }

    /// `true` when this is the first child in its parent's `children`
    /// (always `false` for the root). Uses reference identity (`===`).
    public var isFirst: Bool {
        guard let parent = parent, let first = node(parent).children.first else {
            return false
        }
        return first === selfNode
    }

    /// `true` when this is the last child in its parent's `children`
    /// (always `false` for the root). Uses reference identity (`===`).
    public var isLast: Bool {
        guard let parent = parent, let last = node(parent).children.last else {
            return false
        }
        return last === selfNode
    }

    /// Cached root-first path `[root, …, self]`. Built by walking up the
    /// `parent` chain on first access, then cached.
    public var path: [TVM] {
        if let cached = _pathCache { return cached }
        let built = buildPath()
        _pathCache = built
        return built
    }

    // ── Lifecycle override — eager construction ──────────────────────────

    /// When `eagerChildren` is set, override `_onConstruct()` to materialize
    /// the child list and recursively construct each child *before* this
    /// node's own `_onConstruct()` returns. Because `ComponentVMBase.construct()`
    /// sets status to `.constructed` only after `_onConstruct()` completes, the
    /// children (and their descendants) all reach `.constructed` before the parent
    /// does — producing depth-first order (HIER-008, HIER-009). The cascade is
    /// synchronous and throwing (ADR-0053): if any child's `construct()` throws,
    /// the error propagates up and the caller's `construct()` rolls the parent
    /// back to its prior status (LIFE-014).
    open override func _onConstruct() throws {
        try super._onConstruct()
        guard eagerChildren else { return }
        for child in children {
            try node(child).construct()
        }
    }

    // ── Structural mutation ─────────────────────────────────────────────

    /// Appends `child` to this node's children list, wires its parent backpointer,
    /// invalidates path caches in the subtree, and publishes two messages on the hub:
    ///
    /// 1. `PropertyChangedMessage("parent")` with `sender == child` (HIER-010).
    /// 2. `TreeStructureChangedMessage(.added, …)` (HIER-011).
    public func addChild(_ child: TVM) {
        if _children == nil { _ = children } // materialize
        let index = _children!.count
        _children!.append(child)
        setHierarchicalParent(of: child, to: selfNode) // → PropertyChangedMessage
        hub.send(TreeStructureChangedMessage(
            sender: selfNode,
            senderName: name,
            change: .added,
            affected: node(child),
            index: index
        ))
    }

    /// Removes `child` from this node's children list, clears its parent, invalidates
    /// path caches, and publishes `TreeStructureChangedMessage(.removed, …)` (HIER-011).
    public func removeChild(_ child: TVM) {
        guard let idx = _children?.firstIndex(where: { $0 === child }) else { return }
        _children!.remove(at: idx)
        setHierarchicalParent(of: child, to: nil) // → PropertyChangedMessage
        hub.send(TreeStructureChangedMessage(
            sender: selfNode,
            senderName: name,
            change: .removed,
            affected: node(child),
            index: idx
        ))
    }

    /// Moves `child` from its current parent to this node and publishes
    /// `TreeStructureChangedMessage(.reparented, index: -1, …)` (HIER-011).
    ///
    /// - Throws: `HierarchyError.invalidReparent` when `child` is `self` or one of
    ///   `self`'s ancestors — attaching would create a parent cycle (HIER-018). On
    ///   rejection the tree is completely unchanged and no message is published.
    public func reparentChild(_ child: TVM) throws {
        // Already our child → no-op (parity with C#/Python/TS): re-appending would
        // reorder the sibling list and emit a spurious `.reparented` message.
        if node(child).parent === selfNode { return }
        // HIER-018: child is self or one of self's ancestors → cycle.
        if path.contains(where: { $0 === child }) {
            throw HierarchyError.invalidReparent
        }
        // Detach from old parent silently (no PropertyChangedMessage yet).
        if let oldParent = node(child).parent {
            node(oldParent)._children?.removeAll(where: { $0 === child })
        }
        // Attach to this node.
        if _children == nil { _ = children } // materialize
        _children!.append(child)
        setHierarchicalParent(of: child, to: selfNode) // → PropertyChangedMessage
        hub.send(TreeStructureChangedMessage(
            sender: selfNode,
            senderName: name,
            change: .reparented,
            affected: node(child),
            index: -1
        ))
    }

    /// Number of missing-parent items retained on the structural root.
    public var parkedAttachCount: Int {
        node(treeRoot()).parkedAttachItems.count
    }

    /// Attaches an out-of-order, consumer-keyed batch beneath the structural
    /// root. A nil parent key means a direct child of that root. Ordinary
    /// ingestion anomalies are returned as typed rejections.
    public func attachMany<Key: Hashable>(
        _ items: [TVM],
        keyOf: (TVM) throws -> Key,
        parentKeyOf: (TVM) throws -> Key?,
        onMissingParent: MissingParentPolicy = .park
    ) -> BatchAttachResult<TVM> {
        let rootNode = treeRoot()
        let root = node(rootNode)
        let parked = root.parkedAttachItems
        root.parkedAttachItems.removeAll()
        var added: [TVM] = []
        var duplicates: [TVM] = []
        var orphans: [TVM] = []
        var rejections: [BatchAttachRejection<TVM>] = []
        var existing: [Key: TVM] = [:]

        do {
            for materialized in root.materializedSubtree() {
                let key = try keyOf(materialized)
                if existing[key] == nil { existing[key] = materialized }
            }
        } catch {
            root.parkedAttachItems.append(contentsOf: parked)
            rejections.append(contentsOf: (parked + items).map {
                BatchAttachRejection(
                    item: $0,
                    reason: .selectorFailed,
                    detail: String(describing: error)
                )
            })
            return BatchAttachResult(
                added: added,
                duplicates: duplicates,
                orphans: orphans,
                rejections: rejections
            )
        }

        var candidates: [BatchAttachCandidate<TVM, Key>] = []
        var candidateKeys = Set<Key>()
        let active = parked.map { ($0, true) } + items.map { ($0, false) }
        for (item, wasParked) in active {
            let key: Key
            let parentKey: Key?
            do {
                key = try keyOf(item)
                parentKey = try parentKeyOf(item)
            } catch {
                if wasParked { root.parkedAttachItems.append(item) }
                rejections.append(BatchAttachRejection(
                    item: item,
                    reason: .selectorFailed,
                    detail: String(describing: error)
                ))
                continue
            }

            if existing[key] != nil {
                duplicates.append(item)
                rejections.append(BatchAttachRejection(item: item, reason: .duplicateExistingKey))
                continue
            }
            if candidateKeys.contains(key) {
                duplicates.append(item)
                rejections.append(BatchAttachRejection(item: item, reason: .duplicateBatchKey))
                continue
            }
            if node(item).parent != nil {
                rejections.append(BatchAttachRejection(item: item, reason: .alreadyAttached))
                continue
            }
            candidateKeys.insert(key)
            candidates.append(BatchAttachCandidate(
                item: item,
                key: key,
                parentKey: parentKey,
                retainIfMissing: wasParked || onMissingParent == .park
            ))
        }

        var unresolved = candidates
        while !unresolved.isEmpty {
            var next: [BatchAttachCandidate<TVM, Key>] = []
            var progressed = false
            for candidate in unresolved {
                let parent: TVM?
                if let parentKey = candidate.parentKey {
                    parent = existing[parentKey]
                } else {
                    parent = rootNode
                }
                guard let parent = parent else {
                    next.append(candidate)
                    continue
                }

                // After selector evaluation, Swift's addChild path is
                // non-throwing; fallible flavors wrap and roll back this step.
                node(parent).addChild(candidate.item)
                existing[candidate.key] = candidate.item
                added.append(candidate.item)
                progressed = true
            }
            unresolved = next
            if !progressed { break }
        }

        let unresolvedByKey = Dictionary(uniqueKeysWithValues: unresolved.map { ($0.key, $0) })
        for candidate in unresolved {
            let isCycle = batchParentChainCycles(candidate, unresolved: unresolvedByKey)
            let reason: BatchAttachRejectionReason = isCycle ? .cycle : .missingParent
            rejections.append(BatchAttachRejection(item: candidate.item, reason: reason))
            if !isCycle {
                orphans.append(candidate.item)
                if candidate.retainIfMissing { root.parkedAttachItems.append(candidate.item) }
            }
        }

        return BatchAttachResult(
            added: added,
            duplicates: duplicates,
            orphans: orphans,
            rejections: rejections
        )
    }

    /// Drops this node's materialized child cache. The next `children` access
    /// invokes the children factory again. Invalidating an unmaterialized node
    /// is a no-op.
    public func invalidateChildren() {
        guard _children != nil else { return }
        _children = nil
        hub.send(PropertyChangedMessage(
            sender: selfNode,
            senderName: name,
            propertyName: "children"
        ))
    }

    /// Drops cached children for this node and all materialized descendants.
    public func invalidateSubtree() {
        guard let cached = _children else { return }
        for child in cached {
            node(child).invalidateSubtree()
        }
        invalidateChildren()
    }

    open override func _onDispose() {
        parkedAttachItems.removeAll()
        super._onDispose()
    }

    // ── Private helpers ─────────────────────────────────────────────────

    /// Runs the factory and seeds each produced child's `parent` to this node
    /// (via the CRTP `selfNode`).
    private func materializeChildren() -> [TVM] {
        let result = childrenFactory(selfNode)
        for child in result {
            node(child).parent = selfNode
        }
        return result
    }

    private func treeRoot() -> TVM {
        var current = selfNode
        while let parent = node(current).parent { current = parent }
        return current
    }

    private func materializedSubtree() -> [TVM] {
        var result: [TVM] = []
        var stack: [TVM] = [selfNode]
        while let current = stack.popLast() {
            result.append(current)
            if let cached = node(current)._children {
                stack.append(contentsOf: cached.reversed())
            }
        }
        return result
    }

    private func batchParentChainCycles<Key: Hashable>(
        _ candidate: BatchAttachCandidate<TVM, Key>,
        unresolved: [Key: BatchAttachCandidate<TVM, Key>]
    ) -> Bool {
        var seen = Set<Key>()
        var current: BatchAttachCandidate<TVM, Key>? = candidate
        while let value = current {
            if !seen.insert(value.key).inserted { return true }
            guard let parentKey = value.parentKey else { return false }
            current = unresolved[parentKey]
        }
        return false
    }

    /// Walks up the `parent` chain from this node, then reverses so the root
    /// comes first.
    private func buildPath() -> [TVM] {
        var chain: [TVM] = []
        var current: TVM? = selfNode
        while let vm = current {
            chain.append(vm)
            current = node(vm).parent
        }
        chain.reverse()
        return chain
    }

    /// Sets `child`'s parent backpointer to `newParent`, invalidates path caches
    /// for the child's subtree, and publishes `PropertyChangedMessage("parent")`
    /// with `sender == child` on the hub. No-op when the parent is unchanged.
    private func setHierarchicalParent(of child: TVM, to newParent: TVM?) {
        let childNode = node(child)
        // Skip when parent is already newParent (compare by reference identity).
        let alreadySame: Bool = {
            switch (childNode.parent, newParent) {
            case (.none, .none): return true
            case let (.some(a), .some(b)): return a === b
            default: return false
            }
        }()
        if alreadySame { return }

        childNode.parent = newParent
        childNode._pathCache = nil
        invalidatePathCacheDescendants(of: child)
        childNode.hub.send(PropertyChangedMessage(
            sender: child,
            senderName: childNode.name,
            propertyName: "parent"
        ))
    }

    /// Recursively clears `_pathCache` for all materialized descendants of `vm`.
    private func invalidatePathCacheDescendants(of vm: TVM) {
        guard let kids = node(vm)._children else { return }
        for kid in kids {
            node(kid)._pathCache = nil
            invalidatePathCacheDescendants(of: kid)
        }
    }
}
