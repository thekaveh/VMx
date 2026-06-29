//
// Tree-utilities (spec/13-tree-utilities.md). Pure, synchronous reads over
// the composite/group/aggregate tree — no lifecycle side effects. Mirrors
// langs/typescript/src/tree/walk.ts.
//
// UTIL-001 walk(_:)  — DFS pre-order traversal returning every reachable node.
// UTIL-002            — empty/nil aggregate slots are skipped during traversal.
// UTIL-003 find(_:where:) — returns first matching node, short-circuits on match.
//

// MARK: - Internal child-enumeration protocol

/// Internal protocol used by `walk` and `find` to enumerate a container node's
/// children in traversal order. `_TreeContainer` is NOT public surface: it is an
/// implementation detail that lets `walk`/`find` share a single descent path for
/// `CompositeVM`, `GroupVM`, and `AggregateVM1..6` without per-arity switches.
/// Each conformance excludes empty (nil) optional slots (UTIL-002).
protocol _TreeContainer {
    var childComponents: [ComponentVMBase] { get }
}

// MARK: - CompositeVM conformance

extension CompositeVM: _TreeContainer {
    var childComponents: [ComponentVMBase] {
        (0..<count).map { at($0) as ComponentVMBase }
    }
}

// MARK: - GroupVM conformance

extension GroupVM: _TreeContainer {
    var childComponents: [ComponentVMBase] {
        (0..<count).map { at($0) as ComponentVMBase }
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
public func walk(_ root: ComponentVMBase) -> [ComponentVMBase] {
    var out: [ComponentVMBase] = [root]
    if let container = root as? _TreeContainer {
        for child in container.childComponents {
            out.append(contentsOf: walk(child))
        }
    }
    return out
}

/// DFS pre-order like `walk`, but does NOT descend into the children of a node
/// that is `Expandable` and currently collapsed (`isExpanded == false`). A node
/// that is not `Expandable` is always descended (EXP-005). Materialized array,
/// consistent with `walk`/`find` (ADR-0060).
public func walkExpanded(_ root: ComponentVMBase) -> [ComponentVMBase] {
    var out: [ComponentVMBase] = [root]
    let collapsed = (root as? Expandable).map { !$0.isExpanded } ?? false
    if !collapsed, let container = root as? _TreeContainer {
        for child in container.childComponents { out.append(contentsOf: walkExpanded(child)) }
    }
    return out
}

/// Returns the first node in DFS pre-order for which `predicate` is `true`,
/// or `nil` if no node matches. Short-circuits: stops descending the tree as
/// soon as a match is found (UTIL-003). The predicate is invoked at most once
/// per visited node.
public func find(
    _ root: ComponentVMBase,
    where predicate: (ComponentVMBase) -> Bool
) -> ComponentVMBase? {
    if predicate(root) { return root }
    if let container = root as? _TreeContainer {
        for child in container.childComponents {
            if let hit = find(child, where: predicate) { return hit }
        }
    }
    return nil
}
