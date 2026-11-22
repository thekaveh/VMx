/**
 * Interop with view-models and VMx helpers that the graph does not own (`read()`, R15.3 and R15.4), and the
 * prototype-only `tracked()` stand-in for native nodes (R15.5).
 */
import {
  AsyncRelayCommand,
  ComponentVMBase,
  DerivedProperty,
  DiscriminatorVM,
  ExpandableState,
} from "@thekaveh/vmx";
import { isTracking, track } from "./graph.js";
import { announcementNode, installTrackedAccessor, NATIVE_VM_PROPERTIES, resolveStream } from "./interop.js";
import { describeObject } from "./util.js";
import { activateState, existingState, explainState, stateOf } from "./vmState.js";

/**
 * Returns `source[name]` and, inside a frame, records a dependency (R15.3): on the node when `source` publishes
 * `name`, otherwise on the announcement node for (source, name). A source that is not a VMx object with a change
 * stream for `name` raises a usage error.
 */
export function read<S extends object, K extends keyof S & string>(source: S, name: K): S[K] {
  if (existingState(source)?.published.has(name) === true) return source[name];
  if (resolveStream(source, name) === null) {
    throw new Error(`read(): ${describeObject(source)} has no change stream for '${name}' (not a VMx object)`);
  }
  const value = source[name];
  if (isTracking()) {
    const node = announcementNode(source, name);
    if (node !== null) track(node);
  }
  return value;
}

function defaultTrackedNames(source: object): readonly string[] {
  if (source instanceof ExpandableState) return ["isExpanded"];
  if (source instanceof AsyncRelayCommand) return ["isExecuting"];
  if (source instanceof DiscriminatorVM) return ["activeKey", "modalDepth"];
  if (source instanceof DerivedProperty) return ["value"];
  if (source instanceof ComponentVMBase) return NATIVE_VM_PROPERTIES;
  return [];
}

/**
 * Prototype only (R15.5): makes the named getters of one VMx object instance tracked, so a direct read such as
 * `this.#expansion.isExpanded` records the announcement node. Without names, a default per type applies
 * (`isExpanded`, `isExecuting`, `activeKey`, `value`, or a view-model's native properties). VMx tracks its built-ins
 * natively; code written against a VMx implementation drops the call.
 */
export function tracked<T extends object>(source: T, ...names: readonly (keyof T & string)[]): T {
  const list: readonly string[] = names.length > 0 ? names : defaultTrackedNames(source);
  if (list.length === 0) throw new Error(`tracked(): name the tracked getters of ${describeObject(source)}`);
  for (const name of list) {
    if (resolveStream(source, name) === null) {
      throw new Error(`tracked(): ${describeObject(source)} has no change stream for '${name}'`);
    }
    installTrackedAccessor(source, name, false);
  }
  return source;
}

/** Activates `vm` now (R4.1, R4.2 e). Idempotent; a no-op once its disposal started. */
export function activate(vm: ComponentVMBase): void {
  activateState(stateOf(vm));
}

/** Development inspection (informative, R19.4): the nodes read by the last evaluation of `vm[name]`. */
export function explain(vm: ComponentVMBase, name: string): readonly { readonly owner: object; readonly name: string }[] {
  return explainState(vm, name);
}
