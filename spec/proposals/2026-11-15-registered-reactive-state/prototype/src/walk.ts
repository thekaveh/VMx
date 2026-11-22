/**
 * walk / walkExpanded / find that also visit registered members (R11.6, spec 13).
 *
 * A VM's container children (or its aggregate `components()`) come first, then its members in registration order,
 * depth-first. A member that `components()` already yielded is skipped. VMx would change its own walks; the
 * prototype exports these.
 */
import { ComponentVMBase, hasCapability, type IExpandable } from "@thekaveh/vmx";
import { membersOf } from "./vmState.js";

function* children(node: ComponentVMBase): Iterable<ComponentVMBase> {
  const seen = new Set<ComponentVMBase>();
  if (Symbol.iterator in node) {
    for (const child of node as unknown as Iterable<unknown>) {
      if (child instanceof ComponentVMBase) {
        seen.add(child);
        yield child;
      }
    }
  } else {
    const components = (node as unknown as { readonly components?: unknown }).components;
    if (typeof components === "function") {
      for (const child of (components as () => readonly unknown[]).call(node)) {
        if (child instanceof ComponentVMBase) {
          seen.add(child);
          yield child;
        }
      }
    }
  }
  for (const member of membersOf(node)) {
    if (!seen.has(member)) yield member;
  }
}

export function* walk(root: ComponentVMBase): Iterable<ComponentVMBase> {
  yield root;
  for (const child of children(root)) yield* walk(child);
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

export function* walkExpanded(root: ComponentVMBase): Iterable<ComponentVMBase> {
  yield root;
  if (hasCapability(root, "IExpandable") && !(root as unknown as IExpandable).isExpanded) return;
  for (const child of children(root)) yield* walkExpanded(child);
}
