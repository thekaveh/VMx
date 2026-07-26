import { ComponentVMBase } from "../components/componentVMBase.js";
import { disposeBestEffort } from "../components/disposal.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import type {
  IOwningParentVM,
  ParentTransfer,
} from "../components/componentVMBase.js";

/** @internal Fixed-slot parent adaptor used by aggregate implementations. */
export class AggregateParent implements IOwningParentVM {
  readonly supportsChildSelection = false;
  readonly currentChild = null;

  constructor(
    readonly owner: ComponentVMBase,
    private readonly slots: () => readonly ComponentVMBase[],
  ) {}

  get ownerParent(): IOwningParentVM | null { return this.owner._parent; }
  selectChild(_vm: ComponentVMBase): void { /* fixed aggregate has no selection */ }
  deselectChild(_vm: ComponentVMBase): void { /* fixed aggregate has no selection */ }
  containsChild(vm: ComponentVMBase): boolean {
    const identity = vm._ownershipIdentity;
    return this.slots().some((child) => child._ownershipIdentity === identity);
  }
  detachForTransfer(vm: ComponentVMBase): ParentTransfer {
    throw new Error(`Cannot transfer '${vm.name}' out of a fixed aggregate slot`);
  }
}

/** @internal Validate all factories before overwriting any fixed slot. */
export function validateAggregateSlots(
  parent: AggregateParent,
  children: readonly ComponentVMBase[],
): void {
  const seen = new Set<ComponentVMBase>();
  for (const child of children) {
    const identity = child._ownershipIdentity;
    if (seen.has(identity)) {
      throw new Error("Aggregate factories returned duplicate canonical identity");
    }
    seen.add(identity);
    if (child._parent !== null) {
      throw new Error(`Cannot populate aggregate with '${child.name}': already owned`);
    }
    let cursor: IOwningParentVM | null = parent;
    while (cursor !== null) {
      if (cursor.owner._ownershipIdentity === identity) {
        throw new Error("Aggregate ownership would create a parent cycle");
      }
      cursor = cursor.ownerParent;
    }
  }
}

/** @internal Replace parent links only after every factory validates. */
export function commitAggregateSlots(
  parent: AggregateParent,
  previous: readonly (ComponentVMBase | null)[],
  next: readonly ComponentVMBase[],
): void {
  for (const child of previous) {
    if (child?._parent === parent) child._parent = null;
  }
  for (const child of next) child._parent = parent;
}

/** @internal Reserve replacement identities across validation, cleanup, and commit. */
export function replaceAggregateSlots(
  parent: AggregateParent,
  previous: readonly (ComponentVMBase | null)[],
  next: readonly ComponentVMBase[],
  assign: () => void,
  notifyCommittedError: () => void,
): boolean {
  const identities = [...new Set(next.map((child) => child._ownershipIdentity))];
  if (identities.some((identity) => identity._ownershipInProgress)) {
    throw new Error("Aggregate ownership transaction is already in progress");
  }
  for (const identity of identities) identity._ownershipInProgress = true;
  try {
    validateAggregateSlots(parent, next);
    let failed = false;
    let firstError: unknown;
    try {
      disposeBestEffort(previous.map((child) => () => child?.dispose()));
    } catch (error) {
      failed = true;
      firstError = error;
    }
    if (parent.owner.status === ConstructionStatus.Disposed) {
      try {
        disposeBestEffort(next.map((child) => () => child.dispose()));
      } catch (error) {
        if (!failed) {
          failed = true;
          firstError = error;
        }
      }
      if (failed) throw firstError;
      return false;
    }
    assign();
    commitAggregateSlots(parent, previous, next);
    if (failed) {
      notifyCommittedError();
      throw firstError;
    }
    return true;
  } finally {
    for (const identity of identities) identity._ownershipInProgress = false;
  }
}
