//
// Tree-utilities (spec/13-tree-utilities.md). Pure, synchronous reads over
// the composite/group/aggregate tree — no lifecycle side effects. Mirrors
// langs/typescript/src/tree/walk.ts.
//
// UTIL-001 walk(_:)  — DFS pre-order traversal returning every reachable node.
// UTIL-002            — empty/nil aggregate slots are skipped during traversal.
// UTIL-003 find(_:where:) — returns first matching node, short-circuits on match.
//
// All three throw `HierarchyError.invalidFactoryOutput` when they reach a
// `HierarchicalVM` whose lazy children factory returns invalid output
// (spec/13 §6.1, ADR-0170). They never trap.
//

// MARK: - Internal child-enumeration protocol

/// Internal protocol used by `walk` and `find` to enumerate a container node's
/// children in traversal order. `_TreeContainer` is NOT public surface: it is an
/// implementation detail that lets `walk`/`find` share a single descent path for
/// `CompositeVM`, `GroupVM`, and `AggregateVM1..6` without per-arity switches.
/// Each conformance excludes empty (nil) optional slots (UTIL-002).
///
/// The requirement is an effectful (`get throws`) property so that the
/// `HierarchicalVM` conformance can report invalid lazy factory output
/// (ADR-0170). The non-throwing conformances below, including the
/// `childComponents` members that `AggregateVM1..6` already declare, satisfy
/// it unchanged.
protocol _TreeContainer {
    var childComponents: [ComponentVMBase] { get throws }
}

// MARK: - CompositeVM conformance

extension CompositeVM: _TreeContainer {
    /// One `snapshot()` reads the membership once, so a removal on another
    /// thread cannot shrink the list between a `count` read and an `at(_:)`
    /// read (ADR-0187).
    var childComponents: [ComponentVMBase] {
        snapshot().map { $0 as ComponentVMBase }
    }
}

// MARK: - GroupVM conformance

extension GroupVM: _TreeContainer {
    /// One `snapshot()` reads the membership once (ADR-0187).
    var childComponents: [ComponentVMBase] {
        snapshot().map { $0 as ComponentVMBase }
    }
}

// MARK: - HierarchicalVM conformance (HIER-012: walkExpanded descent)

/// Makes every `HierarchicalVM<TModel, TVM>` node descend-able by `walk` /
/// `walkExpanded` / `find`. `TVM: AnyObject` so `children` returns `[TVM]`;
/// `compactMap { $0 as? ComponentVMBase }` recovers the base type. The cast
/// always succeeds at runtime because every `TVM` IS-A
/// `HierarchicalVM<TModel, TVM>` IS-A `ComponentVMBase` (CRTP invariant — see
/// `HierarchicalVM.swift` header).
///
/// Reads `tryChildren()`, not the fail-fast `children` accessor, so invalid
/// lazy factory output throws `HierarchyError.invalidFactoryOutput` out of the
/// walk and leaves the node unmaterialized and retryable (HIER-031, ADR-0170).
extension HierarchicalVM: _TreeContainer {
    var childComponents: [ComponentVMBase] {
        get throws {
            try tryChildren().get().compactMap { $0 as? ComponentVMBase }
        }
    }
}

// MARK: - AggregateVM1..6 conformances (nil slots skipped — UTIL-002)

extension AggregateVM1: _TreeContainer {
    var childComponents: [ComponentVMBase] {
        var out: [ComponentVMBase] = []
        if let c = component1 { out.append(c) }
        return out
    }
}

extension AggregateVM2: _TreeContainer {
    var childComponents: [ComponentVMBase] {
        var out: [ComponentVMBase] = []
        if let c = component1 { out.append(c) }
        if let c = component2 { out.append(c) }
        return out
    }
}

extension AggregateVM3: _TreeContainer {
    var childComponents: [ComponentVMBase] {
        var out: [ComponentVMBase] = []
        if let c = component1 { out.append(c) }
        if let c = component2 { out.append(c) }
        if let c = component3 { out.append(c) }
        return out
    }
}

extension AggregateVM4: _TreeContainer {
    var childComponents: [ComponentVMBase] {
        var out: [ComponentVMBase] = []
        if let c = component1 { out.append(c) }
        if let c = component2 { out.append(c) }
        if let c = component3 { out.append(c) }
        if let c = component4 { out.append(c) }
        return out
    }
}

extension AggregateVM5: _TreeContainer {
    var childComponents: [ComponentVMBase] {
        var out: [ComponentVMBase] = []
        if let c = component1 { out.append(c) }
        if let c = component2 { out.append(c) }
        if let c = component3 { out.append(c) }
        if let c = component4 { out.append(c) }
        if let c = component5 { out.append(c) }
        return out
    }
}

extension AggregateVM6: _TreeContainer {
    var childComponents: [ComponentVMBase] {
        var out: [ComponentVMBase] = []
        if let c = component1 { out.append(c) }
        if let c = component2 { out.append(c) }
        if let c = component3 { out.append(c) }
        if let c = component4 { out.append(c) }
        if let c = component5 { out.append(c) }
        if let c = component6 { out.append(c) }
        return out
    }
}

// MARK: - Public API

/// DFS pre-order walk: yields `root`, then each child subtree left to right.
/// Empty aggregate slots are skipped (UTIL-002). A leaf `ComponentVM` yields
/// exactly itself. No lifecycle transitions are triggered; this is a pure read.
///
/// - Throws: `HierarchyError.invalidFactoryOutput` when a `HierarchicalVM`
///   in the tree has a lazy children factory that returns invalid output.
///   That node stays unmaterialized, and a later walk retries the factory.
public func walk(_ root: ComponentVMBase) throws -> [ComponentVMBase] {
    try preOrder(root, shouldDescend: { _ in true })
}

/// DFS pre-order like `walk`, but does NOT descend into the children of a node
/// that is `Expandable` and currently collapsed (`isExpanded == false`). A node
/// that is not `Expandable` is always descended (EXP-005). Materialized array,
/// consistent with `walk`/`find` (ADR-0059 §2.5).
///
/// - Throws: `HierarchyError.invalidFactoryOutput`, as `walk` does, for a
///   descended `HierarchicalVM` whose lazy children factory returns invalid
///   output. A collapsed node's children are not read, so they cannot throw.
public func walkExpanded(_ root: ComponentVMBase) throws -> [ComponentVMBase] {
    try preOrder(root, shouldDescend: isExpandedOrNotExpandable)
}

/// `false` only for an `Expandable` node that is currently collapsed (EXP-005).
private func isExpandedOrNotExpandable(_ node: ComponentVMBase) -> Bool {
    guard let expandable = node as? Expandable else { return true }
    return expandable.isExpanded
}

/// Pre-order traversal with an explicit stack of pending child lists, so tree
/// depth is not limited by the call stack. A node's children are read only when
/// the walk descends into it, in the same order as the recursive walk, so the
/// read order and the ADR-0170 error timing (spec/13 §6.1) are unchanged.
private func preOrder(
    _ root: ComponentVMBase,
    shouldDescend: (ComponentVMBase) -> Bool
) throws -> [ComponentVMBase] {
    var out: [ComponentVMBase] = []
    // Each frame holds the children of one open node and the next child to visit.
    var frames: [(children: [ComponentVMBase], next: Int)] = [(children: [root], next: 0)]
    while let top = frames.indices.last {
        guard frames[top].next < frames[top].children.count else {
            frames.removeLast()
            continue
        }
        let node = frames[top].children[frames[top].next]
        frames[top].next += 1
        out.append(node)
        if shouldDescend(node), let container = node as? _TreeContainer {
            let children = try container.childComponents
            if !children.isEmpty { frames.append((children: children, next: 0)) }
        }
    }
    return out
}

/// Returns the first node in DFS pre-order for which `predicate` is `true`,
/// or `nil` if no node matches. Short-circuits: stops descending the tree as
/// soon as a match is found (UTIL-003). The predicate is invoked at most once
/// per visited node.
///
/// - Throws: `HierarchyError.invalidFactoryOutput`, as `walk` does, when the
///   search reaches a `HierarchicalVM` whose lazy children factory returns
///   invalid output before it finds a match.
public func find(
    _ root: ComponentVMBase,
    where predicate: (ComponentVMBase) -> Bool
) throws -> ComponentVMBase? {
    var frames: [(children: [ComponentVMBase], next: Int)] = [(children: [root], next: 0)]
    while let top = frames.indices.last {
        guard frames[top].next < frames[top].children.count else {
            frames.removeLast()
            continue
        }
        let node = frames[top].children[frames[top].next]
        frames[top].next += 1
        if predicate(node) { return node }
        if let container = node as? _TreeContainer {
            let children = try container.childComponents
            if !children.isEmpty { frames.append((children: children, next: 0)) }
        }
    }
    return nil
}
