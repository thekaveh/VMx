//
// CollectionChangedMessage — hub envelope emitted by ServicedObservableCollection.
//
// See spec/21-collections.md §2 and ADR-0024.
//
import Foundation

/// Hub message published by `ServicedObservableCollection<T>` on each mutation.
///
/// Conforms to `Message` so it is routable through `MessageHubProtocol`.
/// Subscribers may downcast `any Message` to `CollectionChangedMessage<T>` or
/// filter by identity (`sender === collection`).
public struct CollectionChangedMessage<T>: Message {
    /// The collection that emitted this message.
    public let senderObject: AnyObject
    /// Type name of the sender (e.g. `"ServicedObservableCollection"`).
    public let senderName: String
    /// The kind of mutation.
    public let action: CollectionChangedAction
    /// Items added or replacing an existing item (empty for remove/reset).
    public let newItems: [T]
    /// Items removed or being replaced (empty for add/reset).
    public let oldItems: [T]
    /// Insertion/removal/replacement index, or -1 when not applicable (reset).
    public let index: Int

    /// Spec alias of `senderObject`. Matches the `sender` field name in
    /// C# / Python / TypeScript flavors.
    public var sender: AnyObject { senderObject }
}

// MARK: — Convenience factories

extension CollectionChangedMessage {
    /// An Add message for a single item appended at `index`.
    public static func forAdd(
        sender: AnyObject,
        senderName: String,
        item: T,
        index: Int
    ) -> CollectionChangedMessage<T> {
        .init(senderObject: sender, senderName: senderName,
              action: .add, newItems: [item], oldItems: [], index: index)
    }

    /// A Remove message for a single item that was at `index` before removal.
    public static func forRemove(
        sender: AnyObject,
        senderName: String,
        item: T,
        index: Int
    ) -> CollectionChangedMessage<T> {
        .init(senderObject: sender, senderName: senderName,
              action: .remove, newItems: [], oldItems: [item], index: index)
    }

    /// A Replace message for an item replaced in-place at `index`.
    public static func forReplace(
        sender: AnyObject,
        senderName: String,
        newItem: T,
        oldItem: T,
        index: Int
    ) -> CollectionChangedMessage<T> {
        .init(senderObject: sender, senderName: senderName,
              action: .replace, newItems: [newItem], oldItems: [oldItem], index: index)
    }

    /// A Reset message (clear or batch update). `index` is -1.
    public static func forReset(
        sender: AnyObject,
        senderName: String
    ) -> CollectionChangedMessage<T> {
        .init(senderObject: sender, senderName: senderName,
              action: .reset, newItems: [], oldItems: [], index: -1)
    }
}
