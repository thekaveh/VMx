//
// ServicedObservableCollection — observable array that optionally publishes
// CollectionChangedMessage events to a MessageHubProtocol.
//
// When no hub is injected (hub == nil), the class behaves like a plain
// observable collection: the local collectionChanged publisher fires but
// no hub publication occurs and no error is raised (COL-003).
//
// Ordering guarantee (COL-001/002): local collectionChanged fires FIRST,
// then hub?.send(_:). Delivery is synchronous on the caller's thread,
// with no dispatcher marshaling (COL-004).
//
// Ownership stays with the caller: removing, replacing, or clearing an item
// does not call dispose/destruct or any VM lifecycle method on that item.
//
// See spec/21-collections.md §2, ADR-0024, and ADR-0096.
//
import Combine
import Foundation

/// Hub-aware observable collection. Each mutation:
/// 1. Emits a `CollectionChangedMessage` on the local `collectionChanged` publisher.
/// 2. Sends the same message to the injected `MessageHubProtocol` (if any).
///
/// Both steps happen synchronously on the caller thread (COL-004).
public final class ServicedObservableCollection<T>: Sequence {

    // ── Private state ────────────────────────────────────────────────────────

    private let hub: (any MessageHubProtocol)?
    private var items: [T] = []
    private let subject = PassthroughSubject<CollectionChangedMessage<T>, Never>()
    private let typeName: String

    // ── Initializer ──────────────────────────────────────────────────────────

    /// Create a serviced collection optionally backed by a hub.
    ///
    /// - Parameter hub: The hub to publish `CollectionChangedMessage` events to.
    ///   Pass `nil` (the default) for a hub-less observable collection.
    public init(hub: (any MessageHubProtocol)? = nil) {
        self.hub = hub
        self.typeName = "ServicedObservableCollection"
    }

    // ── Public surface ───────────────────────────────────────────────────────

    /// Hot publisher of `CollectionChangedMessage` events for this collection.
    /// Subscribers see only events emitted after they subscribe.
    public var collectionChanged: AnyPublisher<CollectionChangedMessage<T>, Never> {
        subject.eraseToAnyPublisher()
    }

    /// The number of items in the collection.
    public var count: Int { items.count }

    /// Return the item at `index`, or `nil` if out of bounds.
    public func at(_ index: Int) -> T? {
        guard index >= 0 && index < items.count else { return nil }
        return items[index]
    }

    /// Return a shallow copy of the backing array.
    public func toArray() -> [T] { items }

    /// Iterate over a snapshot of the current contents.
    public func makeIterator() -> IndexingIterator<[T]> {
        items.makeIterator()
    }

    // ── Mutations ────────────────────────────────────────────────────────────

    /// Append `item` to the end of the collection.
    public func append(_ item: T) {
        let index = items.count
        items.append(item)
        emit(.forAdd(sender: self, senderName: typeName, item: item, index: index))
    }

    /// Remove and return the last item, or `nil` if the collection is empty.
    @discardableResult
    public func removeLast() -> T? {
        guard !items.isEmpty else { return nil }
        let index = items.count - 1
        let item = items[index]
        items.removeLast()
        emit(.forRemove(sender: self, senderName: typeName, item: item, index: index))
        return item
    }

    /// Remove the item at `index`.
    ///
    /// - Precondition: `index` is a valid index in the collection.
    public func removeAt(_ index: Int) {
        precondition(index >= 0 && index < items.count,
                     "ServicedObservableCollection.removeAt: index \(index) out of bounds (count: \(items.count))")
        let item = items.remove(at: index)
        emit(.forRemove(sender: self, senderName: typeName, item: item, index: index))
    }

    /// Replace the item at `index` with `newItem`.
    ///
    /// - Precondition: `index` is a valid index in the collection.
    public func replace(at index: Int, with newItem: T) {
        precondition(index >= 0 && index < items.count,
                     "ServicedObservableCollection.replace: index \(index) out of bounds (count: \(items.count))")
        let oldItem = items[index]
        items[index] = newItem
        emit(.forReplace(sender: self, senderName: typeName,
                         newItem: newItem, oldItem: oldItem, index: index))
    }

    /// Replace the item at `index` with `newItem`.
    ///
    /// - Precondition: `index` is a valid index in the collection.
    public func setAt(_ index: Int, _ newItem: T) {
        replace(at: index, with: newItem)
    }

    /// Replace all contents from a fully materialized input snapshot.
    public func replaceAll<S: Sequence>(_ newItems: S) where S.Element == T {
        let snapshot = Array(newItems)
        guard !items.isEmpty || !snapshot.isEmpty else { return }
        items = snapshot
        emit(.forReset(sender: self, senderName: typeName))
    }

    /// Move an existing item between two pre-move positions.
    public func move(from oldIndex: Int, to newIndex: Int) throws {
        guard oldIndex >= 0 && oldIndex < items.count else {
            throw VMCollectionIndexError(index: oldIndex, count: items.count)
        }
        guard newIndex >= 0 && newIndex < items.count else {
            throw VMCollectionIndexError(index: newIndex, count: items.count)
        }
        guard oldIndex != newIndex else { return }

        let item = items.remove(at: oldIndex)
        items.insert(item, at: newIndex)
        emit(.forMove(sender: self, senderName: typeName, item: item,
                      from: oldIndex, to: newIndex))
    }

    /// Remove all items and emit a Reset event.
    public func clear() {
        guard !items.isEmpty else { return }
        items.removeAll()
        emit(.forReset(sender: self, senderName: typeName))
    }

    // ── Internal ─────────────────────────────────────────────────────────────

    /// Emit locally first, then publish to the hub (COL-001/002 ordering).
    private func emit(_ message: CollectionChangedMessage<T>) {
        // 1. Local subscribers first.
        subject.send(message)
        // 2. Hub publication (no-op when hub is nil — COL-003).
        hub?.send(message)
    }
}

// MARK: - Value-based removal (requires Equatable)

extension ServicedObservableCollection where T: Equatable {
    /// Remove the first occurrence of `item`, emitting a granular remove (local
    /// then hub, COL-001/002 ordering) exactly like the other mutators. Returns
    /// `true` when the item was found and removed, `false` otherwise — parity with
    /// the canonical `Remove(item): Bool` (spec/21 §2.1). Offered on an
    /// `Equatable`-constrained extension because the element type is unconstrained.
    @discardableResult
    public func remove(_ item: T) -> Bool {
        guard let index = items.firstIndex(of: item) else { return false }
        let storedItem = items.remove(at: index)
        emit(.forRemove(sender: self, senderName: typeName, item: storedItem, index: index))
        return true
    }
}

// MARK: - Aggregate membership source (reference items only)

extension ServicedObservableCollection: ObservableMembershipSource where T: AnyObject {
    public typealias Item = T

    public func snapshot() -> [T] { toArray() }

    public func subscribeMembership(_ callback: @escaping () -> Void) -> AnyCancellable {
        collectionChanged.sink { _ in callback() }
    }
}
