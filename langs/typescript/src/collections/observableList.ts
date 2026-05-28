/**
 * ObservableList<T> — granular per-mutation event observable list.
 *
 * Exposes four RxJS Subjects for strongly typed mutation streams:
 *   - itemAdded     — emits { item, index } on push/insert
 *   - itemRemoved   — emits { item, index } (index before removal) on remove
 *   - itemReplaced  — emits { newItem, oldItem, index } on replace
 *   - reset         — emits void on clear or batch completion
 *
 * A propertyChanged Subject emits the property name ("Count") after every
 * mutation that changes Count (add and remove; not replace). This ordering
 * is normative per spec §3.3 and ADR-0026.
 *
 * withBatch(callback) invokes the callback, suppresses granular events, and
 * fires a single reset on completion (ref-counted for nested calls).
 *
 * See spec/21-collections.md §3 and ADR-0026.
 */

import { Observable, Subject } from "rxjs";

// ── Payload shapes ────────────────────────────────────────────────────────────

export interface ItemAddedEvent<T> {
  readonly item: T;
  readonly index: number;
}

export interface ItemRemovedEvent<T> {
  readonly item: T;
  /** Index of the item before it was removed. */
  readonly index: number;
}

export interface ItemReplacedEvent<T> {
  readonly newItem: T;
  readonly oldItem: T;
  readonly index: number;
}

// ── ObservableList ────────────────────────────────────────────────────────────

export class ObservableList<T> {
  readonly #items: T[] = [];
  #batchDepth = 0;
  #mutatedInBatch = false;

  readonly #itemAdded = new Subject<ItemAddedEvent<T>>();
  readonly #itemRemoved = new Subject<ItemRemovedEvent<T>>();
  readonly #itemReplaced = new Subject<ItemReplacedEvent<T>>();
  readonly #reset = new Subject<void>();
  readonly #propertyChanged = new Subject<string>();

  // ── Observables ─────────────────────────────────────────────────────────────

  /** Emits when an item is added. Payload: { item, index }. */
  get itemAdded(): Observable<ItemAddedEvent<T>> {
    return this.#itemAdded.asObservable();
  }

  /** Emits when an item is removed. Payload: { item, index } (index before removal). */
  get itemRemoved(): Observable<ItemRemovedEvent<T>> {
    return this.#itemRemoved.asObservable();
  }

  /** Emits when an item is replaced. Payload: { newItem, oldItem, index }. */
  get itemReplaced(): Observable<ItemReplacedEvent<T>> {
    return this.#itemReplaced.asObservable();
  }

  /** Emits (void) on clear or when a batch completes with mutations. */
  get reset(): Observable<void> {
    return this.#reset.asObservable();
  }

  /**
   * Emits the property name whenever a property changes.
   * Emits "Count" after every add and remove (not after replace).
   * Ordering: granular event fires before propertyChanged("Count") — normative.
   */
  get propertyChanged(): Observable<string> {
    return this.#propertyChanged.asObservable();
  }

  // ── Length ───────────────────────────────────────────────────────────────────

  get length(): number {
    return this.#items.length;
  }

  at(index: number): T | undefined {
    return this.#items[index];
  }

  toArray(): T[] {
    return [...this.#items];
  }

  [Symbol.iterator](): IterableIterator<T> {
    return this.#items[Symbol.iterator]();
  }

  // ── Mutations ────────────────────────────────────────────────────────────────

  /** Append an item to the end of the list. */
  push(item: T): void {
    const index = this.#items.length;
    this.#items.push(item);
    this.#onAdded(item, index);
  }

  /** Insert an item at the given index. */
  insert(index: number, item: T): void {
    this.#items.splice(index, 0, item);
    this.#onAdded(item, index);
  }

  /** Remove and return the last item, or undefined if empty. */
  pop(): T | undefined {
    if (this.#items.length === 0) return undefined;
    const index = this.#items.length - 1;
    const item = this.#items[index] as T;
    this.#items.pop();
    this.#onRemoved(item, index);
    return item;
  }

  /**
   * Remove the item at *index*.
   * Throws RangeError if index is out of bounds.
   */
  removeAt(index: number): void {
    if (index < 0 || index >= this.#items.length) {
      throw new RangeError(`Index ${String(index)} out of bounds`);
    }
    const item = this.#items[index] as T;
    this.#items.splice(index, 1);
    this.#onRemoved(item, index);
  }

  /**
   * Remove the first occurrence of *item*.
   * Returns true if the item was found and removed, false otherwise.
   */
  remove(item: T): boolean {
    const index = this.#items.indexOf(item);
    if (index === -1) return false;
    this.#items.splice(index, 1);
    this.#onRemoved(item, index);
    return true;
  }

  /**
   * Replace the item at *index* with *newItem*.
   * Throws RangeError if index is out of bounds.
   */
  replace(index: number, newItem: T): void {
    if (index < 0 || index >= this.#items.length) {
      throw new RangeError(`Index ${String(index)} out of bounds`);
    }
    const oldItem = this.#items[index] as T;
    this.#items[index] = newItem;
    this.#onReplaced(newItem, oldItem, index);
  }

  /** Remove all items and emit reset. */
  clear(): void {
    this.#items.length = 0;
    this.#onReset();
  }

  // ── Batch ────────────────────────────────────────────────────────────────────

  /**
   * Execute *callback*, suppressing granular events during execution.
   * On completion of the outermost batch (ref-counted), a single reset fires
   * if any mutations occurred.
   */
  withBatch(callback: () => void): void {
    this.#batchDepth++;
    try {
      callback();
    } finally {
      this.#batchDepth--;
      if (this.#batchDepth === 0 && this.#mutatedInBatch) {
        this.#mutatedInBatch = false;
        this.#reset.next();
      }
    }
  }

  // ── Internal ─────────────────────────────────────────────────────────────────

  #onAdded(item: T, index: number): void {
    if (this.#batchDepth > 0) {
      this.#mutatedInBatch = true;
      return;
    }
    this.#itemAdded.next({ item, index });
    this.#propertyChanged.next("Count");
  }

  #onRemoved(item: T, index: number): void {
    if (this.#batchDepth > 0) {
      this.#mutatedInBatch = true;
      return;
    }
    this.#itemRemoved.next({ item, index });
    this.#propertyChanged.next("Count");
  }

  #onReplaced(newItem: T, oldItem: T, index: number): void {
    if (this.#batchDepth > 0) {
      this.#mutatedInBatch = true;
      return;
    }
    this.#itemReplaced.next({ newItem, oldItem, index });
    // Count does not change on replace — no propertyChanged("Count")
  }

  #onReset(): void {
    if (this.#batchDepth > 0) {
      this.#mutatedInBatch = true;
      return;
    }
    this.#reset.next();
  }
}
