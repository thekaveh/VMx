/**
 * ObservableDictionary<TKey1, TKey2, TValue> — two-key observable dictionary.
 *
 * Entries are stored in insertion order. Four RxJS Subjects surface mutations:
 *   - itemAdded     — emits { key1, key2, value } on insert
 *   - itemRemoved   — emits { key1, key2, value } on remove
 *   - itemReplaced  — emits { key1, key2, newValue, oldValue } on replace
 *   - reset         — emits void on clear
 *
 * keys1 and keys2 are live ObservableList<TKeyN> views of the distinct Key1 /
 * Key2 values currently present, in insertion order of their first appearance.
 *
 * Null/undefined keys are not permitted; passing one throws Error.
 *
 * See spec/21-collections.md §4 and ADR-0025.
 */

import { Observable, Subject } from "rxjs";
import { ObservableList } from "./observableList.js";

// ── Payload shapes ────────────────────────────────────────────────────────────

export interface DictionaryItemAddedEvent<TKey1, TKey2, TValue> {
  readonly key1: TKey1;
  readonly key2: TKey2;
  readonly value: TValue;
}

export interface DictionaryItemRemovedEvent<TKey1, TKey2, TValue> {
  readonly key1: TKey1;
  readonly key2: TKey2;
  readonly value: TValue;
}

export interface DictionaryItemReplacedEvent<TKey1, TKey2, TValue> {
  readonly key1: TKey1;
  readonly key2: TKey2;
  readonly newValue: TValue;
  readonly oldValue: TValue;
}

// ── Serialisation helper ──────────────────────────────────────────────────────

/** Serialise a key pair to a string map key. */
function serializeKey(key1: unknown, key2: unknown): string {
  return `${String(key1)}\x00${String(key2)}`;
}

// ── ObservableDictionary ──────────────────────────────────────────────────────

export class ObservableDictionary<TKey1, TKey2, TValue> {
  /** Insertion-ordered list of composite keys (as string tokens). */
  readonly #keyOrder: string[] = [];
  /** Map from serialised key to value. */
  readonly #data = new Map<string, TValue>();
  /** Map from serialised key to original key pair (for enumeration). */
  readonly #keyPairs = new Map<string, [TKey1, TKey2]>();

  /** Distinct-key observable views. */
  readonly #keys1 = new ObservableList<TKey1>();
  readonly #keys2 = new ObservableList<TKey2>();

  readonly #itemAdded =
    new Subject<DictionaryItemAddedEvent<TKey1, TKey2, TValue>>();
  readonly #itemRemoved =
    new Subject<DictionaryItemRemovedEvent<TKey1, TKey2, TValue>>();
  readonly #itemReplaced =
    new Subject<DictionaryItemReplacedEvent<TKey1, TKey2, TValue>>();
  readonly #reset = new Subject<void>();

  // ── Observables ─────────────────────────────────────────────────────────────

  /** Emits when an entry is added. */
  get itemAdded(): Observable<DictionaryItemAddedEvent<TKey1, TKey2, TValue>> {
    return this.#itemAdded.asObservable();
  }

  /** Emits when an entry is removed. */
  get itemRemoved(): Observable<
    DictionaryItemRemovedEvent<TKey1, TKey2, TValue>
  > {
    return this.#itemRemoved.asObservable();
  }

  /** Emits when an existing entry's value is replaced. */
  get itemReplaced(): Observable<
    DictionaryItemReplacedEvent<TKey1, TKey2, TValue>
  > {
    return this.#itemReplaced.asObservable();
  }

  /** Emits void on clear. */
  get reset(): Observable<void> {
    return this.#reset.asObservable();
  }

  // ── Key-axis views ───────────────────────────────────────────────────────────

  /**
   * Live observable view of distinct Key1 values,
   * in insertion order of their first appearance.
   */
  get keys1(): ObservableList<TKey1> {
    return this.#keys1;
  }

  /**
   * Live observable view of distinct Key2 values,
   * in insertion order of their first appearance.
   */
  get keys2(): ObservableList<TKey2> {
    return this.#keys2;
  }

  // ── Size ─────────────────────────────────────────────────────────────────────

  /** Total number of entries. */
  get size(): number {
    return this.#data.size;
  }

  // ── Mutations ────────────────────────────────────────────────────────────────

  /**
   * Insert a new entry.
   * Throws Error if key1 or key2 is null/undefined.
   * Throws Error if the key pair already exists.
   */
  set(key1: TKey1, key2: TKey2, value: TValue): void {
    this.#requireKeys(key1, key2);
    const token = serializeKey(key1, key2);
    if (this.#data.has(token)) {
      const oldValue = this.#data.get(token) as TValue;
      this.#data.set(token, value);
      this.#itemReplaced.next({ key1, key2, newValue: value, oldValue });
    } else {
      this.#internalAdd(token, key1, key2, value);
    }
  }

  /**
   * Remove the entry for (key1, key2).
   * Returns true if found and removed, false if absent.
   */
  delete(key1: TKey1, key2: TKey2): boolean {
    this.#requireKeys(key1, key2);
    const token = serializeKey(key1, key2);
    if (!this.#data.has(token)) return false;

    const value = this.#data.get(token) as TValue;
    this.#data.delete(token);
    this.#keyPairs.delete(token);
    this.#keyOrder.splice(this.#keyOrder.indexOf(token), 1);

    // Update key-axis views: drop only when no other entry uses this key.
    const key1StillPresent = [...this.#keyPairs.values()].some(
      ([k1]) => k1 === key1,
    );
    if (!key1StillPresent) this.#keys1.remove(key1);

    const key2StillPresent = [...this.#keyPairs.values()].some(
      ([, k2]) => k2 === key2,
    );
    if (!key2StillPresent) this.#keys2.remove(key2);

    this.#itemRemoved.next({ key1, key2, value });
    return true;
  }

  /**
   * Get the value for (key1, key2).
   * Returns undefined if absent.
   */
  get(key1: TKey1, key2: TKey2): TValue | undefined {
    this.#requireKeys(key1, key2);
    return this.#data.get(serializeKey(key1, key2));
  }

  /** Returns true if an entry exists for (key1, key2). */
  has(key1: TKey1, key2: TKey2): boolean {
    this.#requireKeys(key1, key2);
    return this.#data.has(serializeKey(key1, key2));
  }

  /** Remove all entries and emit reset. Does NOT fire per-entry itemRemoved events. */
  clear(): void {
    this.#data.clear();
    this.#keyPairs.clear();
    this.#keyOrder.length = 0;
    this.#keys1.clear();
    this.#keys2.clear();
    this.#reset.next();
  }

  // ── Enumeration ──────────────────────────────────────────────────────────────

  /**
   * Iterate entries in insertion order.
   * Each item is [key1, key2, value].
   */
  [Symbol.iterator](): IterableIterator<[TKey1, TKey2, TValue]> {
    const keyOrder = this.#keyOrder;
    const data = this.#data;
    const keyPairs = this.#keyPairs;
    let index = 0;
    return {
      next(): IteratorResult<[TKey1, TKey2, TValue]> {
        if (index >= keyOrder.length) return { done: true, value: undefined };
        const token = keyOrder[index++] as string;
        const pair = keyPairs.get(token) as [TKey1, TKey2];
        const v = data.get(token) as TValue;
        return { done: false, value: [pair[0], pair[1], v] };
      },
      [Symbol.iterator]() {
        return this;
      },
    };
  }

  // ── Internal ─────────────────────────────────────────────────────────────────

  #internalAdd(
    token: string,
    key1: TKey1,
    key2: TKey2,
    value: TValue,
  ): void {
    this.#keyOrder.push(token);
    this.#data.set(token, value);
    this.#keyPairs.set(token, [key1, key2]);

    // Update key-axis views on first appearance only.
    const key1AlreadyPresent = [...this.#keyPairs.values()].filter(
      ([k1]) => k1 === key1,
    ).length > 1;
    if (!key1AlreadyPresent) this.#keys1.push(key1);

    const key2AlreadyPresent = [...this.#keyPairs.values()].filter(
      ([, k2]) => k2 === key2,
    ).length > 1;
    if (!key2AlreadyPresent) this.#keys2.push(key2);

    this.#itemAdded.next({ key1, key2, value });
  }

  #requireKeys(key1: TKey1, key2: TKey2): void {
    if (key1 === null || key1 === undefined) {
      throw new Error("key1 must not be null or undefined");
    }
    if (key2 === null || key2 === undefined) {
      throw new Error("key2 must not be null or undefined");
    }
  }
}
