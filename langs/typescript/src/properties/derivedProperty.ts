/**
 * DerivedProperty — value derived from N source observables.
 *
 * See spec/15-derived-properties.md and ADR-0011.
 */
import { combineLatest, map, Observable, Subject, Subscription } from "rxjs";

/**
 * Registry key of the internal state seam that VMx's own adapters (for
 * example `@thekaveh/vmx-react`) use to observe the silent first value. It is
 * not part of the specified DerivedProperty surface and may change in any
 * release.
 */
const OBSERVE_STATE: symbol = Symbol.for("@thekaveh/vmx:DerivedProperty.observeState");

export class DerivedProperty<TValue> {
  #value: TValue | undefined;
  #hasValue = false;
  readonly #changes = new Subject<TValue>();
  /** Signals the first value and every later change; carries no value. */
  readonly #states = new Subject<void>();
  readonly #subscription: Subscription;
  #disposed = false;
  readonly #canSet: ((v: TValue) => boolean) | null;
  readonly #setAction: ((v: TValue) => void) | null;

  constructor(
    derivedStream: Observable<TValue>,
    canSet: ((v: TValue) => boolean) | null = null,
    setAction: ((v: TValue) => void) | null = null,
  ) {
    this.#canSet = canSet;
    this.#setAction = setAction;
    this.#subscription = derivedStream.subscribe((v) => {
      if (!this.#hasValue) {
        this.#value = v;
        this.#hasValue = true;
        // The first value is not a ValueChanged emission (DPROP-009).
        this.#states.next();
        return;
      }
      if (Object.is(v, this.#value)) return;
      this.#value = v;
      this.#changes.next(v);
      this.#states.next();
    });
  }

  static {
    // Internal adapter seam, defined here so it can read #states but stays
    // out of the declarations: calls `listener` when the first value is
    // stored and after every `valueChanged` emission, without subscribing
    // upstream again. Returns an idempotent unsubscribe function.
    Object.defineProperty(DerivedProperty.prototype, OBSERVE_STATE, {
      value(this: DerivedProperty<unknown>, listener: () => void): () => void {
        const subscription = this.#states.subscribe({ next: listener });
        return () => subscription.unsubscribe();
      },
    });
  }

  get value(): TValue {
    if (!this.#hasValue) {
      throw new Error(
        "Derived property has no value yet — no source has emitted.",
      );
    }
    return this.#value as TValue;
  }

  get valueChanged(): Observable<TValue> {
    return this.#changes.asObservable();
  }

  canSet(value: TValue): boolean {
    return this.#canSet ? this.#canSet(value) : false;
  }

  setValue(value: TValue): void {
    if (!this.canSet(value)) {
      throw new Error("canSet returned false for the given value");
    }
    if (this.#setAction) this.#setAction(value);
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#subscription.unsubscribe();
    this.#changes.complete();
    this.#states.complete();
  }
}

export interface DerivedFromSourcesOptions<TValue> {
  canSet?: (value: TValue) => boolean;
  setAction?: (value: TValue) => void;
}

/** Build a DerivedProperty from one typed source (ADR-0035 §2 DP2). */
export function fromOne<T1, TValue>(
  s1: Observable<T1>,
  transform: (v1: T1) => TValue,
  opts?: DerivedFromSourcesOptions<TValue>,
): DerivedProperty<TValue> {
  return new DerivedProperty<TValue>(
    s1.pipe(map((v1) => transform(v1))),
    opts?.canSet ?? null,
    opts?.setAction ?? null,
  );
}

/** Build a DerivedProperty from two typed sources (ADR-0035 §2 DP2). */
export function fromTwo<T1, T2, TValue>(
  s1: Observable<T1>,
  s2: Observable<T2>,
  transform: (v1: T1, v2: T2) => TValue,
  opts?: DerivedFromSourcesOptions<TValue>,
): DerivedProperty<TValue> {
  return new DerivedProperty<TValue>(
    combineLatest([s1, s2]).pipe(map(([v1, v2]) => transform(v1, v2))),
    opts?.canSet ?? null,
    opts?.setAction ?? null,
  );
}

/** Build a DerivedProperty from three typed sources (ADR-0035 §2 DP2). */
export function fromThree<T1, T2, T3, TValue>(
  s1: Observable<T1>,
  s2: Observable<T2>,
  s3: Observable<T3>,
  transform: (v1: T1, v2: T2, v3: T3) => TValue,
  opts?: DerivedFromSourcesOptions<TValue>,
): DerivedProperty<TValue> {
  return new DerivedProperty<TValue>(
    combineLatest([s1, s2, s3]).pipe(
      map(([v1, v2, v3]) => transform(v1, v2, v3)),
    ),
    opts?.canSet ?? null,
    opts?.setAction ?? null,
  );
}

/** Build a DerivedProperty from four typed sources (ADR-0035 §2 DP2). */
export function fromFour<T1, T2, T3, T4, TValue>(
  s1: Observable<T1>,
  s2: Observable<T2>,
  s3: Observable<T3>,
  s4: Observable<T4>,
  transform: (v1: T1, v2: T2, v3: T3, v4: T4) => TValue,
  opts?: DerivedFromSourcesOptions<TValue>,
): DerivedProperty<TValue> {
  return new DerivedProperty<TValue>(
    combineLatest([s1, s2, s3, s4]).pipe(
      map(([v1, v2, v3, v4]) => transform(v1, v2, v3, v4)),
    ),
    opts?.canSet ?? null,
    opts?.setAction ?? null,
  );
}

/** Build a DerivedProperty from five typed sources (ADR-0035 §2 DP2). */
export function fromFive<T1, T2, T3, T4, T5, TValue>(
  s1: Observable<T1>,
  s2: Observable<T2>,
  s3: Observable<T3>,
  s4: Observable<T4>,
  s5: Observable<T5>,
  transform: (v1: T1, v2: T2, v3: T3, v4: T4, v5: T5) => TValue,
  opts?: DerivedFromSourcesOptions<TValue>,
): DerivedProperty<TValue> {
  return new DerivedProperty<TValue>(
    combineLatest([s1, s2, s3, s4, s5]).pipe(
      map(([v1, v2, v3, v4, v5]) => transform(v1, v2, v3, v4, v5)),
    ),
    opts?.canSet ?? null,
    opts?.setAction ?? null,
  );
}

/**
 * Build a DerivedProperty from N source observables.
 * `fromMany` is the parity alias (Python `from_many`).
 */
export function fromSources<TValue>(
  sources: Observable<unknown>[],
  transform: (...values: unknown[]) => TValue,
  opts?: DerivedFromSourcesOptions<TValue>,
): DerivedProperty<TValue> {
  if (sources.length === 0) {
    throw new Error("At least one source is required");
  }
  let stream: Observable<TValue>;
  if (sources.length === 1) {
    const [first] = sources;
    if (!first) throw new Error("Source observable is undefined");
    stream = first.pipe(map((v) => transform(v)));
  } else {
    stream = combineLatest(sources).pipe(map((arr) => transform(...arr)));
  }
  return new DerivedProperty<TValue>(
    stream,
    opts?.canSet ?? null,
    opts?.setAction ?? null,
  );
}

/** Parity alias of {@link fromSources} (Python `from_many`, C# `FromMany`). */
export const fromMany = fromSources;
