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

/**
 * Decrements the count of `key` and drops `key` when no entry uses it.
 * Returns true when `key` was dropped.
 */
function release<Key>(counts: Map<Key, number>, key: Key): boolean {
  const count = counts.get(key) ?? 1;
  if (count > 1) {
    counts.set(key, count - 1);
    return false;
  }
  counts.delete(key);
  return true;
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
  /**
   * Changes on every add, remove, and clear, so an add can tell whether a
   * key-view subscriber changed the entries during its notification.
   */
  #version = 0;
  /**
   * Counts the deletes and clears that notify keys2 now. keys1 can then still
   * list a key that no entry uses, so an add checks keys1 first (#1075).
   */
  #removalsNotifyingKeys2 = 0;

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
    this.#version += 1;

    // Count both axes before either key view notifies: drop a key from its
    // view only when its count reaches 0.
    const dropKey1 = release(this.#key1Counts, key1);
    const dropKey2 = release(this.#key2Counts, key2);

    // Keys2 first, so a keys1 subscriber sees the updated keys2, as on add (#1075).
    if (dropKey2) {
      this.#notifyKeys2(() => this.#removeAxisKey(this.#keys2, key2));
    }
    if (dropKey1) this.#removeKey1(key1);

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
    this.#version += 1;
    this.#key1Counts.clear();
    this.#key2Counts.clear();
    // Keys2 first, so a keys1 subscriber sees the cleared keys2, as on add (#1075).
    this.#notifyKeys2(() => this.#keys2.clear());
    this.#clearKeys1();
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

  /**
   * Appends `key1` unless a keys2 subscriber changed the entries, or a delete
   * or clear notifies keys2 now. Then `#listKey1` decides.
   */
  #addKey1(key1: TKey1, version: number): void {
    if (version === this.#version && this.#removalsNotifyingKeys2 === 0) {
      this.#keys1.push(key1);
      return;
    }
    this.#listKey1(key1);
  }

  /**
   * Lists `key1` only while an entry still uses it and keys1 does not list it
   * yet, at `#key1Position`.
   */
  #listKey1(key1: TKey1): void {
    if (!this.#key1Counts.has(key1)) return;
    for (const listed of this.#keys1) if (sameValueZero(listed, key1)) return;
    this.#keys1.insert(this.#key1Position(key1), key1);
  }

  /**
   * Unlists `key1` when no entry uses it. If a keys2 subscriber added an entry
   * with `key1`, `key1` stays listed and moves to `#key1Position` (#1075).
   */
  #removeKey1(key1: TKey1): void {
    if (!this.#key1Counts.has(key1)) {
      this.#removeAxisKey(this.#keys1, key1);
      return;
    }
    let listed = -1;
    let index = 0;
    for (const candidate of this.#keys1) {
      if (sameValueZero(candidate, key1)) {
        listed = index;
        break;
      }
      index += 1;
    }
    if (listed === this.#key1Position(key1)) return;
    if (listed >= 0) this.#keys1.removeAt(listed);
    // The removal notifies keys1, and a subscriber can change the entries.
    this.#listKey1(key1);
  }

  /**
   * Empties keys1 unless a keys2 subscriber added entries. Then keys1 lists
   * their key1 values in first-appearance order, with at most one reset
   * (#1075).
   */
  #clearKeys1(): void {
    if (this.#keyOrder.length === 0) {
      this.#keys1.clear();
      return;
    }
    const keys = [...new Set(this.#keyOrder.map((entry) => entry.key1))];
    const listed = this.#keys1.toArray();
    if (
      listed.length !== keys.length ||
      listed.some((key, index) => !sameValueZero(key, keys[index]))
    ) {
      this.#keys1.replaceAll(keys);
    }
  }

  /**
   * The keys1 index for `key1`, counted without `key1`: after every listed key
   * that has an entry before `key1`'s first entry.
   */
  #key1Position(key1: TKey1): number {
    const earlier = new Set<TKey1>();
    for (const entry of this.#keyOrder) {
      if (sameValueZero(entry.key1, key1)) break;
      earlier.add(entry.key1);
    }
    let position = 0;
    let index = 0;
    for (const listed of this.#keys1) {
      if (sameValueZero(listed, key1)) continue;
      index += 1;
      if (earlier.has(listed)) position = index;
    }
    return position;
  }

  /** Runs a keys2 change of a delete or clear. keys1 can lag behind it. */
  #notifyKeys2(change: () => void): void {
    this.#removalsNotifyingKeys2 += 1;
    try {
      change();
    } finally {
      this.#removalsNotifyingKeys2 -= 1;
    }
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
    // A key counted by an add whose keys2 subscriber removes the entry is not
    // listed yet (#772).
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
    // Capture the position now: a key-view or local subscriber may add another entry.
    const index = this.#keyOrder.length - 1;
    let bucket = this.#data.get(key1);
    if (bucket === undefined) {
      bucket = new Map();
      this.#data.set(key1, bucket);
    }
    bucket.set(key2, entry);
    const version = ++this.#version;

    // Count both axes before either key view notifies.
    const key1Count = this.#key1Counts.get(key1) ?? 0;
    this.#key1Counts.set(key1, key1Count + 1);
    const key2Count = this.#key2Counts.get(key2) ?? 0;
    this.#key2Counts.set(key2, key2Count + 1);

    // Keys2 first, so a keys1 subscriber sees the new key2 and cannot put
    // keys2 out of first-appearance order (#772).
    if (key2Count === 0) this.#keys2.push(key2);
    if (key1Count === 0) this.#addKey1(key1, version);

    // 1. Local granular event first.
    this.#itemAdded.next({ key1, key2, value });
    // 2. Publish to hub (if present). Element type includes both keys + value
    //    so hub subscribers can recover the full identity of the added entry.
    this.#hub?.send(
      CollectionChangedMessage.forAdd<DictionaryEntry<TKey1, TKey2, TValue>>(
        this,
        { key1, key2, value },
        this.#currentIndex(key1, key2, index),
      ),
    );
  }

  // The key pair's position now: a subscriber may have removed an entry or cleared.
  #currentIndex(key1: TKey1, key2: TKey2, index: number): number {
    const current = this.#data.get(key1)?.get(key2);
    if (current === undefined) return -1;
    return this.#keyOrder[index] === current ? index : this.#keyOrder.indexOf(current);
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
