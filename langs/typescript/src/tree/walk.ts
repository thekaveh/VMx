/**
 * walk / find / walkExpanded — depth-first pre-order tree traversal.
 *
 * See spec/13-tree-utilities.md (UTIL-001..003, EXP-005).
 */
import type { IExpandable } from "../capabilities/expansion.js";
import { hasCapability } from "../capabilities/registry.js";
import { ComponentVMBase } from "../components/componentVMBase.js";

export function* walk(root: ComponentVMBase): Iterable<ComponentVMBase> {
  yield root;
  for (const child of _children(root)) {
    yield* walk(child);
  }
}

export function find(
  root: ComponentVMBase,
  predicate: (vm: ComponentVMBase) => boolean,
): ComponentVMBase | null {
  for (const node of walk(root)) {
    if (predicate(node)) return node;
  }
  return null;
}

export function* walkExpanded(
  root: ComponentVMBase,
): Iterable<ComponentVMBase> {
  yield root;
  if (hasCapability(root, "IExpandable")) {
    const expandable = root as unknown as IExpandable;
    if (!expandable.isExpanded) return;
  }
  for (const child of _children(root)) {
    yield* walkExpanded(child);
  }
}

/**
 * The typed accessor an aggregate VM exposes for tree traversal — its component
 * slots in declaration order. VMX-023: walking via this method (instead of
 * reflecting over `component${i}` name strings bounded at 6) keeps traversal
 * correct for any arity, including a future AggregateVM7+.
 */
interface IAggregateComponents {
  components(): readonly ComponentVMBase[];
}

function _hasComponents(node: object): node is IAggregateComponents {
  return (
    typeof (node as Partial<IAggregateComponents>).components === "function"
  );
}

function* _children(node: ComponentVMBase): Iterable<ComponentVMBase> {
  // Composites and groups expose Symbol.iterator yielding child VMs.
  if (Symbol.iterator in node) {
    for (const child of node as unknown as Iterable<ComponentVMBase>) {
      if (child instanceof ComponentVMBase) yield child;
    }
    return;
  }
  // Aggregates expose a typed components() accessor (VMX-023) — no per-arity
  // slot-name reflection, so AggregateVM7+ is traversed automatically.
  if (_hasComponents(node)) {
    for (const slot of node.components()) {
      if (slot instanceof ComponentVMBase) yield slot;
    }
  }
}
