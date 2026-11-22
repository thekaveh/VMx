/**
 * Tracked command predicates (R10.*, as amended by fix round 2).
 *
 * R10.2 (fix round 2): every VMx command tracks its own predicate, wherever it was built. Each evaluation of a
 * RelayCommand, RelayCommandOf or AsyncRelayCommand predicate (`canExecute()`, and the check inside `execute()`)
 * runs in the command's frame, and so does the extra predicate of a DecoratorCommand (`wrapWith`). When a settle
 * changes a node of the frame, the command raises CanExecuteChanged once and clears the set (R10.3). A combinator
 * forwards its inner command's raises, so the inner command's evaluation inside it is opaque: it does not also
 * record into the combinator's frame (no double raise).
 *
 * The helpers (`relayCommand`, `relayCommandOf`, `asyncRelayCommand`) build the command through its builder and own
 * it in the same call (R10.1, D13); tracking is the commands' own.
 *
 * VMx would hold the frame inside each command class. The prototype keeps it in a WeakMap and installs the
 * wrappers on the 3.30.0 prototypes at import time (`library.ts`).
 */
import {
  AsyncRelayCommand,
  DecoratorCommand,
  RelayCommand,
  RelayCommandOf,
} from "@thekaveh/vmx";
import { merge, type Observable, Subject } from "rxjs";
import { reportOnce } from "./diagnostics.js";
import { ReactiveCycleError, ReactiveWriteError } from "./errors.js";
import {
  forgetFrame,
  Frame,
  isTracking,
  nextIndex,
  type NodeOwner,
  type QueueEntry,
  releaseConsumer,
  runFrame,
  untracked,
} from "./graph.js";
import { trackAnnouncement } from "./interop.js";
import type { AsyncCommandOptions, CommandOptions } from "./types.js";
import { describeObject, internals } from "./util.js";
import type { VMState } from "./vmState.js";

type Method = (this: unknown, ...args: unknown[]) => unknown;

/** The view-model state that owns each helper command: its raise entries are dropped with it (R9.2). */
const commandOwners = new WeakMap<object, VMState>();

/** The frame of one command's predicate (R10.2). */
class CommandFrame extends Frame {
  readonly frameKind = "command";
  readonly index = nextIndex();

  constructor(
    readonly command: object,
    readonly union: boolean,
    readonly raise: () => void,
  ) {
    super();
  }

  /** A settle changed a node in the set: one raise, then the set is cleared (R10.3). */
  affected(): QueueEntry | null {
    releaseConsumer(this);
    const owner: NodeOwner | null = commandOwners.get(this.command) ?? null;
    if (owner !== null && owner.disposing) return null;
    const label = owner?.label ?? describeObject(this.command);
    return { owner, key: `${label}:command#${String(this.index)}`, announce: false, run: this.raise };
  }
}

const frames = new WeakMap<object, CommandFrame>();

function frameOf(command: object, union: boolean, raise: () => void): CommandFrame {
  let frame = frames.get(command);
  if (frame === undefined) {
    frame = new CommandFrame(command, union, raise);
    frames.set(command, frame);
  }
  return frame;
}

/** Releases a disposed command's frame: no node keeps it reachable (R10.7, R17.2). */
export function releaseCommandFrame(command: object): void {
  const frame = frames.get(command);
  if (frame !== undefined) forgetFrame(frame);
}

// ── Combinators: an inner command's evaluation is opaque to the combinator that forwards it ──────────────────

/** The command evaluations in progress, innermost last; a decorator's entry names its inner command's stream. */
const evaluations: { readonly innerKey: unknown }[] = [];
const NO_INNER: unique symbol = Symbol("no inner");

function streamKey(stream: unknown): unknown {
  if (typeof stream === "object" && stream !== null) {
    const source = (stream as { readonly source?: unknown }).source;
    if (source !== undefined) return source;
  }
  return stream;
}

/** True when `command` is evaluated directly by a decorator that forwards its raises. */
function isForwardedInner(command: object): boolean {
  const top = evaluations[evaluations.length - 1];
  if (top === undefined || top.innerKey === NO_INNER) return false;
  return streamKey((command as { readonly canExecuteChanged?: unknown }).canExecuteChanged) === top.innerKey;
}

function evaluateIn<T>(frame: CommandFrame, innerKey: unknown, run: () => T): T {
  evaluations.push({ innerKey });
  try {
    return runFrame(frame, run, { evaluation: true, passThrough: true, union: frame.union });
  } finally {
    evaluations.pop();
  }
}

/** R10.7: a canExecute() call inside a frame also records the command's CanExecuteChanged. */
function recordRaises(command: object): void {
  if (isTracking()) trackAnnouncement(command, "canExecute");
}

/** `canExecute` of RelayCommand, RelayCommandOf and AsyncRelayCommand, evaluated in the command's frame. */
export function trackedCanExecute(original: Method, union: boolean): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    const command = this as { raiseCanExecuteChanged(): void };
    const frame = frameOf(command, union, () => command.raiseCanExecuteChanged());
    const run = (): unknown => evaluateIn(frame, NO_INNER, () => original.apply(this, args));
    if (isForwardedInner(command)) return untracked(run);
    const result = run();
    recordRaises(command);
    return result;
  };
}

/** `canExecute` of any other command (CompositeCommand, ConfirmationDecoratorCommand): R10.7 only. */
export function raisesTrackedCanExecute(original: Method): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    const command = this as object;
    if (isForwardedInner(command)) return untracked(() => original.apply(this, args));
    const result = original.apply(this, args);
    recordRaises(command);
    return result;
  };
}

const decoratorRaises = new WeakMap<object, Subject<void>>();
const decoratorStreams = new WeakMap<object, Observable<void>>();
const decoratorInnerKeys = new WeakMap<object, unknown>();

function raisesOf(decorator: object): Subject<void> {
  let subject = decoratorRaises.get(decorator);
  if (subject === undefined) {
    subject = new Subject<void>();
    decoratorRaises.set(decorator, subject);
  }
  return subject;
}

/**
 * `canExecuteChanged` of a DecoratorCommand: the inner command's raises (3.30.0), merged with the raises of the
 * decorator's own tracked predicate. One stream object per decorator, so a combinator around it can recognize it.
 */
export function decoratorCanExecuteChanged(original: (this: unknown) => unknown): (this: unknown) => unknown {
  return function (this: unknown): unknown {
    const decorator = this as object;
    let stream = decoratorStreams.get(decorator);
    if (stream === undefined) {
      const inner = original.call(decorator) as Observable<void>;
      decoratorInnerKeys.set(decorator, streamKey(inner));
      stream = merge(inner, raisesOf(decorator));
      decoratorStreams.set(decorator, stream);
    }
    return stream;
  };
}

/**
 * `canExecute` of a DecoratorCommand (`wrapWith`): the extra predicate runs in the decorator's frame; the inner
 * command's evaluation is opaque, because the decorator forwards the inner's raises natively.
 */
export function decoratorCanExecute(original: Method, innerStream: (this: unknown) => unknown): Method {
  return function (this: unknown, ...args: unknown[]): unknown {
    const decorator = this as object;
    if (!decoratorInnerKeys.has(decorator)) decoratorInnerKeys.set(decorator, streamKey(innerStream.call(decorator)));
    const raises = raisesOf(decorator);
    const frame = frameOf(decorator, false, () => raises.next());
    const run = (): unknown => evaluateIn(frame, decoratorInnerKeys.get(decorator), () => original.apply(this, args));
    if (isForwardedInner(decorator)) return untracked(run);
    const result = run();
    recordRaises(decorator);
    return result;
  };
}

/** A disposed decorator raises nothing more of its own. */
export function releaseDecorator(decorator: object): void {
  releaseCommandFrame(decorator);
  decoratorRaises.get(decorator)?.complete();
}

/** True for the prototypes whose predicates `library.ts` tracks with `trackedCanExecute`. */
export const TRACKED_COMMANDS: readonly { readonly prototype: object; readonly union: boolean }[] = [
  { prototype: RelayCommand.prototype, union: false },
  { prototype: RelayCommandOf.prototype, union: true },
  { prototype: AsyncRelayCommand.prototype, union: false },
];

export const DECORATOR_PROTOTYPE: object = DecoratorCommand.prototype;

// ── The helpers (R10.1) ──────────────────────────────────────────────────────────────────────────────────────

/** R19.6: a reactive usage error inside a helper predicate reads as false and is reported once per class. */
function reporting<A extends unknown[]>(state: VMState, predicate: (...args: A) => boolean): (...args: A) => boolean {
  return (...args: A): boolean => {
    try {
      return predicate(...args);
    } catch (error) {
      if (error instanceof ReactiveWriteError || error instanceof ReactiveCycleError) {
        reportOnce(
          `predicate:${state.className}:${error.name}`,
          `${state.className}: a command predicate raised ${error.name} (${error.message}); it reads as false`,
        );
      }
      throw error;
    }
  };
}

function register<C extends { dispose(): void }>(state: VMState, command: C): C {
  commandOwners.set(command, state.lifecycle);
  // R10.1: registered with own() in the same call, on the canonical ownership identity (ADR-0124).
  return internals(state.lifecycle.vm).own(command);
}

export function createRelayCommand(
  state: VMState,
  task: () => void,
  canExecute: (() => boolean) | undefined,
  options: CommandOptions | undefined,
): RelayCommand {
  let builder = RelayCommand.builder().task(task);
  if (canExecute !== undefined) builder = builder.predicate(reporting(state, canExecute));
  for (const trigger of options?.triggers ?? []) builder = builder.triggers(trigger);
  return register(state, builder.build());
}

export function createRelayCommandOf<T>(
  state: VMState,
  task: (parameter: T) => void,
  canExecute: ((parameter: T) => boolean) | undefined,
  options: CommandOptions | undefined,
): RelayCommandOf<T> {
  let builder = RelayCommandOf.builder<T>().task(task);
  if (canExecute !== undefined) builder = builder.predicate(reporting(state, canExecute));
  for (const trigger of options?.triggers ?? []) builder = builder.triggers(trigger);
  return register(state, builder.build());
}

export function createAsyncRelayCommand(
  state: VMState,
  task: (signal: AbortSignal) => Promise<void>,
  canExecute: (() => boolean) | undefined,
  options: AsyncCommandOptions | undefined,
): AsyncRelayCommand {
  let builder = AsyncRelayCommand.builder().task(task);
  if (canExecute !== undefined) builder = builder.predicate(reporting(state, canExecute));
  for (const trigger of options?.triggers ?? []) builder = builder.triggers(trigger);
  if (options?.throwOnCancel !== undefined) builder = builder.throwOnCancel(options.throwOnCancel);
  return register(state, builder.build());
}
