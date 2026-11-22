/**
 * The protected helpers of ComponentVMBase (the proposal's TypeScript API): V1 state, V2 computed, V3 commands,
 * V4 and V5 members, V6 reactions, V7 keyed resources.
 *
 * VMx would declare them `protected` on ComponentVMBase. The prototype installs them on
 * `ComponentVMBase.prototype` at import time (adding members, changing none) and types them with a module
 * augmentation (`augment.ts`), which can only add public members.
 *
 * Every helper except `change()` is a library operation and runs untracked (R5.7): registering, constructing a
 * member or starting a reaction from inside an effect adds no dependency to that effect.
 */
import {
  AsyncResourceVM,
  type AsyncResourceVMOptions,
  ComponentVMBase,
  type OwnedResource,
  type RelayCommand,
} from "@thekaveh/vmx";
import { createAsyncRelayCommand, createRelayCommand, createRelayCommandOf } from "./commands.js";
import type { Equality } from "./equality.js";
import {
  assertWritable,
  bumpVersions,
  change as graphChange,
  DerivedNode,
  ReactiveNode,
  readDerived,
  readSource,
  releaseNode,
  untracked,
  writeSources,
} from "./graph.js";
import { installNativeTracking } from "./interop.js";
import type { Reaction } from "./reaction.js";
import { EffectReaction, KeyedDriver, ValueReaction, WhileConstructedReaction } from "./reactions.js";
import type {
  AsyncCommandOptions,
  CommandOptions,
  FollowKeyOptions,
  KeyedResourceOptions,
  Memo,
  ReactionOptions,
  Signal,
} from "./types.js";
import { findDescriptor, internals, isLibraryMember } from "./util.js";
import {
  addMember,
  addReaction,
  announce,
  type ComputedEntry,
  ensureHooks,
  noteInactiveWrite,
  noteLateState,
  readComputed,
  stateOf,
  takeBaseline,
  type VMState,
} from "./vmState.js";

// ── Validation (R3.3) ────────────────────────────────────────────────────────────────────────────────────────

function validateName(state: VMState, name: string): void {
  if (state.published.has(name)) throw new Error(`${state.label}: '${name}' is already registered`);
  if (isLibraryMember(state.vm, name)) {
    throw new Error(`${state.label}: '${name}' is a VMx library property (already a native node)`);
  }
  if (Object.prototype.hasOwnProperty.call(state.vm, name)) {
    throw new Error(`${state.label}: '${name}' is already an own property; declare it with declare`);
  }
}

/** One accepted write of the view-model's own nodes; a write while not activated feeds R19.7. */
function write(state: VMState, changes: Iterable<readonly [ReactiveNode, unknown]>): void {
  if (writeSources(changes)) noteInactiveWrite(state);
}

const NO_HANDLE = (): void => undefined;

/**
 * The handle of a registration (R12.10, fix round 2): removes the reaction for good. Like a registration, it throws
 * ReactiveWriteError inside an evaluation frame (R16).
 */
function handleOf(reaction: Reaction | null): () => void {
  if (reaction === null) return NO_HANDLE;
  return () => {
    assertWritable("A reaction handle");
    untracked(() => reaction.remove());
  };
}

// ── V1: state ────────────────────────────────────────────────────────────────────────────────────────────────

function observable(
  this: ComponentVMBase,
  initial: Readonly<Record<string, unknown>>,
  equals?: Readonly<Record<string, Equality<unknown> | undefined>>,
): (patch: Readonly<Record<string, unknown>>) => void {
  assertWritable("observable()");
  return untracked(() => {
    const state = stateOf(this);
    // R3.4: a registration after disposal started installs nothing.
    if (state.disposalStarted) return () => undefined;
    ensureHooks(state);
    const keys = Object.keys(initial);
    for (const key of keys) {
      validateName(state, key);
      const found = findDescriptor(this, key);
      if (found !== undefined && (found.descriptor.get !== undefined || found.descriptor.set !== undefined)) {
        throw new Error(`${state.label}: state '${key}' names an accessor on the prototype chain`);
      }
    }
    const nodes = new Map<string, ReactiveNode>();
    for (const key of keys) {
      const node = new ReactiveNode("state", state, key, initial[key], equals?.[key] ?? Object.is);
      node.publish = () => announce(state, key);
      const get = (): unknown => readSource(node);
      Object.defineProperty(this, key, {
        configurable: true,
        enumerable: true,
        get,
        set: (value: unknown): void => write(state, [[node, value]]),
      });
      state.published.set(key, { kind: "state", node, get });
      nodes.set(key, node);
    }
    // R3.13 (fix round 2): on an activated view-model the registration is one write of its computeds.
    if (keys.length > 0) noteLateState(state, keys);
    return (patch: Readonly<Record<string, unknown>>): void => {
      const changes: [ReactiveNode, unknown][] = [];
      for (const key of Object.keys(patch)) {
        const node = nodes.get(key);
        if (node === undefined) throw new Error(`${state.label}: the writer has no state key '${key}'`);
        changes.push([node, patch[key]]);
      }
      // R3.1: one write of every key in the patch.
      write(state, changes);
    };
  });
}

class SignalBox<T> implements Signal<T> {
  readonly #node: ReactiveNode;
  readonly #state: VMState;

  constructor(node: ReactiveNode, state: VMState) {
    this.#node = node;
    this.#state = state;
  }

  get value(): T {
    return readSource(this.#node) as T;
  }

  set value(value: T) {
    write(this.#state, [[this.#node, value]]);
  }

  peek(): T {
    return this.#node.value as T;
  }
}

function signal(this: ComponentVMBase, initial: unknown, equals?: Equality<unknown>): Signal<unknown> {
  assertWritable("signal()");
  return untracked(() => {
    const state = stateOf(this);
    if (!state.disposalStarted) ensureHooks(state);
    const node = new ReactiveNode(
      "signal",
      state,
      `signal#${String(state.privateNodes.length + 1)}`,
      initial,
      equals ?? Object.is,
    );
    state.privateNodes.push(node);
    if (state.disposalStarted) releaseNode(node);
    return new SignalBox(node, state);
  });
}

// ── V2: computed ─────────────────────────────────────────────────────────────────────────────────────────────

function registerComputed(state: VMState, name: string, equals: Equality<unknown>): void {
  validateName(state, name);
  const vm = state.vm;
  const found = findDescriptor(vm, name);
  const protoGet = found?.descriptor.get;
  if (protoGet === undefined) throw new Error(`${state.label}: computed '${name}' has no getter on the prototype chain`);
  const protoSet = found?.descriptor.set;
  const invalidation = new ReactiveNode("invalidation", state, `${name}:invalidate`, 0, Object.is);
  const getter = (): unknown => protoGet.call(vm);
  const node = new DerivedNode(
    "computed",
    state,
    name,
    () => {
      readSource(invalidation);
      return getter();
    },
    equals,
  );
  node.publish = () => announce(state, name);
  const entry: ComputedEntry = {
    kind: "computed",
    name,
    node,
    invalidation,
    protoGet: getter,
    get: () => undefined,
    checkPending: false,
    plainDepth: 0,
  };
  const get = (): unknown => readComputed(state, entry);
  entry.get = get;
  const descriptor: PropertyDescriptor = { configurable: true, enumerable: false, get };
  // R3.2: an assignment is forwarded to the prototype setter unchanged.
  if (protoSet !== undefined) {
    descriptor.set = (value: unknown): void => {
      protoSet.call(vm, value);
    };
  }
  Object.defineProperty(vm, name, descriptor);
  state.published.set(name, entry);
  state.computedOrder.push(entry);
  // R4.3: a registration after activation takes its baseline at once.
  if (state.activated) takeBaseline(entry);
}

function computed(this: ComponentVMBase, ...args: unknown[]): void {
  assertWritable("computed()");
  untracked(() => {
    const state = stateOf(this);
    if (state.disposalStarted) return;
    ensureHooks(state);
    const specs: [string, Equality<unknown>][] = [];
    const first = args[0];
    if (args.length === 1 && typeof first === "object" && first !== null) {
      for (const [name, equals] of Object.entries(first as Record<string, Equality<unknown>>)) {
        specs.push([name, equals]);
      }
    } else {
      for (const name of args) specs.push([String(name), Object.is]);
    }
    for (const [name, equals] of specs) registerComputed(state, name, equals);
  });
}

class MemoBox<T> implements Memo<T> {
  readonly #node: DerivedNode;
  readonly #invalidation: ReactiveNode;
  readonly #state: VMState;
  /**
   * The memo's function, kept for one case: a read after disposal of a memo that was never evaluated (R5.6, fix
   * round 2, DD3). It belongs to the view-model's own object graph, so it keeps no other view-model alive.
   */
  readonly #fn: (previous: T | undefined) => T;

  constructor(node: DerivedNode, invalidation: ReactiveNode, state: VMState, fn: (previous: T | undefined) => T) {
    this.#node = node;
    this.#invalidation = invalidation;
    this.#state = state;
    this.#fn = fn;
  }

  get value(): T {
    return this.#read(true);
  }

  peek(): T {
    return this.#read(false);
  }

  invalidate(): void {
    bumpVersions([this.#invalidation], false);
    noteInactiveWrite(this.#state);
  }

  #read(track: boolean): T {
    const node = this.#node;
    if ((node.released || this.#state.disposing) && !node.evaluated && !node.hasError) {
      // A plain call that memoizes nothing, like a computed of a view-model that is not activated (R3.10).
      return track ? this.#fn(undefined) : untracked(() => this.#fn(undefined));
    }
    return readDerived(node, track) as T;
  }
}

function memo(this: ComponentVMBase, fn: (previous: unknown) => unknown, equals?: Equality<unknown>): Memo<unknown> {
  assertWritable("memo()");
  return untracked(() => {
    const state = stateOf(this);
    if (!state.disposalStarted) ensureHooks(state);
    const label = `memo#${String(state.privateNodes.length + 1)}`;
    const invalidation = new ReactiveNode("invalidation", state, `${label}:invalidate`, 0, Object.is);
    const node = new DerivedNode(
      "memo",
      state,
      label,
      (previous) => {
        readSource(invalidation);
        return fn(previous);
      },
      equals ?? Object.is,
    );
    state.privateNodes.push(node, invalidation);
    if (state.disposalStarted) {
      releaseNode(node);
      releaseNode(invalidation);
    }
    return new MemoBox(node, invalidation, state, fn);
  });
}

function invalidate(this: ComponentVMBase, ...names: string[]): void {
  assertWritable("invalidate()");
  const state = stateOf(this);
  const nodes: ReactiveNode[] = [];
  for (const name of names) {
    const entry = state.published.get(name);
    if (entry === undefined || entry.kind !== "computed") {
      throw new Error(`${state.label}: '${name}' is not a registered computed`);
    }
    nodes.push(entry.invalidation);
  }
  if (state.disposing) return;
  // R6.1: invalidate(...names) is one write; always accepted; a user write settles at once (fix round 2).
  bumpVersions(nodes, false);
  noteInactiveWrite(state);
}

function change<R>(this: ComponentVMBase, fn: () => R): R {
  return graphChange(fn);
}

// ── V3: commands ─────────────────────────────────────────────────────────────────────────────────────────────

function relayCommand(
  this: ComponentVMBase,
  task: () => void,
  canExecute?: () => boolean,
  options?: CommandOptions,
): RelayCommand {
  assertWritable("relayCommand()");
  return untracked(() => {
    const state = stateOf(this);
    if (!state.disposalStarted) ensureHooks(state);
    return createRelayCommand(state, task, canExecute, options);
  });
}

function relayCommandOf(
  this: ComponentVMBase,
  task: (parameter: unknown) => void,
  canExecute?: (parameter: unknown) => boolean,
  options?: CommandOptions,
): unknown {
  assertWritable("relayCommandOf()");
  return untracked(() => {
    const state = stateOf(this);
    if (!state.disposalStarted) ensureHooks(state);
    return createRelayCommandOf(state, task, canExecute, options);
  });
}

function asyncRelayCommand(
  this: ComponentVMBase,
  task: (signal: AbortSignal) => Promise<void>,
  canExecute?: () => boolean,
  options?: AsyncCommandOptions,
): unknown {
  assertWritable("asyncRelayCommand()");
  return untracked(() => {
    const state = stateOf(this);
    if (!state.disposalStarted) ensureHooks(state);
    return createAsyncRelayCommand(state, task, canExecute, options);
  });
}

// ── V4, V5: members ──────────────────────────────────────────────────────────────────────────────────────────

function member(this: ComponentVMBase, target: unknown, options?: Readonly<Record<string, unknown>>): ComponentVMBase {
  assertWritable("member()");
  return untracked(() => {
    const state = stateOf(this);
    if (!state.disposalStarted) ensureHooks(state);
    let vm: unknown = target;
    if (typeof target === "function") {
      // R11.2: explicit constructor injection by the owner (ADR-0003); no ambient lookup.
      const ctor = target as new (options: Readonly<Record<string, unknown>>) => unknown;
      vm = new ctor({ ...options, hub: this.hub, dispatcher: internals(state.lifecycle.vm)._dispatcher });
    }
    if (!(vm instanceof ComponentVMBase)) throw new TypeError("member() takes a VMx view-model or its constructor");
    return addMember(state, vm);
  });
}

// ── V6: reactions ────────────────────────────────────────────────────────────────────────────────────────────

function effect(this: ComponentVMBase, fn: () => void | (() => void)): () => void {
  assertWritable("effect()");
  return untracked(() => {
    const state = stateOf(this);
    if (state.disposalStarted) return NO_HANDLE;
    ensureHooks(state);
    return handleOf(addReaction(state, new EffectReaction(state.lifecycle, fn)));
  });
}

function reaction(
  this: ComponentVMBase,
  select: () => unknown,
  handler: (value: unknown, previous: unknown) => void,
  options?: ReactionOptions<unknown>,
): () => void {
  assertWritable("reaction()");
  return untracked(() => {
    const state = stateOf(this);
    if (state.disposalStarted) return NO_HANDLE;
    ensureHooks(state);
    return handleOf(addReaction(state, new ValueReaction(state.lifecycle, select, handler, options)));
  });
}

function whileConstructed(this: ComponentVMBase, setup: () => OwnedResource | void): () => void {
  assertWritable("whileConstructed()");
  return untracked(() => {
    const state = stateOf(this);
    if (state.disposalStarted) return NO_HANDLE;
    ensureHooks(state);
    return handleOf(addReaction(state, new WhileConstructedReaction(state.lifecycle, setup)));
  });
}

// ── V7: keyed resources ──────────────────────────────────────────────────────────────────────────────────────

function keyedResource(this: ComponentVMBase, options: KeyedResourceOptions<unknown, unknown>): AsyncResourceVM<unknown> {
  assertWritable("keyedResource()");
  return untracked(() => {
    const state = stateOf(this);
    if (!state.disposalStarted) ensureHooks(state);
    const key = options.key;
    const load = options.load;
    let driver: KeyedDriver<unknown> | null = null;
    const resourceOptions: AsyncResourceVMOptions<unknown> = {
      name: options.name ?? `${this.name}:resource`,
      hint: "",
      hub: this.hub,
      dispatcher: internals(state.lifecycle.vm)._dispatcher,
      // R14.1: the loader reads key() untracked when the load starts, and tells the driver the exact key (R14.3).
      loader: (signal) => {
        const startKey = untracked(key);
        driver?.noteLoadKey(startKey);
        return load(startKey, signal);
      },
      ...(options.retention !== undefined ? { retention: options.retention } : {}),
      ...(options.cleanupValue !== undefined ? { cleanupValue: options.cleanupValue } : {}),
    };
    const resource = new AsyncResourceVM<unknown>(resourceOptions);
    addMember(state, resource);
    if (!state.lifecycle.disposalStarted) {
      driver = new KeyedDriver(state.lifecycle, resource, options);
      addReaction(state, driver);
    }
    return resource;
  });
}

function followKey(this: ComponentVMBase, resource: unknown, options: FollowKeyOptions<unknown>): () => void {
  assertWritable("followKey()");
  if (!(resource instanceof AsyncResourceVM)) throw new TypeError("followKey() takes an AsyncResourceVM");
  return untracked(() => {
    const state = stateOf(this);
    if (state.disposalStarted) return NO_HANDLE;
    ensureHooks(state);
    installNativeTracking(resource);
    return handleOf(addReaction(state, new KeyedDriver(state.lifecycle, resource as AsyncResourceVM<unknown>, options)));
  });
}

// ── Installation ─────────────────────────────────────────────────────────────────────────────────────────────

const HELPERS: Readonly<Record<string, (...args: never[]) => unknown>> = {
  observable,
  signal,
  computed,
  memo,
  invalidate,
  change,
  relayCommand,
  relayCommandOf,
  asyncRelayCommand,
  member,
  effect,
  reaction,
  whileConstructed,
  keyedResource,
  followKey,
};

let installed = false;

/** Adds the helpers to ComponentVMBase.prototype (idempotent). */
export function installReactiveHelpers(): void {
  if (installed) return;
  installed = true;
  const prototype = ComponentVMBase.prototype as unknown as Record<string, unknown>;
  for (const [name, helper] of Object.entries(HELPERS)) {
    Object.defineProperty(prototype, name, { configurable: true, enumerable: false, writable: true, value: helper });
  }
}
