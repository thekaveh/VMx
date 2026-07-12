/**
 * Ordered serviced collection with expected O(1) captured-key lookup.
 *
 * Items remain caller-owned. Every mutation settles the ordered items,
 * captured keys, and key-to-index map before local and optional hub delivery.
 *
 * See spec/21-collections.md §§2.8–2.15 and ADR-0097.
 */
import { Observable, Subject } from "rxjs";
import type { IMessageHub } from "../services/messageHub.js";
import { CollectionChangedMessage } from "../messages/collectionChanged.js";

export interface KeyedServicedObservableCollectionOptions<TKey, TItem> {
  readonly keyOf: (item: TItem) => TKey;
  readonly hub?: IMessageHub | null;
}

export class KeyedServicedObservableCollection<TKey, TItem> {
  readonly #keyOf: (item: TItem) => TKey;
  readonly #hub: IMessageHub | null;
  readonly #subject = new Subject<CollectionChangedMessage<TItem>>();
  #items: TItem[] = [];
  #keys: TKey[] = [];
  #indexByKey = new Map<TKey, number>();

  constructor(options: KeyedServicedObservableCollectionOptions<TKey, TItem>) {
    this.#keyOf = options.keyOf;
    this.#hub = options.hub ?? null;
  }

  get collectionChanged(): Observable<CollectionChangedMessage<TItem>> {
    return this.#subject.asObservable();
  }

  get length(): number {
    return this.#items.length;
  }

  at(index: number): TItem | undefined {
    return this.#items[index];
  }

  toArray(): TItem[] {
    return [...this.#items];
  }

  [Symbol.iterator](): IterableIterator<TItem> {
    return this.#items[Symbol.iterator]();
  }

  get(key: TKey): TItem | undefined {
    const index = this.#indexByKey.get(key);
    return index === undefined ? undefined : this.#items[index];
  }

  has(key: TKey): boolean {
    return this.#indexByKey.has(key);
  }

  push(item: TItem): void {
    const key = this.#keyOf(item);
    this.#throwIfDuplicate(key);
    const index = this.#items.length;
    this.#items.push(item);
    this.#keys.push(key);
    this.#indexByKey.set(key, index);
    this.#emit(CollectionChangedMessage.forAdd(this, item, index));
  }

  pop(): TItem | undefined {
    if (this.#items.length === 0) return undefined;
    const index = this.#items.length - 1;
    const item = this.#items[index] as TItem;
    const key = this.#keys[index] as TKey;
    this.#items.pop();
    this.#keys.pop();
    this.#indexByKey.delete(key);
    this.#emit(CollectionChangedMessage.forRemove(this, item, index));
    return item;
  }

  remove(item: TItem): boolean {
    const index = this.#items.indexOf(item);
    if (index === -1) return false;
    this.#removeAt(index);
    return true;
  }

  removeAt(index: number): void {
    this.#validateIndex(index);
    this.#removeAt(index);
  }

  delete(key: TKey): boolean {
    const index = this.#indexByKey.get(key);
    if (index === undefined) return false;
    this.#removeAt(index);
    return true;
  }

  /**
   * Apply native Array.splice normalization to an atomic candidate state.
   * Retained memberships keep their captured keys; inserted items are projected
   * once before commit and may reuse keys removed by the same operation.
   */
  splice(start: number, deleteCount?: number, ...newItems: TItem[]): TItem[] {
    const deleteCountProvided = arguments.length >= 2;
    const insertedKeys = newItems.map((item) => this.#keyOf(item));
    const candidateItems = [...this.#items];
    const candidateKeys = [...this.#keys];
    const resolvedStart = resolveSpliceStart(start, candidateItems.length);
    let removedItems: TItem[];

    if (deleteCountProvided) {
      const effectiveDeleteCount = deleteCount ?? 0;
      removedItems = candidateItems.splice(start, effectiveDeleteCount, ...newItems);
      candidateKeys.splice(start, effectiveDeleteCount, ...insertedKeys);
    } else {
      removedItems = candidateItems.splice(start);
      candidateKeys.splice(start);
    }

    const candidateIndex = this.#buildIndex(candidateKeys);
    if (removedItems.length === 0 && newItems.length === 0) return removedItems;

    this.#items = candidateItems;
    this.#keys = candidateKeys;
    this.#indexByKey = candidateIndex;
    if (removedItems.length === 1 && newItems.length === 0) {
      this.#emit(
        CollectionChangedMessage.forRemove(
          this,
          removedItems[0] as TItem,
          resolvedStart,
        ),
      );
    } else {
      this.#emit(CollectionChangedMessage.forReset(this));
    }
    return removedItems;
  }

  replace(index: number, newItem: TItem): void {
    this.#validateIndex(index);
    const newKey = this.#keyOf(newItem);
    const owner = this.#indexByKey.get(newKey);
    if (owner !== undefined && owner !== index) this.#throwDuplicate();
    this.#replaceAt(index, newItem, newKey);
  }

  setAt(index: number, newItem: TItem): void {
    this.replace(index, newItem);
  }

  replaceAll(items: Iterable<TItem>): void {
    const snapshot = [...items];
    const keys = snapshot.map((item) => this.#keyOf(item));
    const indexByKey = this.#buildIndex(keys);
    if (this.#items.length === 0 && snapshot.length === 0) return;

    this.#items = snapshot;
    this.#keys = keys;
    this.#indexByKey = indexByKey;
    this.#emit(CollectionChangedMessage.forReset(this));
  }

  move(fromIndex: number, toIndex: number): void {
    this.#validateIndex(fromIndex);
    this.#validateIndex(toIndex);
    if (fromIndex === toIndex) return;

    const item = this.#items[fromIndex] as TItem;
    const key = this.#keys[fromIndex] as TKey;
    this.#items.splice(fromIndex, 1);
    this.#keys.splice(fromIndex, 1);
    this.#items.splice(toIndex, 0, item);
    this.#keys.splice(toIndex, 0, key);
    this.#indexByKey = this.#buildIndex(this.#keys);
    this.#emit(
      CollectionChangedMessage.forMove(this, item, fromIndex, toIndex),
    );
  }

  clear(): void {
    if (this.#items.length === 0) return;
    this.#items = [];
    this.#keys = [];
    this.#indexByKey = new Map<TKey, number>();
    this.#emit(CollectionChangedMessage.forReset(this));
  }

  upsert(item: TItem): boolean {
    const key = this.#keyOf(item);
    const index = this.#indexByKey.get(key);
    if (index === undefined) {
      const insertionIndex = this.#items.length;
      this.#items.push(item);
      this.#keys.push(key);
      this.#indexByKey.set(key, insertionIndex);
      this.#emit(CollectionChangedMessage.forAdd(this, item, insertionIndex));
      return true;
    }

    this.#replaceAt(index, item, key);
    return false;
  }

  #removeAt(index: number): void {
    const item = this.#items[index] as TItem;
    this.#items.splice(index, 1);
    this.#keys.splice(index, 1);
    this.#indexByKey = this.#buildIndex(this.#keys);
    this.#emit(CollectionChangedMessage.forRemove(this, item, index));
  }

  #replaceAt(index: number, newItem: TItem, newKey: TKey): void {
    const oldItem = this.#items[index] as TItem;
    const oldKey = this.#keys[index] as TKey;
    this.#items[index] = newItem;
    this.#keys[index] = newKey;
    this.#indexByKey.delete(oldKey);
    this.#indexByKey.set(newKey, index);
    this.#emit(
      CollectionChangedMessage.forReplace(this, newItem, oldItem, index),
    );
  }

  #buildIndex(keys: readonly TKey[]): Map<TKey, number> {
    const result = new Map<TKey, number>();
    keys.forEach((key, index) => {
      if (result.has(key)) this.#throwDuplicate();
      result.set(key, index);
    });
    return result;
  }

  #throwIfDuplicate(key: TKey): void {
    if (this.#indexByKey.has(key)) this.#throwDuplicate();
  }

  #throwDuplicate(): never {
    throw new Error("Duplicate key in KeyedServicedObservableCollection");
  }

  #emit(message: CollectionChangedMessage<TItem>): void {
    this.#subject.next(message);
    this.#hub?.send(message);
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

function resolveSpliceStart(start: number, length: number): number {
  const integer = toIntegerOrInfinity(start);
  if (integer < 0) return Math.max(length + integer, 0);
  return Math.min(integer, length);
}

function toIntegerOrInfinity(value: number): number {
  if (Number.isNaN(value) || value === 0) return 0;
  if (!Number.isFinite(value)) return value;
  return Math.trunc(value);
}
