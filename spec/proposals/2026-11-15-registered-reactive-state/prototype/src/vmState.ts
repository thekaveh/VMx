/**
 * The reactive state of one view-model: its registered names, members and reactions, and the lifecycle sequences
 * of R13.* (R3.*, R4.*, R11.*, R12.*, R13.*, R17.*, R19.*, with the rules that the two fix rounds added).
 *
 * The prototype does not change VMx 3.30.0. It hooks one instance at a time, at its first registration, with own
 * properties that call the prototype-chain methods: `_onConstruct`, `_onDestruct`, `_onDispose` and `_setStatus`
 * (the lifecycle sequences) and the `propertyChanged` getter (activation on the first subscription, R4.2 b). The
 * rules that hold for every view-model (publications, producer order, library operations) are prototype wrappers in
 * `library.ts`.
 */
import { ComponentVMBase, ConstructionStatus } from "@thekaveh/vmx";
import type { CollectionChangedEvent } from "@thekaveh/vmx";
import { defer, isObservable, type Observable, type Subscription } from "rxjs";
import { developmentDiagnostics, later, reportOnce, reportStreamFed } from "./diagnostics.js";
import { structurallyEqual } from "./equality.js";
import { ReactiveCycleError } from "./errors.js";
import {
  asEvaluation,
  assertWritable,
  baseline,
  bumpVersions,
  compareValues,
  DerivedNode,
  flushProducer,
  isConsumerRead,
  isMemoized,
  probe,
  type ReactiveNode,
  readDerived,
  readSource,
  releaseNode,
  untracked,
} from "./graph.js";
import { asGraphEmission, installNativeTracking, releaseAnnouncements } from "./interop.js";
import { currentRun, type Reaction, type ReactionOwner } from "./reaction.js";
import {
  callProto,
  defineMethod,
  describeObject,
  disposeBestEffort,
  findDescriptor,
  internals,
  isLibraryMember,
  libraryPrototypes,
} from "./util.js";

export interface StateEntry {
  readonly kind: "state";
  readonly node: ReactiveNode;
  readonly get: () => unknown;
}

export interface ComputedEntry {
  readonly kind: "computed";
  readonly name: string;
  readonly node: DerivedNode;
  /** A version node that `invalidate(name)` bumps; the computed and the readers of its plain getter read it. */
  readonly invalidation: ReactiveNode;
  readonly protoGet: () => unknown;
  get: () => unknown;
  /** A deferred staleness check is scheduled (R19.1). */
  checkPending: boolean;
  /** Nesting of the plain getter (before activation or after disposal): a re-entry is a cycle (R16, CC1). */
  plainDepth: number;
}

export type PublishedEntry = StateEntry | ComputedEntry;

/** The reactive state of one view-model instance. */
export class VMState implements ReactionOwner {
  /** The state of the canonical ownership identity: members, reactions and activation follow it (R3.8). */
  readonly lifecycle: VMState;
  /** Decorator states that follow this canonical identity. */
  readonly dependents: VMState[] = [];
  readonly published = new Map<string, PublishedEntry>();
  readonly computedOrder: ComputedEntry[] = [];
  readonly privateNodes: ReactiveNode[] = [];
  readonly members: ComponentVMBase[] = [];
  readonly reactions: Reaction[] = [];
  readonly className: string;
  /** The owner that registered this view-model as a member (R11.1). */
  owner: ComponentVMBase | null = null;
  activated = false;
  hooked = false;
  released = false;
  reactionScopeOpen = false;
  pausedFlag = false;
  /** A destruct rolled back to Constructed: the stopped reactions start again after the rollback (R13.2). */
  restartAfterRollback = false;
  /** Hooks were installed inside an unhooked `_onConstruct`: the walk and the starts run before Constructed. */
  tailPending = false;
  /** The member walk of the current construct has run: a later member is constructed at once (R11.4). */
  walkDone = false;
  /** A deferred inactive-write diagnostic is scheduled (R19.7). */
  inactiveCheckPending = false;
  containerSubscription: Subscription | null = null;
  #disposalStarted = false;
  #disposed = false;

  constructor(
    readonly vm: ComponentVMBase,
    lifecycle: VMState | null,
  ) {
    this.lifecycle = lifecycle ?? this;
    this.className = (vm.constructor as { readonly name?: string }).name ?? "ComponentVMBase";
  }

  /** Disposal started (R13.3 step 1): no reaction runs or starts, registrations are ignored, no activation. */
  get disposalStarted(): boolean {
    return this.#disposalStarted || (this.lifecycle !== this && this.lifecycle.disposalStarted);
  }

  /** Disposed is published (R13.3 step 5): the nodes accept no write and evaluate nothing; entries are dropped. */
  get disposing(): boolean {
    return this.#disposed || (this.lifecycle !== this && this.lifecycle.disposing);
  }

  get reactionsClosed(): boolean {
    return this.disposalStarted;
  }

  get paused(): boolean {
    return this.lifecycle.pausedFlag;
  }

  get label(): string {
    return `${this.className}(${safeName(this.vm)})`;
  }

  get target(): object {
    return this.vm;
  }

  /** Forgets a removed reaction (R12.10). */
  forgetReaction(reaction: Reaction): void {
    const at = this.reactions.indexOf(reaction);
    if (at >= 0) this.reactions.splice(at, 1);
  }

  markDisposalStarted(): void {
    this.#disposalStarted = true;
    this.reactionScopeOpen = false;
  }

  markDisposed(): void {
    this.markDisposalStarted();
    this.#disposed = true;
  }
}

function safeName(vm: ComponentVMBase): string {
  try {
    return vm.name;
  } catch {
    return "?";
  }
}

/** The status of a view-model, read without recording a dependency (library-internal reads, R5.7). */
export function rawStatus(vm: object): ConstructionStatus {
  return untracked(() => internals(vm).status);
}

const states = new WeakMap<ComponentVMBase, VMState>();

/** The state of `vm`, created on first use (no hooks yet). */
export function stateOf(vm: ComponentVMBase): VMState {
  const existing = states.get(vm);
  if (existing !== undefined) return existing;
  let identity: object = vm;
  try {
    identity = internals(vm)._ownershipIdentity;
  } catch {
    identity = vm;
  }
  const lifecycle = identity !== vm && identity instanceof ComponentVMBase ? stateOf(identity) : null;
  const state = new VMState(vm, lifecycle);
  states.set(vm, state);
  if (lifecycle !== null) lifecycle.dependents.push(state);
  return state;
}

/** The state of `vm` when it has one. */
export function existingState(vm: object): VMState | undefined {
  return vm instanceof ComponentVMBase ? states.get(vm) : undefined;
}

/** The members registered on `vm`, in registration order (walks, R11.6). */
export function membersOf(vm: ComponentVMBase): readonly ComponentVMBase[] {
  return states.get(vm)?.lifecycle.members ?? [];
}

// ── Announcing ───────────────────────────────────────────────────────────────────────────────────────────────

/** One announcement: one call to the unchanged dual-channel helper, hub first, then local (R8.3, spec 05 §2.3). */
export function announce(state: VMState, name: string): void {
  if (state.disposing) return;
  asGraphEmission(state.vm, name, () => {
    internals(state.vm)._notifyPropertyChanged(name);
  });
}

// ── Hooks ────────────────────────────────────────────────────────────────────────────────────────────────────

/** Installs the per-instance hooks at the first registration (and activates a VM constructed before it). */
export function ensureHooks(state: VMState): void {
  if (state.hooked) return;
  state.hooked = true;
  const life = state.lifecycle;
  if (life !== state) ensureHooks(life);
  else installLifecycleHooks(state);
  installActivationHook(state);
  installNativeTracking(state.vm);
  const status = rawStatus(life.vm);
  if (life === state) {
    if (status === ConstructionStatus.Constructed) {
      // A view-model constructed before its first registration: its reaction scope is open.
      life.reactionScopeOpen = true;
    } else if (status === ConstructionStatus.Constructing) {
      // Inside an unhooked _onConstruct (R11.4, fix round 1): members and reactions registered now join the
      // construct tail that runs before Constructed is published.
      life.tailPending = true;
      life.walkDone = false;
    }
  }
  // R4.2 a: a view-model constructed (or constructing) before its first registration activates now.
  if (status !== ConstructionStatus.Destructed && status !== ConstructionStatus.Disposed) activateState(state);
}

function installLifecycleHooks(state: VMState): void {
  const vm = state.vm;
  defineMethod(vm, "_onConstruct", function (this: object): void {
    constructSequence(state, () => callProto(this, "_onConstruct"));
  });
  defineMethod(vm, "_onDestruct", function (this: object): void {
    destructSequence(state, () => callProto(this, "_onDestruct"));
  });
  defineMethod(vm, "_onDispose", function (this: object): void {
    disposeTail(state, () => callProto(this, "_onDispose"));
  });
  defineMethod(vm, "_setStatus", function (this: object, status: ConstructionStatus): void {
    setStatusHook(state, this, status);
  });
}

function installActivationHook(state: VMState): void {
  const vm = state.vm;
  const getter = findDescriptor(vm, "propertyChanged")?.descriptor.get;
  if (getter !== undefined) {
    Object.defineProperty(vm, "propertyChanged", {
      configurable: true,
      enumerable: false,
      get(this: object): Observable<string> {
        const surface = getter.call(this) as Observable<string>;
        // R4.2 b: the first subscription to the VM-local surface activates the view-model.
        return defer(() => {
          activateState(state);
          return surface;
        });
      },
    });
  }
}

function setStatusHook(state: VMState, vm: object, status: ConstructionStatus): void {
  assertWritable("A lifecycle call");
  const current = rawStatus(vm);
  if (status === ConstructionStatus.Disposed) {
    let failed = false;
    let firstError: unknown;
    if (current !== ConstructionStatus.Disposed && !state.disposing) {
      try {
        // R13.3 steps 2 and 3: the reactions (unless the dispose call already ended them), then the members in
        // registration order, depth-first, while V still accepts writes and still announces (D2).
        startDisposalOf(state);
        disposeMembers(state);
      } catch (error) {
        failed = true;
        firstError = error;
      }
      // R13.3 step 4, R9.5 (fix round 2): the announcements of writes accepted before the disposal are delivered
      // while V can still announce, before its Disposed message (spec 05 §2.3: admitted before disposal).
      flushProducer(state);
    }
    // R13.3 step 5: from here the nodes accept no write and the queued entries are dropped (R9.5).
    state.markDisposed();
    for (const dependent of state.dependents) dependent.markDisposed();
    callProto(vm, "_setStatus", status);
    if (failed) throw firstError;
    return;
  }
  if (status === ConstructionStatus.Destructing && current === ConstructionStatus.Constructed) {
    // R13.2 step 2: the reactions pause and the scope closes before Destructing is published, so the
    // publication itself runs no effect, and a reaction registered during the destruct waits.
    state.pausedFlag = true;
    state.reactionScopeOpen = false;
  }
  if (status === ConstructionStatus.Constructing) state.walkDone = false;
  if (status === ConstructionStatus.Constructed && state.tailPending) runConstructTail(state, vm);
  const rollback = status === ConstructionStatus.Constructed && state.restartAfterRollback;
  const destructed =
    status === ConstructionStatus.Destructed &&
    (current === ConstructionStatus.Destructing || current === ConstructionStatus.Constructing);
  // R15.2: one status transition is one write; the prototype wrapper publishes it (library.ts).
  callProto(vm, "_setStatus", status);
  // R12.10 (fix round 2): the reactions registered during the construct that this transition ends are removed.
  if (destructed) removeConstructScoped(state);
  if (rollback) {
    state.restartAfterRollback = false;
    restartReactions(state);
  }
}

// ── The lifecycle sequences (R13.*) ──────────────────────────────────────────────────────────────────────────

function constructSequence(state: VMState, hook: () => void): void {
  state.tailPending = false;
  state.pausedFlag = false;
  state.walkDone = false;
  // Step 2: activation, after Constructing is published and before _onConstruct (R4.2 a).
  if (!state.disposalStarted && !state.activated) activateState(state);
  // Step 3.
  hook();
  if (state.disposalStarted) return;
  // Step 4: the member walk, registration order; members registered until now join it.
  walkMembers(state, true);
  state.walkDone = true;
  if (state.disposalStarted) return;
  // Step 5: reactions start in index order, each as a drain entry; a failure stops the started ones and fails the
  // construct.
  state.reactionScopeOpen = true;
  startConstructedReactions(state);
}

/** The construct tail of a view-model whose hooks were installed inside its own `_onConstruct` (L1d). */
function runConstructTail(state: VMState, vm: object): void {
  state.tailPending = false;
  try {
    walkMembers(state, true);
    state.walkDone = true;
    if (state.disposalStarted) return;
    state.reactionScopeOpen = true;
    startConstructedReactions(state);
  } catch (error) {
    // LIFE-014: the construct rolls back to Destructed and fails.
    state.reactionScopeOpen = false;
    try {
      callProto(vm, "_setStatus", ConstructionStatus.Destructed);
      removeConstructScoped(state);
    } catch {
      // The tail error stays primary.
    }
    throw error;
  }
}

/**
 * The destruct sequence (R13.2, fix round 2): the exact mirror of construct. Construct runs the hook, the members,
 * then the reactions; destruct stops the reactions, destructs the members in reverse, then runs the hook. A teardown
 * therefore runs while every member it used is still Constructed (LC1, LC2), and a member still sees its owner's
 * construct-time resources (L3).
 */
function destructSequence(state: VMState, hook: () => void): void {
  // Step 2 ran at the Destructing transition; repeat it for a destruct that bypassed the status hook.
  state.pausedFlag = true;
  state.reactionScopeOpen = false;
  try {
    // Step 3: constructed-kind reactions stop, last in first out (keyed drivers apply their disable rule).
    stopConstructedReactions(state);
    state.pausedFlag = false;
    if (state.disposalStarted) return;
    // Step 4: the members, in reverse registration order.
    walkMembers(state, false);
    if (state.disposalStarted) return;
    // Step 5.
    hook();
  } catch (error) {
    // A failure rolls V back to Constructed; the stopped reactions start again after the rollback is published.
    state.restartAfterRollback = true;
    throw error;
  }
}

function constructMember(member: ComponentVMBase): void {
  const status = rawStatus(member);
  if (status === ConstructionStatus.Disposed) return;
  if (status !== ConstructionStatus.Constructed && status !== ConstructionStatus.Constructing) member.construct();
  const after = rawStatus(member);
  // A background member stays Constructing; 3.30.0 cannot defer the owner's terminal status (README.md, limit 4).
  if (
    after !== ConstructionStatus.Constructed &&
    after !== ConstructionStatus.Constructing &&
    after !== ConstructionStatus.Disposed
  ) {
    throw new Error(`Member '${member.name}' did not reach Constructed`);
  }
}

function destructMember(member: ComponentVMBase): void {
  const status = rawStatus(member);
  if (status === ConstructionStatus.Disposed) return;
  if (status !== ConstructionStatus.Destructed && status !== ConstructionStatus.Destructing) member.destruct();
  const after = rawStatus(member);
  if (
    after !== ConstructionStatus.Destructed &&
    after !== ConstructionStatus.Destructing &&
    after !== ConstructionStatus.Disposed
  ) {
    throw new Error(`Member '${member.name}' did not reach Destructed`);
  }
}

/**
 * The member walk. Construct visits the members in registration order, including members registered during the
 * walk (R11.4); a member disposed during the walk has left the list (R11.5). Destruct visits a snapshot in reverse.
 */
function walkMembers(state: VMState, construct: boolean): void {
  if (construct) {
    const visited = new Set<ComponentVMBase>();
    for (let progressed = true; progressed; ) {
      progressed = false;
      for (const member of [...state.members]) {
        if (visited.has(member)) continue;
        visited.add(member);
        progressed = true;
        if (state.disposalStarted) return;
        constructMember(member);
      }
    }
    return;
  }
  const snapshot = [...state.members];
  for (let i = snapshot.length - 1; i >= 0; i -= 1) {
    const member = snapshot[i];
    if (member === undefined) continue;
    if (state.disposalStarted) return;
    destructMember(member);
  }
}

/** Starts the constructed-kind reactions in index order (R13.1 step 5). */
function startConstructedReactions(state: VMState): void {
  try {
    for (const reaction of [...state.reactions]) {
      if (reaction.alive || reaction.started || reaction.removed) continue;
      if (state.disposalStarted) return;
      reaction.start();
    }
  } catch (error) {
    // The reactions started so far stop in reverse order; the construct fails (LIFE-014).
    state.reactionScopeOpen = false;
    stopConstructedReactions(state);
    throw error;
  }
}

/** Stops the constructed-kind reactions, last in first out (R12.7). */
function stopConstructedReactions(state: VMState): void {
  const snapshot = [...state.reactions];
  for (let i = snapshot.length - 1; i >= 0; i -= 1) {
    const reaction = snapshot[i];
    if (reaction !== undefined && !reaction.alive && reaction.started) reaction.stop();
  }
}

/** After a destruct rolled back to Constructed: the stopped reactions start again, in index order (R13.2). */
function restartReactions(state: VMState): void {
  state.pausedFlag = false;
  state.reactionScopeOpen = true;
  for (const reaction of [...state.reactions]) {
    if (reaction.alive || reaction.started || reaction.removed || state.disposalStarted) continue;
    try {
      reaction.start();
    } catch (error) {
      // A rollback cannot fail: a failing restart goes to the stream-fed route.
      reportStreamFed(error);
    }
  }
}

/** R12.10: the reactions registered while V was constructing end when V next publishes Destructed. */
function removeConstructScoped(state: VMState): void {
  const snapshot = [...state.reactions];
  for (let i = snapshot.length - 1; i >= 0; i -= 1) {
    const reaction = snapshot[i];
    if (reaction !== undefined && reaction.scope === "construct") reaction.remove();
  }
}

/**
 * R13.3 steps 1 and 2 (fix round 2), called by every VMx dispose before it disposes anything (library.ts): disposal
 * starts, and V's reactions that started (constructed-kind and alive) are torn down, last in first out, while the
 * members and children they used are still alive (LC3). Idempotent.
 */
export function startDisposal(vm: ComponentVMBase): void {
  const state = states.get(vm);
  if (state === undefined) return;
  const life = state.lifecycle;
  if (life.disposalStarted || rawStatus(life.vm) === ConstructionStatus.Disposed) return;
  startDisposalOf(life);
}

function startDisposalOf(state: VMState): void {
  if (state.disposalStarted) return;
  state.markDisposalStarted();
  for (const dependent of state.dependents) dependent.markDisposalStarted();
  state.containerSubscription?.unsubscribe();
  state.containerSubscription = null;
  const snapshot = [...state.reactions];
  for (let i = snapshot.length - 1; i >= 0; i -= 1) snapshot[i]?.stop();
}

/** R13.3 step 3: the members, in registration order, depth-first (best effort, spec 02 §7.1). */
function disposeMembers(state: VMState): void {
  disposeBestEffort([...state.members].map((member) => () => member.dispose()));
}

/**
 * R11.5 (fix round 2): a member that reaches Disposed leaves its owner's member list, so a navigation shell or a
 * keyed slot that disposes the member it replaces keeps no reference to it (DD1).
 */
export function memberDisposed(vm: ComponentVMBase): void {
  const state = states.get(vm);
  const owner = state?.owner ?? null;
  if (state === undefined || owner === null) return;
  const ownerState = states.get(owner)?.lifecycle;
  if (ownerState !== undefined) {
    const at = ownerState.members.indexOf(vm);
    if (at >= 0) ownerState.members.splice(at, 1);
  }
  state.owner = null;
}

function disposeTail(state: VMState, hook: () => void): void {
  try {
    // Step 6.
    hook();
  } finally {
    // Reactions that started after the teardown of step 2 (none can; a safety net) end now.
    for (const reaction of [...state.reactions].reverse()) reaction.stop();
    // Step 7: the graph release. Step 8 (own() resources, the helper commands) follows in VMx.
    releaseGraph(state);
  }
}

/** Removes every edge to and from the view-model's nodes and frames; drops its functions (R17.1). */
export function releaseGraph(state: VMState): void {
  if (state.released) return;
  state.released = true;
  for (const entry of state.published.values()) {
    releaseNode(entry.node);
    if (entry.kind === "computed") releaseNode(entry.invalidation);
  }
  for (const node of state.privateNodes) releaseNode(node);
  for (const reaction of [...state.reactions]) reaction.release();
  state.reactions.length = 0;
  state.containerSubscription?.unsubscribe();
  state.containerSubscription = null;
  releaseAnnouncements(state.vm);
  for (const dependent of state.dependents) releaseGraph(dependent);
}

// ── Activation (R4.*) ────────────────────────────────────────────────────────────────────────────────────────

function* containerChildren(vm: ComponentVMBase): Iterable<ComponentVMBase> {
  if (Symbol.iterator in vm) {
    for (const child of vm as unknown as Iterable<unknown>) {
      if (child instanceof ComponentVMBase) yield child;
    }
    return;
  }
  const components = (vm as unknown as { readonly components?: unknown }).components;
  if (typeof components === "function") {
    for (const child of (components as () => readonly unknown[]).call(vm)) {
      if (child instanceof ComponentVMBase) yield child;
    }
  }
}

function watchContainer(state: VMState): void {
  if (state.containerSubscription !== null) return;
  const changes = (state.vm as unknown as { readonly collectionChanged?: unknown }).collectionChanged;
  if (!isObservable(changes)) return;
  // R4.2 c: a child added to an activated container activates.
  state.containerSubscription = (changes as Observable<CollectionChangedEvent>).subscribe((event) => {
    if (state.disposalStarted) return;
    const items = event.action === "reset" ? [...containerChildren(state.vm)] : event.newItems;
    for (const item of items) if (item instanceof ComponentVMBase) activateQuietly(stateOf(item));
  });
}

/** R3.12: each registered name's own property must still be the VMx accessor. */
function checkShadowing(state: VMState): void {
  for (const [name, entry] of state.published) {
    const own = Object.getOwnPropertyDescriptor(state.vm, name);
    if (own === undefined || own.get !== entry.get) {
      throw new Error(`${state.label}: ${name} is shadowed by a class field; declare it with declare`);
    }
  }
}

/** Activates a member or child; its own usage error surfaces at its own trigger (its construct). */
function activateQuietly(state: VMState): void {
  try {
    activateState(state);
  } catch {
    // The child's activation is retried, and fails loudly, at its own construct.
  }
}

/**
 * Activates the view-model now (R4.1). Idempotent; a no-op once its disposal started (R4.3). Fix round 1:
 * activation is atomic. The shadowing check runs first, and a failure leaves the view-model unactivated, so every
 * later trigger raises the same usage error.
 */
export function activateState(state: VMState): void {
  if (state.activated && state.lifecycle.activated) return;
  // Activation is a library operation: it runs untracked (R5.7).
  untracked(() => activateUntracked(state));
}

function activateUntracked(state: VMState): void {
  if (state.lifecycle !== state && !state.lifecycle.activated) activateState(state.lifecycle);
  if (state.activated || state.disposalStarted) return;
  checkShadowing(state);
  state.activated = true;
  let cascadeFailed = false;
  let cascadeError: unknown;
  const cascade = (target: VMState): void => {
    try {
      activateState(target);
    } catch (error) {
      // The rest of this activation still runs; the first usage error of the cascade is raised at its end.
      if (!cascadeFailed) {
        cascadeFailed = true;
        cascadeError = error;
      }
    }
  };
  asEvaluation(() => {
    // Step 1: members, then materialized container children, depth-first.
    for (const member of [...state.members]) cascade(stateOf(member));
    for (const child of [...containerChildren(state.vm)]) cascade(stateOf(child));
    watchContainer(state);
    for (const dependent of state.dependents) cascade(dependent);
    // Step 3: baselines, in index order, silent.
    for (const entry of state.computedOrder) takeBaseline(entry);
    // Step 4: alive reactions.
    for (const reaction of [...state.reactions]) if (reaction.alive && !reaction.started) reaction.start();
  });
  // Step 5: the development probe, on a later task (R19.2, fix round 1).
  if (developmentDiagnostics()) {
    later(() => {
      if (developmentDiagnostics() && !state.disposalStarted) probeUnpublishedGetters(state);
    });
  }
  if (cascadeFailed) throw cascadeError;
}

/** The baseline of one registered computed of an activated view-model. */
export function takeBaseline(entry: ComputedEntry): void {
  entry.node.eagerPublished = true;
  baseline(entry.node);
}

/**
 * R3.13 (fix round 2, MS2): state registered on an activated view-model (in `_onConstruct`, which runs after
 * activation, R13.1) is one write: every registered computed of the view-model re-evaluates, and those that changed
 * are announced. Readers in other view-models that read the name before it existed are not refreshed, so development
 * reports the late registration once per class.
 */
export function noteLateState(state: VMState, keys: readonly string[]): void {
  if (!state.activated || state.disposalStarted) return;
  reportOnce(
    `late-state:${state.className}`,
    `${state.className}: state ${keys.join(", ")} registered after activation; readers in other view-models that ` +
      "read it before are not refreshed. Register state in the constructor",
  );
  if (state.computedOrder.length === 0) return;
  bumpVersions(
    state.computedOrder.map((entry) => entry.invalidation),
    false,
  );
}

/** R19.2: every public getter of the VM's own classes that reads reactive state but is not registered. */
function probeUnpublishedGetters(state: VMState): void {
  const vm = state.vm;
  let proto = Object.getPrototypeOf(vm) as object | null;
  while (proto !== null && !libraryPrototypes.has(proto)) {
    const className = (proto as { readonly constructor?: { readonly name?: string } }).constructor?.name ?? "?";
    for (const name of Object.getOwnPropertyNames(proto)) {
      const getter = Object.getOwnPropertyDescriptor(proto, name)?.get;
      if (getter === undefined || state.published.has(name) || isLibraryMember(vm, name)) continue;
      const result = probe(() => getter.call(vm) as unknown);
      if (result.recorded.length > 0) {
        reportOnce(
          `probe:${className}.${name}`,
          `${className}.${name} reads reactive state but is not published; register it with computed("${name}")`,
        );
      }
    }
    proto = Object.getPrototypeOf(proto) as object | null;
  }
}

/**
 * R19.7 (fix round 1): a registered write on a view-model that has registered computeds but is not activated is
 * reported once per class if the view-model is still not activated on a later task: its computeds were not
 * announced to hub observers (R4.5).
 */
export function noteInactiveWrite(state: VMState): void {
  if (state.activated || state.computedOrder.length === 0 || state.inactiveCheckPending) return;
  if (!developmentDiagnostics()) return;
  state.inactiveCheckPending = true;
  later(() => {
    state.inactiveCheckPending = false;
    if (state.activated || state.disposalStarted || !developmentDiagnostics()) return;
    const names = state.computedOrder.map((entry) => entry.name).join(", ");
    reportOnce(
      `inactive:${state.className}`,
      `${state.className}: registered state changed while the view-model was not activated, so its computeds ` +
        `(${names}) were not announced; construct, bind, own or contain it, or call activate()`,
    );
  });
}

// ── Reading registered computeds (R3.9, R3.10) ───────────────────────────────────────────────────────────────

const staleChecks: [VMState, ComputedEntry][] = [];
let staleTimer = false;

/** R19.1 (fix round 1): the staleness check of a consumer read runs on a later task, never inside the read. */
function scheduleStalenessCheck(state: VMState, entry: ComputedEntry): void {
  if (entry.checkPending) return;
  entry.checkPending = true;
  staleChecks.push([state, entry]);
  if (staleTimer) return;
  staleTimer = true;
  later(runStalenessChecks);
}

function runStalenessChecks(): void {
  staleTimer = false;
  for (const [state, entry] of staleChecks.splice(0)) {
    entry.checkPending = false;
    const node = entry.node;
    if (!developmentDiagnostics() || state.disposing || !isMemoized(node)) continue;
    const memoized = node.value;
    const fresh = probe(() => entry.protoGet.call(state.vm));
    if (!fresh.ok) continue;
    // Fix round 2 (MM1, MM2): structural equality compares functions by source and handles back references; at
    // its depth limit it counts as equal, so the check reports nothing when it cannot decide.
    if (compareValues(node.equals, memoized, fresh.value, false)) continue;
    if (structurallyEqual(fresh.value, memoized, { atLimit: true })) continue;
    reportOnce(
      `stale:${state.className}.${entry.name}`,
      `${state.className}.${entry.name} changed without a tracked dependency`,
    );
  }
}

/** A plain call of a registered getter (before activation, or a never-evaluated node after disposal). */
function plainRead(state: VMState, entry: ComputedEntry): unknown {
  // R16 (fix round 2, CC1): a plain getter read during its own evaluation is a cycle, as it is after activation.
  if (entry.plainDepth > 0) {
    throw new ReactiveCycleError(`${state.label}.${entry.name} was read during its own evaluation`);
  }
  entry.plainDepth += 1;
  try {
    return entry.protoGet.call(state.vm);
  } finally {
    entry.plainDepth -= 1;
  }
}

export function readComputed(state: VMState, entry: ComputedEntry): unknown {
  const node = entry.node;
  if (state.disposing || node.released) {
    // R5.6: the last value; a node that was never evaluated reads through its getter (R5.6, fix round 2).
    if (node.evaluated || node.hasError) return readDerived(node, false);
    return plainRead(state, entry);
  }
  if (!state.activated) {
    // R3.10: a plain getter in the caller's frame; the invalidation node lets invalidate() reach the readers.
    readSource(entry.invalidation);
    return plainRead(state, entry);
  }
  const consumerRead = isConsumerRead();
  const value = readDerived(node);
  if (consumerRead && developmentDiagnostics() && isMemoized(node)) scheduleStalenessCheck(state, entry);
  return value;
}

// ── Members (R11.*) ──────────────────────────────────────────────────────────────────────────────────────────

function ownerOf(vm: ComponentVMBase): ComponentVMBase | null {
  const owner = states.get(vm)?.owner ?? null;
  if (owner !== null) return owner;
  const parent = internals(vm)._parent as { readonly owner?: unknown } | null;
  return parent !== null && parent.owner instanceof ComponentVMBase ? parent.owner : null;
}

function guardContainerAdd(vm: ComponentVMBase, memberState: VMState, ownerName: string): void {
  const identity = internals(vm)._ownershipIdentity as { _ownershipInProgress?: boolean };
  let stored = identity._ownershipInProgress === true;
  // Containers refuse a VM that has an owner (R11.3): 3.30.0's parent transfer and aggregate slots read this flag
  // before they change anything, so the refusal happens before any mutation.
  Object.defineProperty(identity, "_ownershipInProgress", {
    configurable: true,
    enumerable: true,
    get(): boolean {
      if (memberState.owner !== null) {
        throw new Error(`Cannot add '${vm.name}' to a container: it is a member of '${ownerName}'`);
      }
      return stored;
    },
    set(value: boolean): void {
      stored = value;
    },
  });
}

/** Registers `vm` as a member of the owner (R11.1 to R11.5). Runs untracked (R5.7). */
export function addMember(ownerState: VMState, vm: ComponentVMBase): ComponentVMBase {
  assertWritable("member()");
  return untracked(() => registerMember(ownerState, vm));
}

function registerMember(ownerState: VMState, vm: ComponentVMBase): ComponentVMBase {
  const owner = ownerState.lifecycle;
  const ownerVM = owner.vm;
  if (!(vm instanceof ComponentVMBase)) throw new TypeError("member() takes a VMx view-model");
  const memberIdentity = internals(vm)._ownershipIdentity;
  if (vm === ownerVM || memberIdentity === internals(ownerVM)._ownershipIdentity) {
    throw new Error(`${owner.label}: a view-model cannot be its own member`);
  }
  if (owner.members.includes(vm)) return vm;
  const ownerStatus = rawStatus(ownerVM);
  if (owner.disposalStarted || ownerStatus === ConstructionStatus.Disposed) {
    // R11.4: disposing or disposed owner: the member is disposed at once and returned.
    vm.dispose();
    return vm;
  }
  // R11.5 (fix round 2): a disposed view-model registers nothing; it is returned as it is.
  if (rawStatus(vm) === ConstructionStatus.Disposed || states.get(vm)?.disposalStarted === true) return vm;
  const memberState = stateOf(vm);
  if (memberState.owner !== null) {
    throw new Error(`Cannot register '${vm.name}' as a member of ${owner.label}: it already has an owner`);
  }
  if (internals(vm)._parent !== null) {
    throw new Error(`Cannot register '${vm.name}' as a member of ${owner.label}: it has a container parent`);
  }
  for (let cursor: ComponentVMBase | null = ownerVM; cursor !== null; cursor = ownerOf(cursor)) {
    if (internals(cursor)._ownershipIdentity === memberIdentity) {
      throw new Error(`Cannot register '${vm.name}' as a member of ${owner.label}: it would close an owner cycle`);
    }
  }
  memberState.owner = ownerVM;
  owner.members.push(vm);
  guardContainerAdd(vm, memberState, safeName(ownerVM));
  installNativeTracking(vm);
  // R4.2 c: a member of an activated owner activates.
  if (owner.activated) activateQuietly(memberState);
  // R11.4 (fix round 1): a Constructed owner, or a Constructing owner whose member walk already ran (a
  // registration from a reaction start), constructs the member at once. Before the walk the member joins it.
  if (
    ownerStatus === ConstructionStatus.Constructed ||
    (ownerStatus === ConstructionStatus.Constructing && owner.walkDone)
  ) {
    vm.construct();
  }
  return vm;
}

// ── Reactions (R12.*) ────────────────────────────────────────────────────────────────────────────────────────

/**
 * Registers a reaction on the lifecycle state (R12.2) in its registration scope (R12.10, fix round 2), and starts
 * it when its scope is open. Returns the reaction, or null when the registration is ignored.
 */
export function addReaction(state: VMState, reaction: Reaction): Reaction | null {
  const life = state.lifecycle;
  if (life.disposalStarted) return null;
  const run = currentRun();
  if (run !== null && run.owner === life && !run.removed) {
    // Registered by a run of another reaction of this view-model: it belongs to that run (RR5).
    reaction.scope = "run";
    reaction.parent = run;
    run.children.push(reaction);
  } else if (!reaction.alive && rawStatus(life.vm) === ConstructionStatus.Constructing) {
    // Registered while the view-model constructs (in _onConstruct): it belongs to that construct (LC7).
    reaction.scope = "construct";
  }
  life.reactions.push(reaction);
  if (reaction.alive) {
    if (life.activated) reaction.start();
  } else if (life.reactionScopeOpen) {
    reaction.start();
  }
  return reaction;
}

// ── Inspection (R19.*) ───────────────────────────────────────────────────────────────────────────────────────

/** The nodes read by the last evaluation of `vm[name]` (R19.4, informative). */
export function explainState(vm: ComponentVMBase, name: string): readonly { readonly owner: object; readonly name: string }[] {
  const entry = states.get(vm)?.published.get(name);
  if (entry === undefined || entry.kind !== "computed") return [];
  return entry.node.sources
    .filter((source) => source.kind !== "invalidation")
    .map((source) => ({ owner: source.owner?.target ?? source.subject ?? source, name: source.name }));
}

/** `Class(name)` of a view-model or object, for messages. */
export function labelOf(target: object): string {
  return existingState(target)?.label ?? describeObject(target);
}
