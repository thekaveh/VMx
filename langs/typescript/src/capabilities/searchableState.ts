/**
 * SearchableState — debounced filter helper implementing ISearchable.
 *
 * See spec/06-composite-vm.md §Search / filter and ADR-0014.
 */
import {
  asyncScheduler,
  BehaviorSubject,
  debounceTime,
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

    this.#subscription = merge(debouncedTerm, forceFilter).subscribe((term) => {
      this.#filteredSubject.next(this.#applyFilter(term));
    });
  }

  get searchTerm(): string {
    return this.#termSubject.value;
  }

  set searchTerm(value: string) {
    this.#termSubject.next(value);
  }

  get filtered(): Observable<readonly T[]> {
    return this.#filteredSubject.asObservable();
  }

  canSearch(): boolean {
    for (const _ of this.#items()) return true;
    return false;
  }

  search(): void {
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
