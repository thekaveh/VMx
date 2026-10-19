//
// CollectionChangedEvent — immutable payload emitted on collection mutations.
//
// Mirrors WPF's NotifyCollectionChangedEventArgs shape and the TypeScript
// CollectionChangedEvent interface. Action is .add, .remove, .replace, .move, or .reset.
//
// See spec/21-collections.md. Consumed by CompositeVM.collectionChanged,
// GroupVM.collectionChanged (COMP-001/002, GRP-001), and
// ServicedObservableCollection (COL-001..004).
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
    case move
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

    /// Creates an event. Use `-1` for an index that does not apply.
    public init(
        action: CollectionChangedAction,
        newItems: [ComponentVMBase],
        oldItems: [ComponentVMBase],
        newIndex: Int,
        oldIndex: Int
    ) {
        self.action = action
        self.newItems = newItems
        self.oldItems = oldItems
        self.newIndex = newIndex
        self.oldIndex = oldIndex
    }
}

// MARK: — Convenience factories

extension CollectionChangedEvent {
    /// An Add event for a single item inserted at `index`.
    public static func added(_ item: ComponentVMBase, at index: Int) -> CollectionChangedEvent {
        .init(action: .add, newItems: [item], oldItems: [], newIndex: index, oldIndex: -1)
    }

    /// A Remove event for a single item that was at `index` before removal.
    public static func removed(_ item: ComponentVMBase, at index: Int) -> CollectionChangedEvent {
        .init(action: .remove, newItems: [], oldItems: [item], newIndex: -1, oldIndex: index)
    }

    /// A Move event for an existing item relocated without replacement.
    public static func moved(_ item: ComponentVMBase, from oldIndex: Int, to newIndex: Int)
        -> CollectionChangedEvent {
        .init(
            action: .move,
            newItems: [item],
            oldItems: [item],
            newIndex: newIndex,
            oldIndex: oldIndex
        )
    }

    /// A Reset event (batch clear or batch update completion).
    public static func reset() -> CollectionChangedEvent {
        .init(action: .reset, newItems: [], oldItems: [], newIndex: -1, oldIndex: -1)
    }
}

// MARK: — Hub publication (spec/01 §1.4, ADR-0142)

extension CollectionChangedEvent {
    /// The hub message a `CompositeVM` or `GroupVM` publishes after delivering
    /// this event on its local `collectionChanged` stream: the same action,
    /// positions, and items, sent by the container itself. The legacy `index`
    /// follows spec/21 §2.4 (insertion/replacement/destination position, the
    /// pre-removal position for a remove, `-1` for a reset).
    func hubMessage(sentBy container: ComponentVMBase) -> CollectionChangedMessage<ComponentVMBase> {
        let index: Int
        switch action {
        case .add, .replace, .move:
            index = newIndex
        case .remove:
            index = oldIndex
        case .reset:
            index = -1
        }
        return CollectionChangedMessage<ComponentVMBase>(
            senderObject: container,
            senderName: container.name,
            action: action,
            newItems: newItems,
            oldItems: oldItems,
            index: index,
            oldIndex: oldIndex,
            newIndex: newIndex
        )
    }
}
