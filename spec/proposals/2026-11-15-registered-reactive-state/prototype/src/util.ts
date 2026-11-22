/**
 * Small runtime helpers: descriptor lookup on the prototype chain, VMx library-class detection (a VMx implementation
 * marks its library prototypes; the prototype derives the set from the package's exports), and the typing of the
 * protected VMx members that the reactive layer calls.
 */
import * as VMX from "@thekaveh/vmx";
import type { ConstructionStatus, IDispatcher, IMessageHub, OwnedResource } from "@thekaveh/vmx";

/** The protected and internal ComponentVMBase members that the prototype calls (VMx 3.30.0). */
export interface VMInternals {
  readonly name: string;
  readonly status: ConstructionStatus;
  readonly hub: IMessageHub;
  readonly _dispatcher: IDispatcher;
  readonly _parent: unknown;
  readonly _ownershipIdentity: object;
  own<T extends OwnedResource>(resource: T): T;
  _notifyPropertyChanged(propertyName: string): void;
  construct(): void;
  destruct(): void;
  dispose(): void;
}

/** Views a VMx view-model through its protected members. */
export function internals(vm: object): VMInternals {
  return vm as unknown as VMInternals;
}

/** The prototypes of the classes that VMx exports (the library boundary of R3.3 and R19.2). */
export const libraryPrototypes: ReadonlySet<object> = (() => {
  const set = new Set<object>();
  for (const value of Object.values(VMX) as unknown[]) {
    if (typeof value !== "function") continue;
    const prototype = (value as { readonly prototype?: unknown }).prototype;
    if (typeof prototype === "object" && prototype !== null) set.add(prototype);
  }
  return set;
})();

export interface FoundDescriptor {
  readonly descriptor: PropertyDescriptor;
  readonly owner: object;
}

/** The first descriptor of `name` on the prototype chain of `target`, skipping own properties. */
export function findDescriptor(target: object, name: string): FoundDescriptor | undefined {
  let proto = Object.getPrototypeOf(target) as object | null;
  while (proto !== null) {
    const descriptor = Object.getOwnPropertyDescriptor(proto, name);
    if (descriptor !== undefined) return { descriptor, owner: proto };
    proto = Object.getPrototypeOf(proto) as object | null;
  }
  return undefined;
}

/** True when `name` is a member of a VMx library class in the prototype chain of `target` (R3.3). */
export function isLibraryMember(target: object, name: string): boolean {
  let proto = Object.getPrototypeOf(target) as object | null;
  while (proto !== null) {
    if (libraryPrototypes.has(proto) && Object.prototype.hasOwnProperty.call(proto, name)) return true;
    proto = Object.getPrototypeOf(proto) as object | null;
  }
  return false;
}

/** Calls the method `name` found on the prototype chain, skipping an own (hook) property. */
export function callProto(target: object, name: string, ...args: unknown[]): unknown {
  const found = findDescriptor(target, name);
  const method: unknown = found?.descriptor.value;
  if (typeof method !== "function") throw new TypeError(`${name} is not a method of ${describeObject(target)}`);
  return (method as (...a: unknown[]) => unknown).apply(target, args);
}

/** Installs an own, non-enumerable method on one instance (a per-instance hook). */
export function defineMethod(target: object, name: string, method: (...args: never[]) => unknown): void {
  Object.defineProperty(target, name, { configurable: true, enumerable: false, writable: true, value: method });
}

/** `Class(name)` for a view-model, `Class` for another object. */
export function describeObject(target: object): string {
  const ctor = (target as { readonly constructor?: { readonly name?: string } }).constructor;
  const className = ctor?.name ?? "Object";
  const name = (target as { readonly name?: unknown }).name;
  return typeof name === "string" && target instanceof VMX.ComponentVMBase ? `${className}(${name})` : className;
}

/** Runs every action, then rethrows the first failure (VMx's best-effort teardown rule, spec 02 §7.1). */
export function disposeBestEffort(actions: Iterable<() => void>): void {
  let failed = false;
  let firstError: unknown;
  for (const action of actions) {
    try {
      action();
    } catch (error) {
      if (!failed) {
        failed = true;
        firstError = error;
      }
    }
  }
  if (failed) throw firstError;
}

/** Releases an owned resource; failures are isolated and swallowed (spec 02 §2.3, DISP-009, R12.8). */
export function releaseResource(resource: OwnedResource | null | undefined): void {
  if (resource === null || resource === undefined) return;
  try {
    if (typeof resource === "function") resource();
    else if ("dispose" in resource) resource.dispose();
    else resource.unsubscribe();
  } catch {
    // Teardown is best-effort.
  }
}
