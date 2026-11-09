//
// ReadOnlyObservableList.swift — read-only facade over an ObservableList.
//
// See spec/21-collections.md §4.2 and ADR-0193.
// Conforms to: COL-070.
//

import Combine

/// A live, read-only view of an `ObservableList<T>`.
///
/// The view has every read and subscribe member of `ObservableList<T>`. It has
/// no mutator and no batch member, and it does not expose the backing list.
/// Each publisher is the backing list's publisher, so subscribers see the same
/// events, in the same order, with the same payloads.
///
/// `ObservableDictionary.keys1` and `keys2` return this view. Only the
/// dictionary changes a key view.
public final class ReadOnlyObservableList<T> {

    private let source: ObservableList<T>

    /// Creates a read-only view of `source`.
    init(_ source: ObservableList<T>) {
        self.source = source
    }

    // MARK: - Publishers

    /// Emits when an item is added. Payload: `{ item, index }`.
    public var itemAdded: AnyPublisher<ItemAddedEvent<T>, Never> { source.itemAdded }

    /// Emits when an item is removed. Payload: `{ item, index }` (index before removal).
    public var itemRemoved: AnyPublisher<ItemRemovedEvent<T>, Never> { source.itemRemoved }

    /// Emits when an item is replaced. Payload: `{ newItem, oldItem, index }`.
    public var itemReplaced: AnyPublisher<ItemReplacedEvent<T>, Never> { source.itemReplaced }

    /// Emits (`Void`) when the backing list resets.
    public var reset: AnyPublisher<Void, Never> { source.reset }

    /// Emits the property name whenever a property changes. The count channel
    /// is the spec-literal `"Count"` (spec/21 §3.3).
    public var propertyChanged: AnyPublisher<String, Never> { source.propertyChanged }

    // MARK: - Accessors

    /// The number of items in the view.
    public var count: Int { source.count }

    /// Returns the item at `index`, or `nil` if out of bounds.
    public func at(_ index: Int) -> T? { source.at(index) }

    /// Returns a copy of the items.
    public func toArray() -> [T] { source.toArray() }
}
