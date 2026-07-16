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
import type { IMessageHub } from "../services/messageHub.js";
import { CollectionChangedMessage } from "../messages/collectionChanged.js";
import { ObservableList } from "./observableList.js";

// ── Payload shapes ────────────────────────────────────────────────────────────

/**
 * The element type carried in hub `CollectionChangedMessage` publications from
 * `ObservableDictionary`. Both keys and the value are included so subscribers
 * can recover the full identity of the mutated entry.
 *
 * C# equivalent: `KeyValuePair<(TKey1, TKey2), TValue>`
 * Python equivalent: `(key1, key2, value)` tuple
 * Per ADR-0006 each shape is flavor-idiomatic; per ADR-0009 the divergence is
 * catalogued and accepted.
 */
export interface DictionaryEntry<TKey1, TKey2, TValue> {
  readonly key1: TKey1;
  readonly key2: TKey2;
  readonly value: TValue;
}

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

interface StoredDictionaryEntry<TKey1, TKey2, TValue> {
  readonly key1: TKey1;
  readonly key2: TKey2;
  value: TValue;
}

function sameValueZero(left: unknown, right: unknown): boolean {
  return (
    left === right ||
    (typeof left === "number" &&
      typeof right === "number" &&
      Number.isNaN(left) &&
      Number.isNaN(right))
  );
}

// ── ObservableDictionary ──────────────────────────────────────────────────────

export class ObservableDictionary<TKey1, TKey2, TValue> {
  readonly #hub: IMessageHub | null;

  /** Insertion-ordered entry identities (backs enumeration). */
  readonly #keyOrder: StoredDictionaryEntry<TKey1, TKey2, TValue>[] = [];
  /** Native nested maps preserve each key axis' standard Map equality. */
  readonly #data = new Map<
    TKey1,
    Map<TKey2, StoredDictionaryEntry<TKey1, TKey2, TValue>>
  >();

  /** Reference counts for distinct key1 values (for O(1) key-axis upkeep). */
  readonly #key1Counts = new Map<TKey1, number>();
  /** Reference counts for distinct key2 values (for O(1) key-axis upkeep). */
  readonly #key2Counts = new Map<TKey2, number>();

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

  /**
   * Create a new ObservableDictionary.
   * @param hub Optional hub. Pass null/undefined for standalone (no publication) mode.
   */
  constructor(hub?: IMessageHub | null) {
    this.#hub = hub ?? null;
  }

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
    return this.#keyOrder.length;
  }

  // ── Mutations ────────────────────────────────────────────────────────────────

  /**
   * Insert or replace an entry.
   * Throws Error if key1 or key2 is null/undefined.
   * If the key pair already exists, the value is replaced and itemReplaced emits.
   * To guard against overwriting an existing entry, use {@link add} instead.
   */
  set(key1: TKey1, key2: TKey2, value: TValue): void {
    this.#requireKeys(key1, key2);
    const entry = this.#entryAt(key1, key2);
    if (entry !== undefined) {
      const oldValue = entry.value;
      entry.value = value;
      // 1. Local granular event first.
      this.#itemReplaced.next({ key1, key2, newValue: value, oldValue });
      // 2. Publish to hub (if present). Element type includes both keys so
      //    subscribers can recover which entry was replaced.
      this.#hub?.send(
        CollectionChangedMessage.forReplace<DictionaryEntry<TKey1, TKey2, TValue>>(
          this,
          { key1, key2, value },
          { key1, key2, value: oldValue },
          -1,
        ),
      );
    } else {
      this.#internalAdd(key1, key2, value);
    }
  }

  /**
   * Strict-insert an entry.
   * Throws Error if key1 or key2 is null/undefined.
   * Throws Error if the key pair already exists (use {@link set} for upsert behaviour).
   *
   * Mirrors `Add()` in C# and `add()` in Python, which both throw on duplicate keys.
   */
  add(key1: TKey1, key2: TKey2, value: TValue): void {
    this.#requireKeys(key1, key2);
    if (this.#entryAt(key1, key2) !== undefined) {
      throw new Error(`Key (${String(key1)}, ${String(key2)}) already exists`);
    }
    this.#internalAdd(key1, key2, value);
  }

  /**
   * Remove the entry for (key1, key2).
   * Returns true if found and removed, false if absent.
   */
  delete(key1: TKey1, key2: TKey2): boolean {
    this.#requireKeys(key1, key2);
    const bucket = this.#data.get(key1);
    const entry = bucket?.get(key2);
    if (entry === undefined) return false;

    const value = entry.value;
    bucket?.delete(key2);
    if (bucket?.size === 0) this.#data.delete(key1);
    const orderIndex = this.#keyOrder.indexOf(entry);
    if (orderIndex < 0) {
      throw new Error(
        "ObservableDictionary invariant violated: entry missing from insertion order",
      );
    }
    this.#keyOrder.splice(orderIndex, 1);

    // Update key-axis views: decrement refcount; drop from list when count reaches 0.
    const newKey1Count = (this.#key1Counts.get(key1) ?? 1) - 1;
    if (newKey1Count <= 0) {
      this.#key1Counts.delete(key1);
      this.#removeAxisKey(this.#keys1, key1);
    } else {
      this.#key1Counts.set(key1, newKey1Count);
    }

    const newKey2Count = (this.#key2Counts.get(key2) ?? 1) - 1;
    if (newKey2Count <= 0) {
      this.#key2Counts.delete(key2);
      this.#removeAxisKey(this.#keys2, key2);
    } else {
      this.#key2Counts.set(key2, newKey2Count);
    }

    // 1. Local granular event first.
    this.#itemRemoved.next({ key1, key2, value });
    // 2. Publish to hub (if present). Element type includes both keys so
    //    subscribers can recover which entry was removed.
    this.#hub?.send(
      CollectionChangedMessage.forRemove<DictionaryEntry<TKey1, TKey2, TValue>>(
        this,
        { key1, key2, value },
        -1,
      ),
    );
    return true;
  }

  /**
   * Get the value for (key1, key2).
   * Returns undefined if absent.
   */
  get(key1: TKey1, key2: TKey2): TValue | undefined {
    this.#requireKeys(key1, key2);
    return this.#entryAt(key1, key2)?.value;
  }

  /**
   * Try to get the value for (key1, key2).
   * Returns { found: true, value } if found, { found: false, value: undefined } if absent.
   */
  tryGetValue(
    key1: TKey1,
    key2: TKey2,
  ): { found: boolean; value: TValue | undefined } {
    this.#requireKeys(key1, key2);
    const entry = this.#entryAt(key1, key2);
    if (entry !== undefined) {
      return { found: true, value: entry.value };
    }
    return { found: false, value: undefined };
  }

  /** Returns true if an entry exists for (key1, key2). */
  has(key1: TKey1, key2: TKey2): boolean {
    this.#requireKeys(key1, key2);
    return this.#entryAt(key1, key2) !== undefined;
  }

  /** Remove all entries and emit reset. Does NOT fire per-entry itemRemoved events. */
  clear(): void {
    this.#data.clear();
    this.#keyOrder.length = 0;
    this.#key1Counts.clear();
    this.#key2Counts.clear();
    this.#keys1.clear();
    this.#keys2.clear();
    // 1. Local event first.
    this.#reset.next();
    // 2. Publish to hub (if present).
    this.#hub?.send(CollectionChangedMessage.forReset(this));
  }

  // ── Enumeration ──────────────────────────────────────────────────────────────

  /**
   * Iterate entries in insertion order.
   * Each item is [key1, key2, value].
   */
  [Symbol.iterator](): IterableIterator<[TKey1, TKey2, TValue]> {
    const keyOrder = this.#keyOrder;
    let index = 0;
    return {
      next(): IteratorResult<[TKey1, TKey2, TValue]> {
        if (index >= keyOrder.length) return { done: true, value: undefined };
        const entry = keyOrder[index++];
        if (entry === undefined) {
          throw new Error(
            "ObservableDictionary invariant violated: missing ordered entry",
          );
        }
        return {
          done: false,
          value: [entry.key1, entry.key2, entry.value],
        };
      },
      [Symbol.iterator]() {
        return this;
      },
    };
  }

  // ── Internal ─────────────────────────────────────────────────────────────────

  #entryAt(
    key1: TKey1,
    key2: TKey2,
  ): StoredDictionaryEntry<TKey1, TKey2, TValue> | undefined {
    return this.#data.get(key1)?.get(key2);
  }

  #removeAxisKey<Key>(keys: ObservableList<Key>, key: Key): void {
    let index = 0;
    for (const candidate of keys) {
      if (sameValueZero(candidate, key)) {
        keys.removeAt(index);
        return;
      }
      index += 1;
    }
    throw new Error(
      "ObservableDictionary invariant violated: counted key missing from axis view",
    );
  }

  #internalAdd(
    key1: TKey1,
    key2: TKey2,
    value: TValue,
  ): void {
    const entry: StoredDictionaryEntry<TKey1, TKey2, TValue> = {
      key1,
      key2,
      value,
    };
    this.#keyOrder.push(entry);
    let bucket = this.#data.get(key1);
    if (bucket === undefined) {
      bucket = new Map();
      this.#data.set(key1, bucket);
    }
    bucket.set(key2, entry);

    // Update key-axis views and refcounts: push to list only on first appearance.
    const key1Count = this.#key1Counts.get(key1) ?? 0;
    this.#key1Counts.set(key1, key1Count + 1);
    if (key1Count === 0) this.#keys1.push(key1);

    const key2Count = this.#key2Counts.get(key2) ?? 0;
    this.#key2Counts.set(key2, key2Count + 1);
    if (key2Count === 0) this.#keys2.push(key2);

    // 1. Local granular event first.
    this.#itemAdded.next({ key1, key2, value });
    // 2. Publish to hub (if present). Element type includes both keys + value
    //    so hub subscribers can recover the full identity of the added entry.
    this.#hub?.send(
      CollectionChangedMessage.forAdd<DictionaryEntry<TKey1, TKey2, TValue>>(
        this,
        { key1, key2, value },
        this.#keyOrder.length - 1,
      ),
    );
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
