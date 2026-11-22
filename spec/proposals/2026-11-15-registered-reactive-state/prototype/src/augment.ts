/**
 * Types of the proposed API on `@thekaveh/vmx` (the proposal's TypeScript API).
 *
 * In VMx the instance members are `protected` on ComponentVMBase; a module augmentation can add public interface
 * members only, so they are public here and call sites type-check the same way.
 *
 * The free functions, classes and types are also declared on `@thekaveh/vmx`, so code written against the design
 * can import them from there as it will from VMx. On 3.30.0 they exist at runtime only in this prototype's index: the prototype's own
 * tests import them from `./index.js`; an import from `@thekaveh/vmx` type-checks but does not link at runtime.
 */
import type {
  AsyncRelayCommand,
  AsyncResourceVM,
  IDispatcher,
  IMessageHub,
  OwnedResource,
  RelayCommand,
  RelayCommandOf,
} from "@thekaveh/vmx";
import type { activate as activateImpl, explain as explainImpl, read as readImpl } from "./bridge.js";
import type { Equality as EqualityImpl, shallowEqual as shallowEqualImpl } from "./equality.js";
import type {
  ReactiveCycleError as ReactiveCycleErrorImpl,
  ReactiveOverflowError as ReactiveOverflowErrorImpl,
  ReactiveWriteError as ReactiveWriteErrorImpl,
} from "./errors.js";
import type { untracked as untrackedImpl } from "./graph.js";
import type {
  AsyncCommandOptions as AsyncCommandOptionsImpl,
  CommandOptions as CommandOptionsImpl,
  FollowKeyOptions as FollowKeyOptionsImpl,
  KeyedResourceOptions as KeyedResourceOptionsImpl,
  Memo as MemoImpl,
  ReactionOptions as ReactionOptionsImpl,
  Signal as SignalImpl,
  StateWriter as StateWriterImpl,
} from "./types.js";

declare module "@thekaveh/vmx" {
  export type Equality<T> = EqualityImpl<T>;
  export type Signal<T> = SignalImpl<T>;
  export type Memo<T> = MemoImpl<T>;
  export type StateWriter<S> = StateWriterImpl<S>;
  export type CommandOptions = CommandOptionsImpl;
  export type AsyncCommandOptions = AsyncCommandOptionsImpl;
  export type ReactionOptions<T> = ReactionOptionsImpl<T>;
  export type FollowKeyOptions<K> = FollowKeyOptionsImpl<K>;
  export type KeyedResourceOptions<K, T> = KeyedResourceOptionsImpl<K, T>;

  export const shallowEqual: typeof shallowEqualImpl;
  export const untracked: typeof untrackedImpl;
  export const read: typeof readImpl;
  export const activate: typeof activateImpl;
  export const explain: typeof explainImpl;
  export const ReactiveWriteError: typeof ReactiveWriteErrorImpl;
  export type ReactiveWriteError = ReactiveWriteErrorImpl;
  export const ReactiveCycleError: typeof ReactiveCycleErrorImpl;
  export type ReactiveCycleError = ReactiveCycleErrorImpl;
  export const ReactiveOverflowError: typeof ReactiveOverflowErrorImpl;
  export type ReactiveOverflowError = ReactiveOverflowErrorImpl;

  interface ComponentVMBase {
    // V1 state
    observable<K extends keyof this>(
      initial: { [P in K]: this[P] },
      equals?: { [P in K]?: EqualityImpl<this[P]> },
    ): StateWriterImpl<{ [P in K]: this[P] }>;
    signal<T>(initial: T, equals?: EqualityImpl<T>): SignalImpl<T>;
    // V2 computed
    computed<K extends keyof this>(...names: K[]): void;
    computed<K extends keyof this>(equals: { [P in K]: EqualityImpl<this[P]> }): void;
    memo<T>(fn: (previous: T | undefined) => T, equals?: EqualityImpl<T>): MemoImpl<T>;
    invalidate<K extends keyof this>(...names: K[]): void;
    change<R>(fn: () => R): R;
    // V3 commands
    relayCommand(task: () => void, canExecute?: () => boolean, options?: CommandOptionsImpl): RelayCommand;
    relayCommandOf<T>(
      task: (parameter: T) => void,
      canExecute?: (parameter: T) => boolean,
      options?: CommandOptionsImpl,
    ): RelayCommandOf<T>;
    asyncRelayCommand(
      task: (signal: AbortSignal) => Promise<void>,
      canExecute?: () => boolean,
      options?: AsyncCommandOptionsImpl,
    ): AsyncRelayCommand;
    // V4 + V5 members
    member<VM extends ComponentVMBase>(vm: VM): VM;
    member<O extends { readonly hub: IMessageHub; readonly dispatcher: IDispatcher }, VM extends ComponentVMBase>(
      ctor: new (options: O) => VM,
      options: Omit<O, "hub" | "dispatcher">,
    ): VM;
    // V6 reactions. Each returns the handle that removes the reaction (R12.10, fix round 2).
    effect(fn: () => void | (() => void)): () => void;
    reaction<T>(select: () => T, handler: (value: T, previous: T) => void, options?: ReactionOptionsImpl<T>): () => void;
    whileConstructed(setup: () => OwnedResource | void): () => void;
    // V7 keyed resources
    keyedResource<K, T>(options: KeyedResourceOptionsImpl<K, T>): AsyncResourceVM<T>;
    followKey<K>(resource: AsyncResourceVM<unknown>, options: FollowKeyOptionsImpl<K>): () => void;
  }
}
