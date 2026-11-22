/**
 * The reaction kinds (R12.*, R14.*): effect, reaction, whileConstructed and the keyed driver.
 */
import { AsyncResourceStatus, type AsyncResourceVM, type OwnedResource } from "@thekaveh/vmx";
import type { Subscription } from "rxjs";
import { reportOnce, reportStreamFed } from "./diagnostics.js";
import { type Equality, shallowEqual, structurallyEqual } from "./equality.js";
import { compareValues, runFrame, untracked } from "./graph.js";
import { localSurface } from "./interop.js";
import { Reaction, type ReactionOwner } from "./reaction.js";
import type { FollowKeyOptions, ReactionOptions } from "./types.js";
import { releaseResource } from "./util.js";

const UNSET: unique symbol = Symbol("unset");
type Maybe<T> = T | typeof UNSET;

function isThenable(value: unknown): value is PromiseLike<unknown> {
  return (
    (typeof value === "object" || typeof value === "function") &&
    value !== null &&
    typeof (value as { readonly then?: unknown }).then === "function"
  );
}

/** effect(fn): runs `fn` in a frame at its start and again when a dependency changes (R12.3). */
export class EffectReaction extends Reaction {
  #fn: (() => void | (() => void)) | null;
  #cleanup: (() => void) | null = null;

  constructor(owner: ReactionOwner, fn: () => void | (() => void)) {
    super(owner, false, "effect");
    this.#fn = fn;
  }

  protected onStart(): void {
    this.#execute();
  }

  protected onRun(): void {
    this.#runCleanup();
    try {
      this.#execute();
    } catch (error) {
      // An effect re-run that throws is reported; the effect stays active with the reads it made (R16).
      reportStreamFed(error);
    }
  }

  protected onStop(): void {
    this.#runCleanup();
  }

  protected dropReferences(): void {
    this.#fn = null;
    this.#cleanup = null;
  }

  #execute(): void {
    const fn = this.#fn;
    if (fn === null) return;
    // An effect run is the one frame that may write.
    const result: unknown = runFrame(this, fn, { evaluation: false });
    if (isThenable(result)) {
      // R12.3 (fix round 2, MS1): an effect runs synchronously. A Promise-returning function is tracked only up to
      // its first await, its promise is no cleanup, and its rejection goes to the stream-fed route.
      reportOnce(
        `async-effect:${this.owner.className}`,
        `${this.owner.className}: an effect returned a Promise; reads after its first await are not tracked. ` +
          "Read every input before the first await, or use keyedResource() or asyncRelayCommand()",
      );
      result.then(undefined, (error: unknown) => {
        reportStreamFed(error);
      });
      this.#cleanup = null;
      return;
    }
    const cleanup = typeof result === "function" ? (result as () => void) : null;
    if (!this.started && cleanup !== null) {
      // The run stopped or removed its own reaction (it disposed its view-model, or called its handle): the cleanup
      // it returned runs at once, so every cleanup runs exactly once (test R3 of attack-r1-reentrancy).
      try {
        cleanup();
      } catch {
        // Cleanup failures are isolated and swallowed (R12.8).
      }
      return;
    }
    this.#cleanup = cleanup;
  }

  #runCleanup(): void {
    const cleanup = this.#cleanup;
    this.#cleanup = null;
    if (cleanup === null) return;
    try {
      cleanup();
    } catch {
      // Cleanup failures are isolated and swallowed (R12.8).
    }
  }
}

/** reaction(select, handler, options) (R12.4, R12.5). */
export class ValueReaction<T> extends Reaction {
  #select: (() => T) | null;
  #handler: ((value: T, previous: T) => void) | null;
  readonly #equals: Equality<T>;
  readonly #immediate: boolean;
  #reference: Maybe<T> = UNSET;
  #delivered: Maybe<T> = UNSET;
  /** An immediate start whose select threw: the first successful run makes the start's delivery (R12.4). */
  #immediatePending = false;

  constructor(
    owner: ReactionOwner,
    select: () => T,
    handler: (value: T, previous: T) => void,
    options: ReactionOptions<T> | undefined,
  ) {
    super(owner, options?.alive === true, options?.alive === true ? "alive-reaction" : "reaction");
    this.#select = select;
    this.#handler = handler;
    this.#equals = options?.equals ?? Object.is;
    // An alive reaction has no immediate run (R12.5).
    this.#immediate = options?.immediate === true && options.alive !== true;
  }

  protected onStart(): void {
    let value: T;
    try {
      value = this.#evaluate();
    } catch (error) {
      // A select that throws is reported; the next successful run takes the baseline, and an immediate reaction
      // makes its start delivery then (R16, R12.4).
      this.#reference = UNSET;
      this.#immediatePending = this.#immediate;
      reportStreamFed(error);
      return;
    }
    this.#reference = value;
    this.#immediatePending = false;
    if (this.#immediate) this.#deliverStart(value);
  }

  protected onRun(): void {
    let value: T;
    try {
      value = this.#evaluate();
    } catch (error) {
      reportStreamFed(error);
      return;
    }
    const reference = this.#reference;
    if (reference === UNSET) {
      this.#reference = value;
      if (!this.#immediatePending) return;
      this.#immediatePending = false;
      try {
        this.#deliverStart(value);
      } catch (error) {
        reportStreamFed(error);
      }
      return;
    }
    // The equality is user code with its own context (R6.10, fix round 2).
    if (compareValues(this.#equals as Equality<unknown>, reference, value)) return;
    // The last delivered value is updated first, so a throwing handler does not loop (R16).
    this.#reference = value;
    this.#delivered = value;
    try {
      this.#call(value, reference);
    } catch (error) {
      reportStreamFed(error);
    }
  }

  protected onStop(): void {
    // Changes while stopped are not delivered: a restart takes a new baseline (R12.4).
    this.#reference = UNSET;
    this.#immediatePending = false;
  }

  /** The start delivery of an immediate reaction: `previous` is the last value delivered before, or `value`. */
  #deliverStart(value: T): void {
    const previous = this.#delivered === UNSET ? value : this.#delivered;
    this.#delivered = value;
    this.#call(value, previous);
  }

  protected dropReferences(): void {
    this.#select = null;
    this.#handler = null;
  }

  #evaluate(): T {
    const select = this.#select;
    if (select === null) throw new Error("released reaction");
    return runFrame(this, select, { evaluation: true });
  }

  #call(value: T, previous: T): void {
    const handler = this.#handler;
    if (handler === null) return;
    untracked(() => handler(value, previous));
  }
}

/** whileConstructed(setup): `setup` runs untracked at each start; its resource is released at the stop (R12.6). */
export class WhileConstructedReaction extends Reaction {
  #setup: (() => OwnedResource | void) | null;
  #resource: OwnedResource | null = null;

  constructor(owner: ReactionOwner, setup: () => OwnedResource | void) {
    super(owner, false, "whileConstructed");
    this.#setup = setup;
  }

  protected onStart(): void {
    const setup = this.#setup;
    if (setup === null) return;
    const resource = untracked(setup);
    // A setup that stopped or removed its own reaction: its resource is released at once.
    if (!this.started) releaseResource(resource ?? null);
    else this.#resource = resource ?? null;
  }

  protected onRun(): void {
    // A setup records no dependency, so it never runs again before its stop.
  }

  protected onStop(): void {
    const resource = this.#resource;
    this.#resource = null;
    releaseResource(resource);
  }

  protected dropReferences(): void {
    this.#setup = null;
  }
}

interface Selection<K> {
  /** The effective enable E: the driver is evaluated, `enabled()` is true and a key exists (R14.3). */
  readonly enabled: boolean;
  /** The key of this evaluation, or the previous one when `key()` threw (rule 6). */
  readonly key: Maybe<K>;
}

/**
 * The keyed driver of a resource (R14.*): a constructed-kind reaction with `startedKey` and `outdated`.
 *
 * Fix round 1 (R14.4): `outdated` means "a load in flight was cancelled by the disable rule". A key that
 * changes while disabled does not set it: enabling compares `key()` with `startedKey`.
 *
 * Fix round 2 (R14.3, R14.4, R19.8):
 * - E also needs a key: while `key()` has never returned one (it threw at every evaluation), the driver is disabled,
 *   and the first valid key is E turning true (KD1).
 * - Any entry into Loading clears `outdated`, whoever started the load (KD2).
 * - Rule 2 compares `key()` with `startedKey`, the key of the last load that started, so a key written while that
 *   load starts (by an observer of the Loading message) does not load the same key again (KD3).
 * - R19.8 reports a reload whose key is structurally equal to `startedKey` under any equality (KD4).
 */
export class KeyedDriver<K> extends Reaction {
  readonly #resource: AsyncResourceVM<unknown>;
  #key: (() => K) | null;
  #enabled: (() => boolean) | null;
  readonly #autoLoad: boolean;
  readonly #cancelWhenDisabled: boolean;
  readonly #equals: Equality<K>;
  readonly #defaultEquals: boolean;
  #startedKey: Maybe<K> = UNSET;
  #everStarted: boolean;
  #outdated = false;
  #lastKey: Maybe<K> = UNSET;
  #effective = false;
  #keyFailed = false;
  #enabledFailed = false;
  #observation: Subscription | null;

  constructor(owner: ReactionOwner, resource: AsyncResourceVM<unknown>, options: FollowKeyOptions<K>) {
    super(owner, false, "keyedDriver");
    this.#resource = resource;
    this.#key = options.key;
    this.#enabled = options.enabled ?? null;
    this.#autoLoad = options.autoLoad === true;
    this.#cancelWhenDisabled = options.cancelWhenDisabled !== false;
    this.#equals = options.equals ?? Object.is;
    this.#defaultEquals = options.equals === undefined;
    this.#everStarted = untracked(() => resource.state.status) !== AsyncResourceStatus.Idle;
    // R14.3: every entry into Loading, whoever started the load, records startedKey (key() read untracked) and,
    // fix round 2, clears outdated.
    this.#observation = localSurface(resource).subscribe((name) => {
      if (name !== "state") return;
      if (untracked(() => resource.state.status) !== AsyncResourceStatus.Loading) return;
      this.#everStarted = true;
      this.#outdated = false;
      const key = this.#key;
      if (key === null) return;
      try {
        this.#startedKey = untracked(key);
      } catch {
        // A throwing key() keeps the previous started key (R14.4 rule 6).
      }
    });
  }

  /** keyedResource's loader reports the exact key of the load that starts (R14.1, R14.3). */
  noteLoadKey(key: K): void {
    this.#everStarted = true;
    this.#outdated = false;
    this.#startedKey = key;
  }

  protected onStart(): void {
    const selection = this.#select();
    this.#effective = selection.enabled;
    // Rule 1: E turns true at the driver's start.
    if (selection.enabled && selection.key !== UNSET) this.#onEnable(selection.key);
  }

  protected onRun(): void {
    const wasEnabled = this.#effective;
    const selection = this.#select();
    this.#effective = selection.enabled;
    const key = selection.key;
    if (!wasEnabled && selection.enabled && key !== UNSET) {
      this.#onEnable(key); // rule 1
    } else if (wasEnabled && selection.enabled && key !== UNSET) {
      // Rule 2 (fix round 2): the key differs from the key of the last load that started (latest start wins).
      if (this.#everStarted && this.#differs(key)) this.#startLoad(key, true);
    } else if (wasEnabled && !selection.enabled) {
      this.#onDisable(); // rule 3
    }
    // Rule 4: a key change while disabled is not remembered; rule 1 compares with startedKey.
  }

  protected onStop(): void {
    // Rule 3 at the driver's stop (destruct step 3).
    if (this.#effective) {
      this.#effective = false;
      this.#onDisable();
    }
  }

  protected dropReferences(): void {
    this.#key = null;
    this.#enabled = null;
    this.#observation?.unsubscribe();
    this.#observation = null;
  }

  /** True when `key` differs from the key of the last load that started, by the driver's equality. */
  #differs(key: K): boolean {
    const started = this.#startedKey;
    if (started === UNSET) return true;
    return !compareValues(this.#equals as Equality<unknown>, started, key);
  }

  /** Evaluates `enabled()` and `key()` in the driver's frame (R14.3). */
  #select(): Selection<K> {
    const key = this.#key;
    const enabled = this.#enabled;
    return runFrame(
      this,
      (): Selection<K> => {
        let isEnabled = true;
        if (enabled !== null) {
          try {
            isEnabled = enabled() === true;
            this.#enabledFailed = false;
          } catch (error) {
            // A throwing enabled() reads as false (R14.3); reported once per transition into error.
            isEnabled = false;
            if (!this.#enabledFailed) reportStreamFed(error);
            this.#enabledFailed = true;
          }
        }
        let current: Maybe<K> = UNSET;
        if (key !== null) {
          try {
            current = key();
            this.#keyFailed = false;
          } catch (error) {
            // A throwing key() keeps the previous key; reported once per transition into error (rule 6).
            if (!this.#keyFailed) reportStreamFed(error);
            this.#keyFailed = true;
          }
        }
        if (current !== UNSET) this.#lastKey = current;
        const kept = this.#lastKey;
        // Fix round 2 (KD1): without any key, the driver is disabled; the first valid key enables it.
        return { enabled: isEnabled && kept !== UNSET, key: kept };
      },
      { evaluation: true },
    );
  }

  #onEnable(key: K): void {
    if (!this.#everStarted) {
      if (this.#autoLoad) this.#startLoad(key, false);
      return;
    }
    const keyDiffers = this.#differs(key);
    const status = untracked(() => this.#resource.state.status);
    const error = status === AsyncResourceStatus.Error;
    if (this.#outdated || keyDiffers || error) this.#startLoad(key, keyDiffers && !this.#outdated && !error);
  }

  #onDisable(): void {
    const status = untracked(() => this.#resource.state.status);
    if (status === AsyncResourceStatus.Loading && this.#cancelWhenDisabled) {
      this.#resource.cancel();
      this.#outdated = true;
    }
  }

  /**
   * Development diagnostic (R19.8): a reload caused only by a key difference, while the new key is equal to the key
   * of the last load in structure. Behavior does not change; the report names the fix.
   */
  #reportEqualKey(next: K): void {
    const previous = this.#startedKey;
    if (previous === UNSET || typeof next !== "object" || next === null) return;
    if (this.#defaultEquals && shallowEqual(previous, next)) {
      reportOnce(
        `keyed:${this.owner.className}`,
        `${this.owner.className}: a keyed resource reloaded because key() returned a new object that is ` +
          "shallow-equal to the previous key; pass equals: shallowEqual",
      );
      return;
    }
    if (structurallyEqual(previous, next)) {
      reportOnce(
        `keyed-structural:${this.owner.className}`,
        `${this.owner.className}: a keyed resource reloaded with a key that is structurally equal to the key of ` +
          "its last load, because its equals reported a difference; pass an equality that compares the nested " +
          "values, or a primitive key",
      );
    }
  }

  /** Rule 5: `load()` when Idle, `reload()` otherwise; the promise is observed. */
  #startLoad(key: K, byKey: boolean): void {
    if (byKey) this.#reportEqualKey(key);
    this.#outdated = false;
    const resource = this.#resource;
    const idle = untracked(() => resource.state.status) === AsyncResourceStatus.Idle;
    const pending = idle ? resource.load() : resource.reload();
    pending.catch((error: unknown) => {
      reportStreamFed(error);
    });
  }
}
