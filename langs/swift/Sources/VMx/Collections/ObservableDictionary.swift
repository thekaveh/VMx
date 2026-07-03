//
// ObservableDictionary<TKey1, TKey2, TValue> — two-key observable dictionary.
//
// See spec/21-collections.md §4 and ADR-0025.
// Conforms to: COL-010, COL-011, COL-012, COL-013, COL-014, COL-015, COL-022.
//
// Entries are stored in insertion order (an `[CompositeKey]` order list backs
// enumeration — COL-014). Four Combine subjects surface mutations:
//   - itemAdded     — emits { key1, key2, value } on insert
//   - itemRemoved   — emits { key1, key2, value } on remove
//   - itemReplaced  — emits { key1, key2, newValue, oldValue } on replace
//   - reset         — emits Void on clear
//
// `keys1` / `keys2` are live `ObservableList` views of the *distinct* Key1 /
// Key2 values currently present, in first-appearance insertion order. A
// distinct key is appended on first appearance and dropped from its view when
// its LAST entry is removed (refcount-tracked — COL-013).
//
// Hub publication (COL-022): when a hub is injected, each mutation fires the
// local granular event FIRST, then sends a `CollectionChangedMessage` carrying
// a `DictionaryEntry` (both keys + value) so subscribers can recover the full
// identity of the mutated entry. A nil hub is a structural no-op (no error).
//
// Swift null-key divergence (for ADR-0060): the TS / C# / Python flavors guard
// against null/undefined keys with a runtime precondition. In Swift the generic
// key parameters `TKey1` / `TKey2` are *non-optional by type* — a `nil` cannot
// be passed unless the caller explicitly instantiates `TKey` as an Optional.
// The null-key precondition is therefore satisfied structurally by the type
// system; no runtime nil-check is added here (it would be dead code). This is a
// catalogued cross-flavor divergence per ADR-0009 / ADR-0037.
//
import Foundation
import Combine

// MARK: — Event payload shapes

/// Payload emitted by `ObservableDictionary.itemAdded` on insert.
public struct DictionaryItemAddedEvent<TKey1, TKey2, TValue> {
    public let key1: TKey1
    public let key2: TKey2
    public let value: TValue
}

/// Payload emitted by `ObservableDictionary.itemRemoved` on remove.
public struct DictionaryItemRemovedEvent<TKey1, TKey2, TValue> {
    public let key1: TKey1
    public let key2: TKey2
    public let value: TValue
}

/// Payload emitted by `ObservableDictionary.itemReplaced` when an existing
/// entry's value is replaced in place.
public struct DictionaryItemReplacedEvent<TKey1, TKey2, TValue> {
    public let key1: TKey1
    public let key2: TKey2
    public let newValue: TValue
    public let oldValue: TValue
}

/// The element type carried in hub `CollectionChangedMessage` publications from
/// `ObservableDictionary`. Both keys and the value are included so subscribers
/// can recover the full identity of the mutated entry.
///
/// C# equivalent: `KeyValuePair<(TKey1, TKey2), TValue>`;
/// Python / TypeScript equivalent: `(key1, key2, value)`. Per ADR-0006 each
/// shape is flavor-idiomatic; per ADR-0009 the divergence is catalogued.
public struct DictionaryEntry<TKey1, TKey2, TValue> {
    public let key1: TKey1
    public let key2: TKey2
    public let value: TValue

    public init(key1: TKey1, key2: TKey2, value: TValue) {
        self.key1 = key1
        self.key2 = key2
        self.value = value
    }
}

// MARK: — ObservableDictionary

/// A two-key observable dictionary (`TKey1 × TKey2 → TValue`) with live
/// distinct-key views and granular per-mutation events.
///
/// Storage is a composite-key map (`[CompositeKey: TValue]`) plus an
/// insertion-order list of composite keys (`keyOrder`) so enumeration is
/// stable and insertion-ordered (COL-014). `keys1` / `keys2` are live
/// `ObservableList` views of the distinct key values, refcount-maintained so a
/// distinct key drops from its view only when its last entry is removed
/// (COL-013).
/// Error thrown by ``ObservableDictionary/add(_:_:_:)`` when a strict insert
/// targets a key pair that already exists — parity with C#/Python/TS, which throw
/// on a duplicate (`set(_:_:_:)` upserts instead).
public enum ObservableDictionaryError: Error, CustomStringConvertible {
    case duplicateKey(key1: String, key2: String)

    public var description: String {
        switch self {
        case let .duplicateKey(key1, key2):
            return "ObservableDictionary: key (\(key1), \(key2)) already exists."
        }
    }
}

public final class ObservableDictionary<TKey1: Hashable, TKey2: Hashable, TValue> {

    /// Composite map key combining both axes. Synthesised `Hashable` because
    /// both `TKey1` and `TKey2` are `Hashable`.
    private struct CompositeKey: Hashable {
        let k1: TKey1
        let k2: TKey2
    }

    // MARK: - Private state

    private let hub: (any MessageHubProtocol)?
    private let typeName = "ObservableDictionary"

    /// Insertion-ordered list of composite keys (backs enumeration — COL-014).
    private var keyOrder: [CompositeKey] = []
    /// Composite-key → value store.
    private var data: [CompositeKey: TValue] = [:]

    /// Reference counts for distinct Key1 values (O(1) key-axis upkeep).
    private var key1Counts: [TKey1: Int] = [:]
    /// Reference counts for distinct Key2 values (O(1) key-axis upkeep).
    private var key2Counts: [TKey2: Int] = [:]

    /// Live distinct-key views.
    private let keys1View = ObservableList<TKey1>()
    private let keys2View = ObservableList<TKey2>()

    // MARK: - Private subjects

    private let itemAddedSubject =
        PassthroughSubject<DictionaryItemAddedEvent<TKey1, TKey2, TValue>, Never>()
    private let itemRemovedSubject =
        PassthroughSubject<DictionaryItemRemovedEvent<TKey1, TKey2, TValue>, Never>()
    private let itemReplacedSubject =
        PassthroughSubject<DictionaryItemReplacedEvent<TKey1, TKey2, TValue>, Never>()
    private let resetSubject = PassthroughSubject<Void, Never>()

    // MARK: - Initializer

    /// Create a new ObservableDictionary.
    ///
    /// - Parameter hub: Optional hub. Pass `nil` (the default) for standalone
    ///   (no-publication) mode; mutations still fire local granular events.
    public init(hub: (any MessageHubProtocol)? = nil) {
        self.hub = hub
    }

    // MARK: - Public publishers

    /// Emits when an entry is added. Payload: `{ key1, key2, value }`.
    public var itemAdded: AnyPublisher<DictionaryItemAddedEvent<TKey1, TKey2, TValue>, Never> {
        itemAddedSubject.eraseToAnyPublisher()
    }

    /// Emits when an entry is removed. Payload: `{ key1, key2, value }`.
    public var itemRemoved: AnyPublisher<DictionaryItemRemovedEvent<TKey1, TKey2, TValue>, Never> {
        itemRemovedSubject.eraseToAnyPublisher()
    }

    /// Emits when an existing entry's value is replaced. Payload:
    /// `{ key1, key2, newValue, oldValue }`.
    public var itemReplaced: AnyPublisher<DictionaryItemReplacedEvent<TKey1, TKey2, TValue>, Never> {
        itemReplacedSubject.eraseToAnyPublisher()
    }

    /// Emits (`Void`) on `clear()`.
    public var reset: AnyPublisher<Void, Never> {
        resetSubject.eraseToAnyPublisher()
    }

    // MARK: - Key-axis views

    /// Live observable view of distinct Key1 values, in first-appearance
    /// insertion order.
    public var keys1: ObservableList<TKey1> { keys1View }

    /// Live observable view of distinct Key2 values, in first-appearance
    /// insertion order.
    public var keys2: ObservableList<TKey2> { keys2View }

    // MARK: - Size

    /// Total number of entries.
    public var size: Int { data.count }

    // MARK: - Reads

    /// Get the value for `(key1, key2)`, or `nil` if absent.
    public func get(_ key1: TKey1, _ key2: TKey2) -> TValue? {
        data[CompositeKey(k1: key1, k2: key2)]
    }

    /// Returns `true` if an entry exists for `(key1, key2)`.
    public func has(_ key1: TKey1, _ key2: TKey2) -> Bool {
        data[CompositeKey(k1: key1, k2: key2)] != nil
    }

    // MARK: - Mutations

    /// Insert or replace an entry (upsert).
    ///
    /// If the key pair already exists, the value is replaced and `itemReplaced`
    /// fires (NOT add/remove — COL-012). Otherwise the pair is added and
    /// `itemAdded` fires.
    public func set(_ key1: TKey1, _ key2: TKey2, _ value: TValue) {
        let key = CompositeKey(k1: key1, k2: key2)
        if let oldValue = data[key] {
            // Existing pair → replace in place. Keys are unchanged, so the
            // key-axis views and order list are untouched.
            data[key] = value
            // 1. Local granular event first (COL-022 ordering).
            itemReplacedSubject.send(
                DictionaryItemReplacedEvent(key1: key1, key2: key2,
                                            newValue: value, oldValue: oldValue))
            // 2. Hub publication (no-op when hub is nil).
            hub?.send(
                CollectionChangedMessage.forReplace(
                    sender: self, senderName: typeName,
                    newItem: DictionaryEntry(key1: key1, key2: key2, value: value),
                    oldItem: DictionaryEntry(key1: key1, key2: key2, value: oldValue),
                    index: -1))
        } else {
            internalAdd(key, key1: key1, key2: key2, value: value)
        }
    }

    /// Strict insert: add `value` under `(key1, key2)`, throwing
    /// ``ObservableDictionaryError/duplicateKey(key1:key2:)`` when the pair is
    /// already present (unlike ``set(_:_:_:)``, which upserts). Emits `itemAdded`
    /// (local then hub) on success — parity with the canonical
    /// `Add(key1, key2, value)` (spec/21 §4.1), which throws on a duplicate in the
    /// other flavors.
    public func add(_ key1: TKey1, _ key2: TKey2, _ value: TValue) throws {
        let key = CompositeKey(k1: key1, k2: key2)
        guard data[key] == nil else {
            throw ObservableDictionaryError.duplicateKey(key1: "\(key1)", key2: "\(key2)")
        }
        internalAdd(key, key1: key1, key2: key2, value: value)
    }

    /// Remove the entry for `(key1, key2)`.
    ///
    /// - Returns: `true` if found and removed, `false` if absent.
    @discardableResult
    public func delete(_ key1: TKey1, _ key2: TKey2) -> Bool {
        let key = CompositeKey(k1: key1, k2: key2)
        guard let value = data[key] else { return false }

        data[key] = nil
        if let idx = keyOrder.firstIndex(of: key) {
            keyOrder.remove(at: idx)
        }

        // Update key-axis views: decrement refcount; drop from the live view
        // when the count reaches zero (last entry for that distinct key).
        let newKey1Count = (key1Counts[key1] ?? 1) - 1
        if newKey1Count <= 0 {
            key1Counts[key1] = nil
            removeFromView(keys1View, key1)
        } else {
            key1Counts[key1] = newKey1Count
        }

        let newKey2Count = (key2Counts[key2] ?? 1) - 1
        if newKey2Count <= 0 {
            key2Counts[key2] = nil
            removeFromView(keys2View, key2)
        } else {
            key2Counts[key2] = newKey2Count
        }

        // 1. Local granular event first (COL-022 ordering).
        itemRemovedSubject.send(
            DictionaryItemRemovedEvent(key1: key1, key2: key2, value: value))
        // 2. Hub publication (no-op when hub is nil).
        hub?.send(
            CollectionChangedMessage.forRemove(
                sender: self, senderName: typeName,
                item: DictionaryEntry(key1: key1, key2: key2, value: value),
                index: -1))
        return true
    }

    /// Remove all entries, empty both key views, and emit `reset`.
    ///
    /// Does NOT fire per-entry `itemRemoved` events (COL-015); the clear is a
    /// single coarse-grained reset.
    public func clear() {
        keyOrder.removeAll()
        data.removeAll()
        key1Counts.removeAll()
        key2Counts.removeAll()
        keys1View.clear()
        keys2View.clear()
        // 1. Local event first (COL-022 ordering).
        resetSubject.send(())
        // 2. Hub publication (no-op when hub is nil).
        hub?.send(
            CollectionChangedMessage<DictionaryEntry<TKey1, TKey2, TValue>>.forReset(
                sender: self, senderName: typeName))
    }

    // MARK: - Enumeration

    /// Entries in insertion order (COL-014). Each element is a labelled tuple
    /// `(key1, key2, value)`.
    public func entries() -> [(key1: TKey1, key2: TKey2, value: TValue)] {
        var result: [(key1: TKey1, key2: TKey2, value: TValue)] = []
        result.reserveCapacity(keyOrder.count)
        for key in keyOrder {
            guard let value = data[key] else { continue }
            result.append((key1: key.k1, key2: key.k2, value: value))
        }
        return result
    }

    // MARK: - Private helpers

    private func internalAdd(_ key: CompositeKey, key1: TKey1, key2: TKey2, value: TValue) {
        keyOrder.append(key)
        data[key] = value

        // Update key-axis views and refcounts: append to the live view only on
        // first appearance of a distinct key.
        let key1Count = key1Counts[key1] ?? 0
        key1Counts[key1] = key1Count + 1
        if key1Count == 0 { keys1View.append(key1) }

        let key2Count = key2Counts[key2] ?? 0
        key2Counts[key2] = key2Count + 1
        if key2Count == 0 { keys2View.append(key2) }

        // 1. Local granular event first (COL-022 ordering).
        itemAddedSubject.send(
            DictionaryItemAddedEvent(key1: key1, key2: key2, value: value))
        // 2. Hub publication (no-op when hub is nil). Index is the insertion
        //    position in the order list.
        hub?.send(
            CollectionChangedMessage.forAdd(
                sender: self, senderName: typeName,
                item: DictionaryEntry(key1: key1, key2: key2, value: value),
                index: keyOrder.count - 1))
    }

    /// Remove the first occurrence of `key` from a live key view (by value).
    /// No-op if the key is not currently present.
    private func removeFromView<K: Equatable>(_ list: ObservableList<K>, _ key: K) {
        if let idx = list.toArray().firstIndex(of: key) {
            list.removeAt(idx)
        }
    }
}

// MARK: — Sequence conformance (insertion-order enumeration, COL-014)

extension ObservableDictionary: Sequence {
    public func makeIterator() -> IndexingIterator<[(key1: TKey1, key2: TKey2, value: TValue)]> {
        entries().makeIterator()
    }
}
