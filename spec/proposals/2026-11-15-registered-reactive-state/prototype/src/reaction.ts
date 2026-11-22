/**
 * The reaction base (R12.*): a frame with a start, runs and a stop.
 *
 * Fix round 2 (R12.10): a reaction has a registration scope. A reaction registered during a run of
 * another reaction of the same view-model (its start, an effect run, a reaction handler, a setup) belongs to that
 * run: it is removed when that reaction runs again, stops or is removed (RR5). A reaction registered while its
 * view-model is constructing, outside a reaction run (in `_onConstruct`), belongs to that construct: it is removed
 * when the view-model next publishes Destructed (LC7). Every other reaction lives until its view-model's disposal,
 * or until the handle that its registration returned removes it.
 */
import {
  forgetFrame,
  Frame,
  nextIndex,
  type NodeOwner,
  type QueueEntry,
  releaseConsumer,
  runAsDrainEntry,
} from "./graph.js";

/** The owner of a reaction: a view-model state (R12.*, R13.*). */
export interface ReactionOwner extends NodeOwner {
  /** From the Destructing transition to the stop (or the rollback): constructed-kind reactions do not run (R13.2). */
  readonly paused: boolean;
  /** Disposal started: no reaction of the owner runs, starts or registers again (R13.3 step 1). */
  readonly reactionsClosed: boolean;
  /** The view-model's class name, for once-per-class diagnostics. */
  readonly className: string;
  /** Forgets a removed reaction (R12.10). */
  forgetReaction(reaction: Reaction): void;
}

/** The registration scope of a reaction (R12.10). */
export type ReactionScope = "instance" | "construct" | "run";

/** The reactions whose start or run is in progress, innermost last. */
const runs: Reaction[] = [];

/** The innermost reaction whose start or run is in progress, or null. */
export function currentRun(): Reaction | null {
  return runs[runs.length - 1] ?? null;
}

export abstract class Reaction extends Frame {
  readonly frameKind = "reaction";
  readonly index = nextIndex();
  started = false;
  dirty = false;
  scope: ReactionScope = "instance";
  /** The reaction whose run registered this one (scope "run"). */
  parent: Reaction | null = null;
  readonly children: Reaction[] = [];
  removed = false;

  constructor(
    readonly owner: ReactionOwner,
    /** An alive reaction runs in every status but Disposed (R12.5). */
    readonly alive: boolean,
    readonly kind: string,
  ) {
    super();
  }

  /** Started and its owner's disposal has not started (R12.1, R13.3 step 1). */
  get active(): boolean {
    return this.started && !this.owner.reactionsClosed && !this.removed;
  }

  /** A paused constructed-kind reaction is marked dirty but does not run (R13.2 step 2). */
  get suspended(): boolean {
    return !this.alive && this.owner.paused;
  }

  get key(): string {
    return `${this.owner.label}:${this.kind}#${String(this.index)}`;
  }

  affected(): QueueEntry | null {
    if (!this.active) return null;
    this.dirty = true;
    if (this.suspended) return null;
    return this.entry();
  }

  /** A run entry: dropped when inactive or suspended, skipped when no longer dirty (R9.2). */
  entry(): QueueEntry {
    return { owner: this.owner, key: this.key, announce: false, run: () => this.process() };
  }

  process(): void {
    if (!this.active || this.suspended || !this.dirty) return;
    this.dirty = false;
    // R12.10: the reactions that the previous run registered end before the next run starts.
    this.removeChildren();
    runs.push(this);
    try {
      this.onRun();
    } finally {
      runs.pop();
    }
    this.settleDirty();
  }

  /**
   * Starts the reaction as one drain entry (R12.9): writes made by its first run (an effect, an immediate
   * handler) settle at once, and the re-run they cause comes after the start returns, never inside it. A setup,
   * an effect's first run or an immediate handler that throws propagates; the reaction then has no pending run.
   */
  start(): void {
    if (this.started || this.removed) return;
    runAsDrainEntry(() => {
      this.started = true;
      this.dirty = false;
      runs.push(this);
      try {
        this.onStart();
      } catch (error) {
        this.dirty = false;
        throw error;
      } finally {
        runs.pop();
      }
      this.settleDirty();
    });
  }

  /**
   * R9.2 skip rule: a run marked dirty by its own writes stays dirty only when a node it read changed after it
   * read it. An effect that wrote a value and then read the fresh value runs once per cause.
   */
  protected settleDirty(): void {
    if (this.dirty && !this.changedSinceRead()) this.dirty = false;
  }

  /** Stops the reaction and forgets its dependencies; failures are isolated (R12.4, R12.8). */
  stop(): void {
    if (!this.started) return;
    this.started = false;
    this.dirty = false;
    // R12.10: what this reaction's runs registered ends first (last in, first out).
    this.removeChildren();
    try {
      this.onStop();
    } catch {
      // Teardown failures are isolated and swallowed (R12.8).
    }
    releaseConsumer(this);
  }

  /** Removes the reaction for good: stop, release, and forget it (R12.10, the registration's handle). */
  remove(): void {
    if (this.removed) return;
    this.stop();
    this.removed = true;
    this.release();
    if (this.parent !== null) {
      const siblings = this.parent.children;
      const at = siblings.indexOf(this);
      if (at >= 0) siblings.splice(at, 1);
      this.parent = null;
    }
    this.owner.forgetReaction(this);
  }

  /** Removes the reactions registered by this reaction's runs, last in first out (R12.10). */
  removeChildren(): void {
    const children = this.children.splice(0);
    for (let i = children.length - 1; i >= 0; i -= 1) {
      const child = children[i];
      if (child === undefined) continue;
      child.parent = null;
      child.remove();
    }
  }

  /** Graph release: stop, then drop the references to user functions (R17.1). */
  release(): void {
    this.stop();
    forgetFrame(this);
    this.dropReferences();
  }

  protected abstract onStart(): void;
  protected abstract onRun(): void;
  protected abstract onStop(): void;
  protected abstract dropReferences(): void;
}
