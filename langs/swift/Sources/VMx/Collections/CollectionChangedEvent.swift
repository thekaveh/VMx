//
// CollectionChangedEvent — immutable payload emitted on collection mutations.
//
// Mirrors WPF's NotifyCollectionChangedEventArgs shape and the TypeScript
// CollectionChangedEvent interface. Action is .add, .remove, .replace, or .reset.
//
// See spec/21-collections.md. Consumed by CompositeVM.collectionChanged,
// GroupVM.collectionChanged (COMP-001/002, GRP-001), and
// ServicedObservableCollection (COL-001..004, Phase 3, Inc 2).
//

/// The kind of mutation that triggered a CollectionChanged event.
///
/// - `add`: one or more items were appended or inserted.
/// - `remove`: one or more items were removed.
/// - `replace`: an item at a known index was replaced in-place (setAt).
/// - `reset`: the collection was cleared or batch-updated (coarse-grained).
public enum CollectionChangedAction: Sendable, Equatable {
    case add
    case remove
    case replace
    case reset
}

/// Immutable payload emitted by `collectionChanged` publishers on
/// `CompositeVM` and `GroupVM`.
///
/// - `newItems`: items added by this mutation (`[]` for remove/reset).
/// - `oldItems`: items removed by this mutation (`[]` for add/reset).
/// - `newIndex`: insertion index, or `-1` when not applicable.
/// - `oldIndex`: removal index, or `-1` when not applicable.
public struct CollectionChangedEvent {
    public let action: CollectionChangedAction
    public let newItems: [ComponentVMBase]
    public let oldItems: [ComponentVMBase]
    public let newIndex: Int
    public let oldIndex: Int
}

// MARK: — Convenience factories

extension CollectionChangedEvent {
    /// An Add event for a single item inserted at `index`.
    static func added(_ item: ComponentVMBase, at index: Int) -> CollectionChangedEvent {
        .init(action: .add, newItems: [item], oldItems: [], newIndex: index, oldIndex: -1)
    }

    /// A Remove event for a single item that was at `index` before removal.
    static func removed(_ item: ComponentVMBase, at index: Int) -> CollectionChangedEvent {
        .init(action: .remove, newItems: [], oldItems: [item], newIndex: -1, oldIndex: index)
    }

    /// A Reset event (batch clear or batch update completion).
    static func reset() -> CollectionChangedEvent {
        .init(action: .reset, newItems: [], oldItems: [], newIndex: -1, oldIndex: -1)
    }
}
