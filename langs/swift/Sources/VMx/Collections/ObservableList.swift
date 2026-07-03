//
// ObservableList.swift — generic observable list with granular per-mutation events.
//
// See spec/21-collections.md §3 and ADR-0026.
// Conforms to: COL-005, COL-006, COL-007, COL-008, COL-009, COL-023.
//
// NOTE: `propertyChanged` emits the literal string "Count" (capital C) —
// a spec-documented cross-flavor exception (spec/21 §3.3 and CLAUDE.md).
// The Swift property is `count` (idiom) but the event channel string is "Count".
//

import Combine

// MARK: — Event payload shapes

/// Payload emitted by `ObservableList.itemAdded` on append / insert.
public struct ItemAddedEvent<T> {
    public let item: T
    /// Index at which the item was inserted.
    public let index: Int
}

/// Payload emitted by `ObservableList.itemRemoved` on removal.
public struct ItemRemovedEvent<T> {
    public let item: T
    /// Index of the item **before** it was removed.
    public let index: Int
}

/// Payload emitted by `ObservableList.itemReplaced` on in-place replacement.
public struct ItemReplacedEvent<T> {
    public let newItem: T
    public let oldItem: T
    /// Index of the replaced item.
    public let index: Int
}

// MARK: — ObservableList

/// A generic observable list that emits strongly-typed per-mutation events.
///
/// Ordering (COL-008): the granular event (`itemAdded`, `itemRemoved`,
/// `itemReplaced`) always fires **before** `propertyChanged("Count")`.
///
/// Batch support (COL-009, COL-023): `withBatch(_:)` raises a batch level;
/// while inside, granular events and `propertyChanged("Count")` are suppressed.
/// On the outermost batch exit:
///   - If no mutations occurred: nothing is emitted.
///   - If mutations occurred: `reset` fires; if the count also changed,
///     `propertyChanged("Count")` fires after `reset`.
///
/// The `propertyChanged` channel string is the spec-literal **`"Count"`**
/// (not the Swift-idiomatic `"count"`). This is a documented cross-flavor
/// exception per spec/21 §3.3.
public final class ObservableList<T> {

    // MARK: - Private state

    private var items: [T] = []
    private var batchDepth = 0
    private var mutatedInBatch = false
    private var countAtBatchStart = 0

    // MARK: - Private subjects

    private let itemAddedSubject = PassthroughSubject<ItemAddedEvent<T>, Never>()
    private let itemRemovedSubject = PassthroughSubject<ItemRemovedEvent<T>, Never>()
    private let itemReplacedSubject = PassthroughSubject<ItemReplacedEvent<T>, Never>()
    private let resetSubject = PassthroughSubject<Void, Never>()
    private let propertyChangedSubject = PassthroughSubject<String, Never>()

    // MARK: - Public publishers

    /// Emits when an item is added. Payload: `{ item, index }`.
    public var itemAdded: AnyPublisher<ItemAddedEvent<T>, Never> {
        itemAddedSubject.eraseToAnyPublisher()
    }

    /// Emits when an item is removed. Payload: `{ item, index }` (index before removal).
    public var itemRemoved: AnyPublisher<ItemRemovedEvent<T>, Never> {
        itemRemovedSubject.eraseToAnyPublisher()
    }

    /// Emits when an item is replaced. Payload: `{ newItem, oldItem, index }`.
    public var itemReplaced: AnyPublisher<ItemReplacedEvent<T>, Never> {
        itemReplacedSubject.eraseToAnyPublisher()
    }

    /// Emits (`Void`) on `clear()` or when a batch completes with mutations.
    public var reset: AnyPublisher<Void, Never> {
        resetSubject.eraseToAnyPublisher()
    }

    /// Emits the property name whenever a property changes.
    ///
    /// Emits `"Count"` (spec-literal — **not** `"count"`) after every add and
    /// remove. Ordering: granular event fires before `propertyChanged("Count")`.
    public var propertyChanged: AnyPublisher<String, Never> {
        propertyChangedSubject.eraseToAnyPublisher()
    }

    // MARK: - Accessors

    /// The number of items in the list. (The *event channel* string is `"Count"` — spec literal.)
    public var count: Int { items.count }

    /// Returns the item at `index`, or `nil` if out of bounds.
    public func at(_ index: Int) -> T? {
        guard index >= 0, index < items.count else { return nil }
        return items[index]
    }

    /// Returns a copy of the underlying array.
    public func toArray() -> [T] { items }

    // MARK: - Mutations

    /// Append an item to the end of the list.
    public func append(_ item: T) {
        let index = items.count
        items.append(item)
        onAdded(item: item, index: index)
    }

    /// Insert an item at `index` (0 … count).
    public func insert(_ item: T, at index: Int) {
        items.insert(item, at: index)
        onAdded(item: item, index: index)
    }

    /// Remove and return the last item, or `nil` if the list is empty.
    @discardableResult
    public func removeLast() -> T? {
        guard !items.isEmpty else { return nil }
        let index = items.count - 1
        let item = items[index]
        items.removeLast()
        onRemoved(item: item, index: index)
        return item
    }

    /// Remove the item at `index`.
    public func removeAt(_ index: Int) {
        let item = items[index]
        items.remove(at: index)
        onRemoved(item: item, index: index)
    }

    /// Replace the item at `index` with `newItem`.
    public func replace(at index: Int, with newItem: T) {
        let oldItem = items[index]
        items[index] = newItem
        onReplaced(newItem: newItem, oldItem: oldItem, index: index)
    }

    /// Remove all items and emit `reset` (and `propertyChanged("Count")` if the
    /// count changed).
    public func clear() {
        let countChanged = !items.isEmpty
        items.removeAll()
        // Clearing an empty list is a no-op: emit neither Reset nor Count
        // (ADR-0037 §2.2, mirroring the empty-batch precedent).
        if countChanged {
            onReset()
        }
        if countChanged && batchDepth == 0 {
            propertyChangedSubject.send("Count")
        }
    }

    /// Execute `body` with granular events suppressed (ref-counted for nesting).
    ///
    /// On exit of the outermost batch:
    ///   - No mutations → nothing emitted.
    ///   - Mutations occurred → `reset` fires; if the count changed,
    ///     `propertyChanged("Count")` fires after `reset`.
    public func withBatch(_ body: () -> Void) {
        if batchDepth == 0 {
            countAtBatchStart = items.count
            mutatedInBatch = false
        }
        batchDepth += 1
        defer {
            batchDepth -= 1
            if batchDepth == 0 && mutatedInBatch {
                let finalCount = items.count
                mutatedInBatch = false
                resetSubject.send(())
                if finalCount != countAtBatchStart {
                    propertyChangedSubject.send("Count")
                }
            }
        }
        body()
    }

    // MARK: - Private helpers

    private func onAdded(item: T, index: Int) {
        if batchDepth > 0 {
            mutatedInBatch = true
            return
        }
        itemAddedSubject.send(ItemAddedEvent(item: item, index: index))
        propertyChangedSubject.send("Count")
    }

    private func onRemoved(item: T, index: Int) {
        if batchDepth > 0 {
            mutatedInBatch = true
            return
        }
        itemRemovedSubject.send(ItemRemovedEvent(item: item, index: index))
        propertyChangedSubject.send("Count")
    }

    private func onReplaced(newItem: T, oldItem: T, index: Int) {
        if batchDepth > 0 {
            mutatedInBatch = true
            return
        }
        itemReplacedSubject.send(ItemReplacedEvent(newItem: newItem, oldItem: oldItem, index: index))
        // Count does not change on replace — no propertyChanged("Count")
    }

    private func onReset() {
        if batchDepth > 0 {
            mutatedInBatch = true
            return
        }
        resetSubject.send(())
    }
}

// MARK: - Value-based removal (requires Equatable)

public extension ObservableList where T: Equatable {
    /// Remove the first occurrence of `item`, emitting `itemRemoved` (and `Count`
    /// when it changed) exactly as `removeAt(_:)` does. Returns `true` when the item
    /// was found and removed, `false` otherwise — parity with the canonical
    /// `Remove(item): Bool` (spec/21 §3.1). Offered on an `Equatable`-constrained
    /// extension because the designated `ObservableList<T>` is unconstrained
    /// (mirroring the ADR-0059 §2.2 pattern the ADR-0009 catalogue prescribes).
    @discardableResult
    func remove(_ item: T) -> Bool {
        guard let index = toArray().firstIndex(of: item) else { return false }
        removeAt(index)
        return true
    }
}
