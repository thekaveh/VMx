/**
 * The prototype's stand-in for the library rules that VMx would implement inside its own classes (R5.7, R5.8, R9.8,
 * R10.*, R15.2; README.md lists the stand-ins):
 *
 * - R5.7: a VMx library operation runs untracked, and inside an evaluation frame it throws `ReactiveWriteError`
 *   before it changes anything (R16).
 * - R15.2 (fix round 2): a library mutation (a container or collection change, a selection change, a model
 *   assignment, a load, an expansion change) is one write of its native nodes: they settle once, when it returns.
 *   A lifecycle operation is one write per status transition. A command's `execute` runs the user's task and is no
 *   library write.
 * - R15.2 (fix round 2), state first: a library publication (the dual-channel helper, the local-only raise, a status
 *   transition, a command raise, an expansion change) commits its native nodes before it delivers anything, and
 *   holds the drain until it returns.
 * - R9.8: a view-model's direct send comes after its queued announcements (the producer flush), for every
 *   view-model, at the helper, the local-only raise and the status transition. R19.3 reports a hand-written
 *   notification of a registered name.
 * - R5.8: a hub send runs untracked.
 * - R10.2, R10.7 (fix round 2): every command tracks its own predicate (`commands.ts`).
 * - R13.3 (fix round 2): a view-model's dispose tears its reactions down before anything else is disposed.
 * - R11.5 (fix round 2): a member that reaches Disposed leaves its owner's member list.
 *
 * VMx reads its own private state natively and does not need this module. The prototype wraps the methods below on
 * the prototypes of the classes VMx 3.30.0 exports, once, at import time. Getters and queries (`canSelect`,
 * `count`, `snapshot`, ...) stay transparent: tracking flows through them (R5.3).
 */
import * as VMX from "@thekaveh/vmx";
import { ConstructionStatus } from "@thekaveh/vmx";
import {
  DECORATOR_PROTOTYPE,
  decoratorCanExecute,
  decoratorCanExecuteChanged,
  raisesTrackedCanExecute,
  releaseCommandFrame,
  releaseDecorator,
  TRACKED_COMMANDS,
  trackedCanExecute,
} from "./commands.js";
import { developmentDiagnostics, reportOnce } from "./diagnostics.js";
import { assertWritable, flushProducer, libraryOperation, untracked } from "./graph.js";
import { isGraphEmission, publication } from "./interop.js";
import { existingState, memberDisposed, rawStatus, startDisposal } from "./vmState.js";

type Method = (this: unknown, ...args: unknown[]) => unknown;

/** The lifecycle operations: untracked, refused inside an evaluation frame; each status transition is one write. */
const LIFECYCLE: Readonly<Record<string, readonly string[]>> = {
  ComponentVMBase: ["construct", "destruct", "reconstruct", "dispose"],
  ForwardingComponentVM: ["construct", "destruct", "reconstruct", "dispose"],
  ForwardingCompositeVM: ["construct", "destruct", "reconstruct", "dispose"],
  CompositeVMBase: ["dispose"],
  GroupVM: ["dispose"],
  FilteredCompositeVM: ["dispose"],
  AggregateVM1: ["dispose"],
  AggregateVM2: ["dispose"],
  AggregateVM3: ["dispose"],
  AggregateVM4: ["dispose"],
  AggregateVM5: ["dispose"],
  AggregateVM6: ["dispose"],
};

/** Command executions: untracked and refused inside an evaluation frame; the task's writes settle as they happen. */
const EXECUTIONS: Readonly<Record<string, readonly string[]>> = {
  RelayCommand: ["execute"],
  RelayCommandOf: ["execute"],
  AsyncRelayCommand: ["execute", "executeAsync"],
  CompositeCommand: ["execute"],
  DecoratorCommand: ["execute"],
  ConfirmationDecoratorCommand: ["execute", "executeAsync"],
};

/** Library mutations: untracked, refused inside an evaluation frame, one write of their native nodes (R15.2). */
const MUTATIONS: Readonly<Record<string, readonly string[]>> = {
  ComponentVMBase: ["select", "deselect"],
  ComponentVMOf: ["_setModel", "republishModel"],
  ReadonlyComponentVMOf: ["republishModel"],
  ForwardingComponentVM: ["republishModel", "select", "deselect"],
  ForwardingCompositeVM: [
    "select",
    "deselect",
    "selectComponent",
    "deselectComponent",
    "add",
    "insert",
    "setAt",
    "remove",
    "removeAt",
    "clear",
    "move",
    "batchUpdate",
  ],
  CompositeVMBase: [
    "selectComponent",
    "deselectComponent",
    "add",
    "insert",
    "remove",
    "removeAt",
    "setAt",
    "clear",
    "move",
    "batchUpdate",
  ],
  GroupVM: ["add", "insert", "remove", "removeAt", "setAt", "clear", "move", "batchUpdate"],
  HierarchicalVM: ["addChild", "removeChild", "reparentChild", "attachMany", "invalidateChildren", "invalidateSubtree"],
  FilteredCompositeVM: ["setPredicate", "setCurrent", "moveToNextVisible", "moveToPreviousVisible"],
  ScoredFilteredCompositeVM: ["refreshScores"],
  AsyncResourceVM: ["load", "reload", "cancel"],
  ExpandableState: ["toggleExpansion", "dispose"],
  SearchableState: ["search", "dispose"],
  PagedComposition: ["moveToFirstPage", "moveToPreviousPage", "moveToNextPage", "moveToLastPage", "dispose"],
  TokenPagedComposition: ["dispose"],
  DiscriminatorVM: ["setActiveKey", "modalOpen", "modalClose", "clearModals", "dispose"],
  FormVM: ["setModel", "approveAsync", "dispose"],
  DerivedProperty: ["setValue", "dispose"],
  ModalVM: ["dismiss", "dispose"],
  RelayCommand: ["dispose"],
  RelayCommandOf: ["dispose"],
  AsyncRelayCommand: ["cancel", "dispose"],
  CompositeCommand: ["dispose"],
  DecoratorCommand: ["dispose"],
  ConfirmationDecoratorCommand: ["dispose"],
  ObservableList: ["push", "insert", "pop", "removeAt", "remove", "replace", "replaceAll", "clear"],
  ServicedObservableCollection: [
    "push",
    "pop",
    "remove",
    "removeAt",
    "splice",
    "replace",
    "setAt",
    "replaceAll",
    "move",
    "clear",
  ],
  KeyedServicedObservableCollection: [
    "push",
    "pop",
    "remove",
    "removeAt",
    "delete",
    "splice",
    "replace",
    "setAt",
    "replaceAll",
    "move",
    "clear",
    "upsert",
  ],
  ObservableDictionary: ["set", "add", "delete", "clear"],
};

const wrapped = new WeakSet<object>();

function prototypeOf(exportName: string): object | null {
  const value = (VMX as Readonly<Record<string, unknown>>)[exportName];
  if (typeof value !== "function") return null;
  const prototype = (value as { readonly prototype?: unknown }).prototype;
  return typeof prototype === "object" && prototype !== null ? prototype : null;
}

function wrapMethod(prototype: object, name: string, make: (original: Method) => Method): void {
  const descriptor = Object.getOwnPropertyDescriptor(prototype, name);
  if (descriptor === undefined || typeof descriptor.value !== "function") return;
  if (wrapped.has(descriptor.value as object)) return;
  const replacement = make(descriptor.value as Method);
  wrapped.add(replacement);
  Object.defineProperty(prototype, name, { ...descriptor, value: replacement });
}

function wrapGetter(prototype: object, name: string, make: (original: (this: unknown) => unknown) => (this: unknown) => unknown): void {
  const descriptor = Object.getOwnPropertyDescriptor(prototype, name);
  const getter = descriptor?.get;
  if (descriptor === undefined || getter === undefined || wrapped.has(getter)) return;
  const replacement = make(getter as (this: unknown) => unknown);
  wrapped.add(replacement);
  Object.defineProperty(prototype, name, { ...descriptor, get: replacement });
}

function lifecycle(label: string, original: Method, dispose: boolean): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    assertWritable(`${label}()`);
    return untracked(() => {
      // R13.3 step 2 (fix round 2): the reactions end before the children and members are disposed.
      if (dispose && this instanceof VMX.ComponentVMBase) startDisposal(this);
      return original.apply(this, args);
    });
  };
}

function execution(label: string, original: Method): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    assertWritable(`${label}()`);
    return untracked(() => original.apply(this, args));
  };
}

function mutation(label: string, original: Method, after?: (target: object) => void): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    assertWritable(`${label}()`);
    const result = libraryOperation(() => untracked(() => original.apply(this, args)), false);
    if (after !== undefined && typeof this === "object" && this !== null) after(this);
    return result;
  };
}

/** The library's own raises of `status` and `isConstructed` inside a status transition commit nothing more. */
const statusTransitions = new Map<object, number>();

/** R9.8 and R19.3 at a direct send of `vm`. */
function beforeDirectSend(vm: object, name: string): void {
  const state = existingState(vm);
  if (state === undefined || isGraphEmission(vm, name)) return;
  if (developmentDiagnostics() && state.published.has(name)) {
    // R19.3: the graph announces registered names; the hand-written call should be deleted.
    reportOnce(
      `notify:${state.className}.${name}`,
      `${state.className}.${name}: hand-written _notifyPropertyChanged of a registered name; delete it`,
    );
  }
  // R9.8: a direct send of this view-model comes after its queued announcements.
  flushProducer(state);
}

function notifyPublication(original: Method): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    const vm = this as object;
    const name = String(args[0]);
    beforeDirectSend(vm, name);
    return publication(vm, [name], () => original.apply(this, args));
  };
}

function raisePublication(original: Method): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    const vm = this as object;
    const name = String(args[0]);
    beforeDirectSend(vm, name);
    const inTransition = statusTransitions.has(vm) && (name === "status" || name === "isConstructed");
    return publication(vm, inTransition ? [] : [name], () => original.apply(this, args), [name]);
  };
}

function statusPublication(original: Method): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    const vm = this as object;
    const next = args[0] as ConstructionStatus;
    const current = rawStatus(vm);
    // Disposed is terminal: VMx publishes nothing more.
    if (current === ConstructionStatus.Disposed) return original.apply(this, args);
    const state = existingState(vm);
    if (state !== undefined && !state.disposing) flushProducer(state);
    const commit = ["status"];
    if ((current === ConstructionStatus.Constructed) !== (next === ConstructionStatus.Constructed)) {
      commit.push("isConstructed");
    }
    statusTransitions.set(vm, (statusTransitions.get(vm) ?? 0) + 1);
    let result: unknown;
    try {
      result = publication(vm, commit, () => original.apply(this, args), ["status", "isConstructed"]);
    } finally {
      const count = (statusTransitions.get(vm) ?? 1) - 1;
      if (count > 0) statusTransitions.set(vm, count);
      else statusTransitions.delete(vm);
    }
    // R11.5 (fix round 2): a disposed member leaves its owner's member list.
    if (next === ConstructionStatus.Disposed && vm instanceof VMX.ComponentVMBase) memberDisposed(vm);
    return result;
  };
}

function commandRaise(names: readonly string[]): (original: Method) => Method {
  return (original) =>
    function (this: unknown, ...args: unknown[]): unknown {
      return publication(this as object, names, () => original.apply(this, args));
    };
}

function expansionPublication(label: string, expanding: boolean, original: Method): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    assertWritable(`${label}()`);
    const state = this as { readonly isExpanded: boolean };
    const changes = untracked(() => state.isExpanded) !== expanding;
    return publication(this as object, changes ? ["isExpanded"] : [], () => original.apply(this, args), ["isExpanded"]);
  };
}

function delivery(original: Method): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    return untracked(() => original.apply(this, args));
  };
}

let installed = false;

/** Wraps the VMx 3.30.0 operations, publications and command queries once (idempotent). */
export function installLibraryRules(): void {
  if (installed) return;
  installed = true;
  for (const [className, names] of Object.entries(LIFECYCLE)) {
    const prototype = prototypeOf(className);
    if (prototype === null) continue;
    for (const name of names) {
      wrapMethod(prototype, name, (original) => lifecycle(`${className}.${name}`, original, name === "dispose"));
    }
  }
  for (const [className, names] of Object.entries(EXECUTIONS)) {
    const prototype = prototypeOf(className);
    if (prototype === null) continue;
    for (const name of names) wrapMethod(prototype, name, (original) => execution(`${className}.${name}`, original));
  }
  for (const [className, names] of Object.entries(MUTATIONS)) {
    const prototype = prototypeOf(className);
    if (prototype === null) continue;
    for (const name of names) {
      let after: ((target: object) => void) | undefined;
      if (name === "dispose" && prototype === DECORATOR_PROTOTYPE) after = releaseDecorator;
      else if (name === "dispose" && TRACKED_COMMANDS.some((entry) => entry.prototype === prototype)) {
        after = releaseCommandFrame;
      }
      wrapMethod(prototype, name, (original) => mutation(`${className}.${name}`, original, after));
    }
  }
  const expandable = prototypeOf("ExpandableState");
  if (expandable !== null) {
    wrapMethod(expandable, "expand", (original) => expansionPublication("ExpandableState.expand", true, original));
    wrapMethod(expandable, "collapse", (original) => expansionPublication("ExpandableState.collapse", false, original));
  }
  const base = prototypeOf("ComponentVMBase");
  if (base !== null) {
    wrapMethod(base, "_notifyPropertyChanged", notifyPublication);
    wrapMethod(base, "_raisePropertyChanged", raisePublication);
    wrapMethod(base, "_setStatus", statusPublication);
    wrapMethod(base, "_setIsCurrent", delivery);
  }
  const hub = prototypeOf("MessageHub");
  if (hub !== null) wrapMethod(hub, "send", delivery);
  for (const { prototype, union } of TRACKED_COMMANDS) {
    wrapMethod(prototype, "canExecute", (original) => trackedCanExecute(original, union));
    const raised = prototype === prototypeOf("AsyncRelayCommand") ? ["canExecute", "isExecuting"] : ["canExecute"];
    wrapMethod(prototype, "raiseCanExecuteChanged", commandRaise(raised));
  }
  const innerStream = Object.getOwnPropertyDescriptor(DECORATOR_PROTOTYPE, "canExecuteChanged")?.get;
  if (innerStream !== undefined) {
    wrapMethod(DECORATOR_PROTOTYPE, "canExecute", (original) =>
      decoratorCanExecute(original, innerStream as (this: unknown) => unknown),
    );
    wrapGetter(DECORATOR_PROTOTYPE, "canExecuteChanged", decoratorCanExecuteChanged);
  }
  for (const className of ["CompositeCommand", "ConfirmationDecoratorCommand"]) {
    const prototype = prototypeOf(className);
    if (prototype !== null) wrapMethod(prototype, "canExecute", raisesTrackedCanExecute);
  }
}
