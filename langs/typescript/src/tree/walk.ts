/**
 * walk / find / walkExpanded — depth-first pre-order tree traversal.
 *
 * See spec/13-tree-utilities.md (UTIL-001..003, EXP-005).
 */
import type { IExpandable } from "../capabilities/expansion.js";
import { hasCapability } from "../capabilities/registry.js";
import { ComponentVMBase } from "../components/componentVMBase.js";

export function* walk(root: ComponentVMBase): Iterable<ComponentVMBase> {
  yield* _preOrder(root, () => true);
}

export function find<T extends ComponentVMBase>(
  root: ComponentVMBase,
  predicate: (vm: ComponentVMBase) => vm is T,
): T | null;
export function find(
  root: ComponentVMBase,
  predicate: (vm: ComponentVMBase) => boolean,
): ComponentVMBase | null;
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
  yield* _preOrder(root, (node) => !_isCollapsed(node));
}

function _isCollapsed(node: ComponentVMBase): boolean {
  if (!hasCapability(node, "IExpandable")) return false;
  const expandable = node as unknown as IExpandable;
  return !expandable.isExpanded;
}

/**
 * Pre-order walk with an explicit stack of child iterators. Each node is
 * yielded before its children are read, and a node's children are read only
 * when the walk descends into it, so the factory and error timing matches a
 * recursive walk (spec/13 §6.1, ADR-0170). The stack keeps the walk iterative,
 * so tree depth is not limited by the call stack.
 */
function* _preOrder(
  root: ComponentVMBase,
  shouldDescend: (node: ComponentVMBase) => boolean,
): Iterable<ComponentVMBase> {
  yield root;
  if (!shouldDescend(root)) return;
  const stack: Iterator<ComponentVMBase>[] = [
    _children(root)[Symbol.iterator](),
  ];
  while (stack.length > 0) {
    const step = (stack[stack.length - 1] as Iterator<ComponentVMBase>).next();
    if (step.done) {
      stack.pop();
      continue;
    }
    const child = step.value;
    yield child;
    if (shouldDescend(child)) {
      stack.push(_children(child)[Symbol.iterator]());
    }
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
