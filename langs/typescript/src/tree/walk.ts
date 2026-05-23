/**
 * walk / find — depth-first pre-order tree traversal.
 *
 * See spec/13-tree-utilities.md (UTIL-001..003).
 */
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

function* _children(node: ComponentVMBase): Iterable<ComponentVMBase> {
  // Composites and groups expose Symbol.iterator yielding child VMs.
  if (Symbol.iterator in node) {
    for (const child of node as unknown as Iterable<ComponentVMBase>) {
      if (child instanceof ComponentVMBase) yield child;
    }
    return;
  }
  // Aggregates expose component1..component5 slots.
  for (let i = 1; i <= 5; i++) {
    const slot = (node as unknown as Record<string, unknown>)[`component${String(i)}`];
    if (slot instanceof ComponentVMBase) yield slot;
  }
}
