/**
 * SearchableState — debounced filter helper implementing ISearchable.
 *
 * See spec/06-composite-vm.md §Search / filter and ADR-0014.
 */
import {
  asyncScheduler,
  BehaviorSubject,
  catchError,
  debounceTime,
  EMPTY,
  map,
  merge,
  type Observable,
  type SchedulerLike,
  Subject,
  Subscription,
} from "rxjs";
import { declareCapabilities } from "./registry.js";
import type { ISearchable } from "./search.js";

export interface SearchableStateOptions<T> {
  items: () => Iterable<T>;
  predicate: (item: T, term: string) => boolean;
  debounceMs?: number; // default: 1000; pass 0 to disable
  scheduler?: SchedulerLike;
  /** Optional invalidation signal; payloads are ignored. */
  sourceChanges?: Observable<unknown>;
}

export class SearchableState<T> implements ISearchable {
  readonly #items: () => Iterable<T>;
  readonly #predicate: (item: T, term: string) => boolean;
  readonly #termSubject = new BehaviorSubject<string>("");
  readonly #filteredSubject: BehaviorSubject<readonly T[]>;
  readonly #forceSearchSubject = new Subject<void>();
  readonly #subscription: Subscription;
  #disposed = false;

  constructor(opts: SearchableStateOptions<T>) {
    this.#items = opts.items;
    this.#predicate = opts.predicate;
    declareCapabilities(this, "ISearchable");
    const debounceMs = opts.debounceMs ?? 1000;
    const scheduler = opts.scheduler ?? asyncScheduler;
    this.#filteredSubject = new BehaviorSubject<readonly T[]>(
      this.#applyFilter(""),
    );

    const debouncedTerm: Observable<string> =
      debounceMs > 0
        ? this.#termSubject.pipe(debounceTime(debounceMs, scheduler))
        : this.#termSubject.asObservable();

    const forceFilter = this.#forceSearchSubject.pipe(
      map(() => this.#termSubject.value),
    );
    const sourceFilter: Observable<string> =
      opts.sourceChanges?.pipe(
        map(() => this.#termSubject.value),
        catchError(() => EMPTY),
      ) ?? EMPTY;

    this.#subscription = merge(
      debouncedTerm,
      forceFilter,
      sourceFilter,
    ).subscribe((term) => {
      this.#filteredSubject.next(this.#applyFilter(term));
    });

    // Close the initial snapshot/attach gap. Callers cannot observe the
    // constructor-only first value; later source pulses flow through the
    // subscription above.
    if (opts.sourceChanges !== undefined) {
      this.#filteredSubject.next(this.#applyFilter(this.#termSubject.value));
    }
  }

  get searchTerm(): string {
    // Inert after dispose: return "" like C#/Python (rxjs BehaviorSubject keeps
    // its last value post-complete, so an explicit guard is required for parity).
    if (this.#disposed) return "";
    return this.#termSubject.value;
  }

  set searchTerm(value: string) {
    // Inert after dispose (parity with C#/Python + this module's own dispose
    // discipline): a post-dispose set would otherwise mutate the BehaviorSubject's
    // retained value even though nothing recomputes.
    if (this.#disposed) return;
    // Spec wording is "emission on a new value" — guard against no-op
    // re-sets so debounce + recompute don't fire when nothing changed.
    if (value === this.#termSubject.value) return;
    this.#termSubject.next(value);
  }

  /**
   * The current filtered view, recomputed on each debounced term change,
   * explicit {@link search} call, and optional `sourceChanges` pulse. Source
   * completion or failure stops automatic refresh without terminating this
   * observable.
   */
  get filtered(): Observable<readonly T[]> {
    return this.#filteredSubject.asObservable();
  }

  canSearch(): boolean {
    for (const _ of this.#items()) return true;
    return false;
  }

  search(): void {
    if (this.#disposed) return;
    this.#forceSearchSubject.next();
  }

  #applyFilter(term: string): T[] {
    const out: T[] = [];
    for (const item of this.#items()) {
      if (this.#predicate(item, term)) out.push(item);
    }
    return out;
  }

  /** Idempotent: subsequent calls are a no-op. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#subscription.unsubscribe();
    this.#termSubject.complete();
    this.#filteredSubject.complete();
    this.#forceSearchSubject.complete();
  }
}
