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
// See spec/21-collections.md §2 and ADR-0024.
//
import Foundation
import Combine

/// Hub-aware observable collection. Each mutation:
/// 1. Emits a `CollectionChangedMessage` on the local `collectionChanged` publisher.
/// 2. Sends the same message to the injected `MessageHubProtocol` (if any).
///
/// Both steps happen synchronously on the caller thread (COL-004).
public final class ServicedObservableCollection<T> {

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

    /// Replace the item at `index` with `newItem`.
    ///
    /// - Precondition: `index` is a valid index in the collection.
    public func setAt(_ index: Int, _ newItem: T) {
        precondition(index >= 0 && index < items.count,
                     "ServicedObservableCollection.setAt: index \(index) out of bounds (count: \(items.count))")
        let oldItem = items[index]
        items[index] = newItem
        emit(.forReplace(sender: self, senderName: typeName,
                         newItem: newItem, oldItem: oldItem, index: index))
    }

    /// Remove all items and emit a Reset event.
    public func clear() {
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

public extension ServicedObservableCollection where T: Equatable {
    /// Remove the first occurrence of `item`, emitting a granular remove (local
    /// then hub, COL-001/002 ordering) exactly like the other mutators. Returns
    /// `true` when the item was found and removed, `false` otherwise — parity with
    /// the canonical `Remove(item): Bool` (spec/21 §2.1). Offered on an
    /// `Equatable`-constrained extension because the element type is unconstrained.
    @discardableResult
    func remove(_ item: T) -> Bool {
        guard let index = items.firstIndex(of: item) else { return false }
        items.remove(at: index)
        emit(.forRemove(sender: self, senderName: typeName, item: item, index: index))
        return true
    }
}
