/**
 * ServicedObservableCollection<T> — observable array that optionally publishes
 * CollectionChangedMessage events to an IMessageHub.
 *
 * When no hub is injected, the class behaves like a plain observable collection
 * (local RxJS Subject emits events; no publication, no errors).
 *
 * Ownership stays with the caller: removing, replacing, or clearing an item does
 * not call dispose/destruct or any VM lifecycle method on that item.
 *
 * See spec/21-collections.md §2, ADR-0024, and ADR-0096.
 */
import { Observable, Subject } from "rxjs";
import type { IMessageHub } from "../services/messageHub.js";
import { CollectionChangedMessage } from "../messages/collectionChanged.js";

export { CollectionChangedMessage };

export class ServicedObservableCollection<T> {
  readonly #hub: IMessageHub | null;
  #items: T[] = [];
  readonly #subject = new Subject<CollectionChangedMessage<T>>();

  constructor(hub?: IMessageHub | null) {
    this.#hub = hub ?? null;
  }

  // ── Public surface ──────────────────────────────────────────────────────

  /** Hot observable of CollectionChangedMessage events. */
  get collectionChanged(): Observable<CollectionChangedMessage<T>> {
    return this.#subject.asObservable();
  }

  get length(): number {
    return this.#items.length;
  }

  /** Return the item at *index*. */
  at(index: number): T | undefined {
    return this.#items[index];
  }

  /** Return a shallow copy of the backing array. */
  toArray(): T[] {
    return [...this.#items];
  }

  [Symbol.iterator](): IterableIterator<T> {
    return this.#items[Symbol.iterator]();
  }

  // ── Mutations ───────────────────────────────────────────────────────────

  /** Append *item* to the end. */
  push(item: T): void {
    const index = this.#items.length;
    this.#items.push(item);
    this.#emit(CollectionChangedMessage.forAdd(this, item, index));
  }

  /** Remove and return the last item, or undefined if empty. */
  pop(): T | undefined {
    if (this.#items.length === 0) return undefined;
    const index = this.#items.length - 1;
    const item = this.#items[index] as T;
    this.#items.pop();
    this.#emit(CollectionChangedMessage.forRemove(this, item, index));
    return item;
  }

  /** Remove the first indexOf match for *item*. */
  remove(item: T): boolean {
    const index = this.#items.indexOf(item);
    if (index === -1) return false;
    this.removeAt(index);
    return true;
  }

  /** Remove the item at *index*. */
  removeAt(index: number): void {
    this.#validateIndex(index);
    const item = this.#items[index] as T;
    this.#items.splice(index, 1);
    this.#emit(CollectionChangedMessage.forRemove(this, item, index));
  }

  /**
   * Remove *count* items starting at *start* and optionally insert *newItems*.
   * Emits a Reset message (coarse-grained) for any multi-item splice.
   * For single-item operations (no inserts, count=1) emits a Remove.
   */
  splice(start: number, deleteCount?: number, ...newItems: T[]): T[] {
    const lengthBeforeSplice = this.#items.length;
    const removed = this.#items.splice(start, deleteCount ?? this.#items.length, ...newItems);
    if (removed.length === 0 && newItems.length === 0) {
      // No-op splice: nothing mutated, so nothing is emitted
      // (spec/21 §2.4 — messages are emitted per mutation).
      return removed;
    }
    if (removed.length === 1 && newItems.length === 0) {
      // Normalize the start index the way Array.prototype.splice resolves it
      // (negatives count from the end, out-of-range clamps) so the emitted
      // Remove carries the actual removal position (spec/21 line 148,
      // "indexBeforeRemoval"), not a raw negative/out-of-range argument.
      const resolvedStart =
        start < 0
          ? Math.max(lengthBeforeSplice + start, 0)
          : Math.min(start, lengthBeforeSplice);
      this.#emit(
        CollectionChangedMessage.forRemove(this, removed[0] as T, resolvedStart),
      );
    } else {
      this.#emit(CollectionChangedMessage.forReset(this));
    }
    return removed;
  }

  /** Replace the item at *index*, emitting even when the value is identical. */
  replace(index: number, newItem: T): void {
    this.#validateIndex(index);
    const oldItem = this.#items[index] as T;
    this.#items[index] = newItem;
    this.#emit(
      CollectionChangedMessage.forReplace(this, newItem, oldItem, index),
    );
  }

  /** Source-compatible alias for replace. */
  setAt(index: number, newItem: T): void {
    this.replace(index, newItem);
  }

  /** Replace the complete contents from a snapshot of *items*. */
  replaceAll(items: Iterable<T>): void {
    const snapshot = [...items];
    if (this.#items.length === 0 && snapshot.length === 0) return;
    this.#items = snapshot;
    this.#emit(CollectionChangedMessage.forReset(this));
  }

  /** Move an item using pre-move source and destination indices. */
  move(fromIndex: number, toIndex: number): void {
    this.#validateIndex(fromIndex);
    this.#validateIndex(toIndex);
    if (fromIndex === toIndex) return;

    const item = this.#items[fromIndex] as T;
    this.#items.splice(fromIndex, 1);
    this.#items.splice(toIndex, 0, item);
    this.#emit(
      CollectionChangedMessage.forMove(this, item, fromIndex, toIndex),
    );
  }

  /** Remove all items. */
  clear(): void {
    if (this.#items.length === 0) return;
    this.#items.length = 0;
    this.#emit(CollectionChangedMessage.forReset(this));
  }

  // ── Internal ────────────────────────────────────────────────────────────

  #emit(msg: CollectionChangedMessage<T>): void {
    // 1. Notify local subscribers.
    this.#subject.next(msg);
    // 2. Publish to hub (when present).
    this.#hub?.send(msg);
  }

  #validateIndex(index: number): void {
    if (
      !Number.isInteger(index) ||
      index < 0 ||
      index >= this.#items.length
    ) {
      throw new RangeError(`Index ${String(index)} out of bounds`);
    }
  }
}
