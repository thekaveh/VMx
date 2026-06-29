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
}
