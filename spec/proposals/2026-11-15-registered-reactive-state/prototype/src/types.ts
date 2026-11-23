/**
 * Public types of the registered reactive state layer (the proposal's TypeScript API).
 */
import type { AsyncResourceRetention } from "@thekaveh/vmx";
import type { Observable } from "rxjs";
import type { Equality } from "./equality.js";

/** Private reactive state (R3.11). */
export interface Signal<T> {
  /** Tracked read; an assignment is one write, skipped when equal. */
  value: T;
  /** Untracked read. */
  peek(): T;
}

/** Private memoized derivation, evaluated lazily (R3.11). */
export interface Memo<T> {
  /** Tracked read; pulls when dirty. */
  readonly value: T;
  /** Pulls when dirty; records no edge. */
  peek(): T;
  /** One write that marks the memo dirty, for an input outside the graph. */
  invalidate(): void;
}

/** Writes several registered state keys as ONE write (R3.1). */
export type StateWriter<S> = (patch: Partial<S>) => void;

export interface CommandOptions {
  /** Extra notification sources for inputs outside the graph (spec 04 §4, R10.6). */
  readonly triggers?: readonly Observable<unknown>[];
}

export interface AsyncCommandOptions extends CommandOptions {
  readonly throwOnCancel?: boolean;
}

export interface ReactionOptions<T> {
  /** Default `Object.is`. */
  readonly equals?: Equality<T>;
  /** Also run the handler at each start (R12.4). Default false. */
  readonly immediate?: boolean;
  /** Run in every status but Disposed, from activation (R12.5). Default false. */
  readonly alive?: boolean;
}

export interface FollowKeyOptions<K> {
  /** Tracked. */
  readonly key: () => K;
  /** Tracked. Default: always true. */
  readonly enabled?: () => boolean;
  /** Start the first load when first enabled. Default false: the first load stays on demand (spec 23 §1). */
  readonly autoLoad?: boolean;
  /** Cancel a load in flight when the resource becomes disabled, and mark it outdated. Default true. */
  readonly cancelWhenDisabled?: boolean;
  /** Default `Object.is`. */
  readonly equals?: Equality<K>;
}

export interface KeyedResourceOptions<K, T> extends FollowKeyOptions<K> {
  /** Default `${owner.name}:resource`. */
  readonly name?: string;
  readonly load: (key: K, signal: AbortSignal) => Promise<T>;
  /** Default DiscardPrevious (spec 23). */
  readonly retention?: AsyncResourceRetention;
  readonly cleanupValue?: (value: T) => void;
}

/** One node read by the last evaluation of a registered name (R19.4, informative). */
export interface ExplainEntry {
  readonly owner: object;
  readonly name: string;
}
