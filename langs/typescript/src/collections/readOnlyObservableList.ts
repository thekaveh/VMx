/**
 * ReadOnlyObservableList<T> — read-only facade over an ObservableList<T>.
 *
 * It has every read and subscribe member of ObservableList<T>, and no mutator
 * and no batch member. It reads through to the live source, so it always shows
 * the current items. Its streams are the source's streams, so subscribers see
 * the same events in the same order.
 *
 * ObservableDictionary returns it from keys1 and keys2, so only the dictionary
 * changes a key view.
 *
 * See spec/21-collections.md §4.2 and ADR-0193.
 */

import type { Observable } from "rxjs";

import type {
  ItemAddedEvent,
  ItemRemovedEvent,
  ItemReplacedEvent,
  ObservableList,
} from "./observableList.js";

export class ReadOnlyObservableList<T> implements Iterable<T> {
  readonly #source: ObservableList<T>;

  /**
   * @internal Wraps `source`. VMx creates the key views of ObservableDictionary.
   */
  constructor(source: ObservableList<T>) {
    this.#source = source;
  }

  // ── Observables ─────────────────────────────────────────────────────────────

  /** Emits when an item is added. Payload: { item, index }. */
  get itemAdded(): Observable<ItemAddedEvent<T>> {
    return this.#source.itemAdded;
  }

  /** Emits when an item is removed. Payload: { item, index } (index before removal). */
  get itemRemoved(): Observable<ItemRemovedEvent<T>> {
    return this.#source.itemRemoved;
  }

  /** Emits when an item is replaced. Payload: { newItem, oldItem, index }. */
  get itemReplaced(): Observable<ItemReplacedEvent<T>> {
    return this.#source.itemReplaced;
  }

  /** Emits (void) on a reset of the source. */
  get reset(): Observable<void> {
    return this.#source.reset;
  }

  /** Emits the property name ("Count") when the source's count changes. */
  get propertyChanged(): Observable<string> {
    return this.#source.propertyChanged;
  }

  // ── Reads ───────────────────────────────────────────────────────────────────

  get length(): number {
    return this.#source.length;
  }

  at(index: number): T | undefined {
    return this.#source.at(index);
  }

  toArray(): T[] {
    return this.#source.toArray();
  }

  [Symbol.iterator](): IterableIterator<T> {
    return this.#source[Symbol.iterator]();
  }
}
