/**
 * ServicedObservableCollection<T> — observable array that optionally publishes
 * CollectionChangedMessage events to an IMessageHub.
 *
 * When no hub is injected, the class behaves like a plain observable collection
 * (local RxJS Subject emits events; no publication, no errors).
 *
 * See spec/21-collections.md §2 and ADR-0024.
 */
import { Observable, Subject } from "rxjs";
import type { IMessageHub } from "../services/messageHub.js";
import { CollectionChangedMessage } from "../messages/collectionChanged.js";

export { CollectionChangedMessage };

export class ServicedObservableCollection<T> {
  readonly #hub: IMessageHub | null;
  readonly #items: T[] = [];
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

  /**
   * Remove *count* items starting at *start* and optionally insert *newItems*.
   * Emits a Reset message (coarse-grained) for any multi-item splice.
   * For single-item operations (no inserts, count=1) emits a Remove.
   */
  splice(start: number, deleteCount?: number, ...newItems: T[]): T[] {
    const removed = this.#items.splice(start, deleteCount ?? this.#items.length, ...newItems);
    if (removed.length === 0 && newItems.length === 0) {
      // No-op splice: nothing mutated, so nothing is emitted
      // (spec/21 §2.4 — messages are emitted per mutation).
      return removed;
    }
    if (removed.length === 1 && newItems.length === 0) {
      this.#emit(
        CollectionChangedMessage.forRemove(this, removed[0] as T, start),
      );
    } else {
      this.#emit(CollectionChangedMessage.forReset(this));
    }
    return removed;
  }

  /** Replace the item at *index*. */
  setAt(index: number, newItem: T): void {
    if (index < 0 || index >= this.#items.length) {
      throw new RangeError(`Index ${String(index)} out of bounds`);
    }
    const oldItem = this.#items[index];
    this.#items[index] = newItem;
    this.#emit(
      CollectionChangedMessage.forReplace(
        this,
        newItem,
        oldItem as T,
        index,
      ),
    );
  }

  /** Remove all items. */
  clear(): void {
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
}
