/**
 * DerivedProperty — value derived from N source observables.
 *
 * See spec/15-derived-properties.md and ADR-0011.
 */
import { combineLatest, map, Observable, Subject, Subscription } from "rxjs";

export class DerivedProperty<TValue> {
  #value: TValue | undefined;
  #hasValue = false;
  readonly #changes = new Subject<TValue>();
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
        return;
      }
      if (Object.is(v, this.#value)) return;
      this.#value = v;
      this.#changes.next(v);
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
  }
}

export interface DerivedFromSourcesOptions<TValue> {
  canSet?: (value: TValue) => boolean;
  setAction?: (value: TValue) => void;
}

/** Build a DerivedProperty from N source observables. */
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
