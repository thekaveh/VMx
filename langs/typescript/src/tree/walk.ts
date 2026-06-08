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

function* _children(node: ComponentVMBase): Iterable<ComponentVMBase> {
  // Composites and groups expose Symbol.iterator yielding child VMs.
  if (Symbol.iterator in node) {
    for (const child of node as unknown as Iterable<ComponentVMBase>) {
      if (child instanceof ComponentVMBase) yield child;
    }
    return;
  }
  // Aggregates expose component1..component6 slots.
  for (let i = 1; i <= 6; i++) {
    const slot = (node as unknown as Record<string, unknown>)[`component${String(i)}`];
    if (slot instanceof ComponentVMBase) yield slot;
  }
}
