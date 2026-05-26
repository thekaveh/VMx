/**
 * DerivedProperty — value derived from N source observables.
 *
 * See spec/15-derived-properties.md and ADR-0011.
 */
import { combineLatest, map, Observable, Subject, Subscription } from "rxjs";

export class DerivedProperty<TValue> {
  private _value: TValue | undefined;
  private _hasValue = false;
  private readonly _changes = new Subject<TValue>();
  private readonly _subscription: Subscription;
  private _disposed = false;

  constructor(
    derivedStream: Observable<TValue>,
    private readonly _canSet: ((v: TValue) => boolean) | null = null,
    private readonly _setAction: ((v: TValue) => void) | null = null,
  ) {
    this._subscription = derivedStream.subscribe((v) => {
      if (!this._hasValue) {
        this._value = v;
        this._hasValue = true;
        return;
      }
      if (Object.is(v, this._value)) return;
      this._value = v;
      this._changes.next(v);
    });
  }

  get value(): TValue {
    if (!this._hasValue) {
      throw new Error(
        "Derived property has no value yet — no source has emitted.",
      );
    }
    return this._value as TValue;
  }

  get valueChanged(): Observable<TValue> {
    return this._changes.asObservable();
  }

  canSet(value: TValue): boolean {
    return this._canSet ? this._canSet(value) : false;
  }

  setValue(value: TValue): void {
    if (!this.canSet(value)) {
      throw new Error("canSet returned false for the given value");
    }
    if (this._setAction) this._setAction(value);
  }

  dispose(): void {
    if (this._disposed) return;
    this._disposed = true;
    this._subscription.unsubscribe();
    this._changes.complete();
  }
}

export interface DerivedFromSourcesOptions<TValue> {
  canSet?: (value: TValue) => boolean;
  setAction?: (value: TValue) => void;
}

/** Build a DerivedProperty from N source observables. */
export function deriveFromSources<TValue>(
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
