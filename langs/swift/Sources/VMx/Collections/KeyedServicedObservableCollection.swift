//
// KeyedServicedObservableCollection — ordered, hub-aware collection with a
// captured-key index. See spec/21-collections.md §2.8 and ADR-0097.
//
import Combine
import Foundation

/// Errors reported by keyed collection invariant validation.
public enum KeyedServicedCollectionError: Error {
    /// A candidate mutation would leave two memberships with the same key.
    case duplicateKey
}

/// An ordered serviced collection with expected-O(1) lookup by a captured key.
///
/// Keys are projected before mutation, captured for the lifetime of each
/// membership, and never recomputed by lookup, movement, or removal. Items stay
/// caller-owned. Every effective mutation commits the ordered store and key
/// index before it publishes locally and then to the optional external hub.
public final class KeyedServicedObservableCollection<Key: Hashable, T>: Sequence {
    private let hub: (any MessageHubProtocol)?
    private let keyOf: (T) throws -> Key
    private var items: [T] = []
    private var capturedKeys: [Key] = []
    private var keyToIndex: [Key: Int] = [:]
    private let subject = PassthroughSubject<CollectionChangedMessage<T>, Never>()
    private let typeName = "KeyedServicedObservableCollection"

    /// Create a keyed serviced collection.
    ///
    /// - Parameters:
    ///   - keyOf: A throwing projector whose successful result is captured for
    ///     each new or explicitly replaced membership.
    ///   - hub: An optional external message hub.
    public init(
        keyOf: @escaping (T) throws -> Key,
        hub: (any MessageHubProtocol)? = nil
    ) {
        self.keyOf = keyOf
        self.hub = hub
    }

    /// Hot local publisher for collection changes.
    public var collectionChanged: AnyPublisher<CollectionChangedMessage<T>, Never> {
        subject.eraseToAnyPublisher()
    }

    /// Number of ordered memberships.
    public var count: Int { items.count }

    /// Return the item at `index`, or `nil` when out of bounds.
    public func at(_ index: Int) -> T? {
        guard items.indices.contains(index) else { return nil }
        return items[index]
    }

    /// Return a shallow ordered snapshot.
    public func toArray() -> [T] { items }

    /// Iterate over a snapshot of the current order.
    public func makeIterator() -> IndexingIterator<[T]> {
        items.makeIterator()
    }

    /// Return the item captured under `key`, or `nil` on a miss.
    public func get(_ key: Key) -> T? {
        guard let index = keyToIndex[key] else { return nil }
        return items[index]
    }

    /// Return whether a membership has captured `key`.
    public func containsKey(_ key: Key) -> Bool {
        keyToIndex[key] != nil
    }

    /// Append a new membership after projecting and validating its key.
    public func append(_ item: T) throws {
        let key = try keyOf(item)
        guard keyToIndex[key] == nil else {
            throw KeyedServicedCollectionError.duplicateKey
        }

        let index = items.count
        items.append(item)
        capturedKeys.append(key)
        keyToIndex[key] = index
        emit(.forAdd(sender: self, senderName: typeName, item: item, index: index))
    }

    /// Remove and return the final membership, or `nil` when empty.
    @discardableResult
    public func removeLast() -> T? {
        guard !items.isEmpty else { return nil }
        let index = items.count - 1
        let item = items.removeLast()
        let key = capturedKeys.removeLast()
        keyToIndex.removeValue(forKey: key)
        emit(.forRemove(sender: self, senderName: typeName, item: item, index: index))
        return item
    }

    /// Remove the membership at `index`.
    ///
    /// - Precondition: `index` is a valid collection index.
    public func removeAt(_ index: Int) {
        precondition(
            items.indices.contains(index),
            "KeyedServicedObservableCollection.removeAt: index \(index) out of bounds (count: \(items.count))"
        )
        removeMembership(at: index)
    }

    /// Replace one membership and explicitly recapture its key.
    ///
    /// - Precondition: `index` is a valid collection index.
    public func replace(at index: Int, with newItem: T) throws {
        precondition(
            items.indices.contains(index),
            "KeyedServicedObservableCollection.replace: index \(index) out of bounds (count: \(items.count))"
        )

        let newKey = try keyOf(newItem)
        if let existingIndex = keyToIndex[newKey], existingIndex != index {
            throw KeyedServicedCollectionError.duplicateKey
        }

        let oldItem = items[index]
        let oldKey = capturedKeys[index]
        items[index] = newItem
        capturedKeys[index] = newKey
        // Remove before insert even for equal keys. Hashable reference keys can
        // be distinct equal objects, and explicit replacement recaptures the
        // newly projected key object rather than retaining the retired one.
        keyToIndex.removeValue(forKey: oldKey)
        keyToIndex[newKey] = index
        emit(.forReplace(
            sender: self,
            senderName: typeName,
            newItem: newItem,
            oldItem: oldItem,
            index: index
        ))
    }

    /// Alias for indexed replacement.
    public func setAt(_ index: Int, _ newItem: T) throws {
        try replace(at: index, with: newItem)
    }

    /// Atomically replace all memberships after materialization, projection,
    /// and complete uniqueness validation.
    public func replaceAll<S: Sequence>(_ newItems: S) throws where S.Element == T {
        let newItemSnapshot = Array(newItems)
        var newKeySnapshot: [Key] = []
        newKeySnapshot.reserveCapacity(newItemSnapshot.count)
        var newIndex: [Key: Int] = [:]
        newIndex.reserveCapacity(newItemSnapshot.count)

        for (index, item) in newItemSnapshot.enumerated() {
            let key = try keyOf(item)
            guard newIndex[key] == nil else {
                throw KeyedServicedCollectionError.duplicateKey
            }
            newKeySnapshot.append(key)
            newIndex[key] = index
        }

        guard !items.isEmpty || !newItemSnapshot.isEmpty else { return }
        items = newItemSnapshot
        capturedKeys = newKeySnapshot
        keyToIndex = newIndex
        emit(.forReset(sender: self, senderName: typeName))
    }

    /// Insert a missing projected key or replace its existing membership.
    ///
    /// - Returns: `true` for Add; `false` for in-place Replace.
    @discardableResult
    public func upsert(_ item: T) throws -> Bool {
        let key = try keyOf(item)
        if let index = keyToIndex[key] {
            let oldItem = items[index]
            let oldKey = capturedKeys[index]
            items[index] = item
            capturedKeys[index] = key
            keyToIndex.removeValue(forKey: oldKey)
            keyToIndex[key] = index
            emit(.forReplace(
                sender: self,
                senderName: typeName,
                newItem: item,
                oldItem: oldItem,
                index: index
            ))
            return false
        }

        let index = items.count
        items.append(item)
        capturedKeys.append(key)
        keyToIndex[key] = index
        emit(.forAdd(sender: self, senderName: typeName, item: item, index: index))
        return true
    }

    /// Delete the membership captured under `key`.
    @discardableResult
    public func delete(_ key: Key) -> Bool {
        guard let index = keyToIndex[key] else { return false }
        removeMembership(at: index)
        return true
    }

    /// Move a membership between pre-move positions without reprojecting it.
    public func move(from oldIndex: Int, to newIndex: Int) throws {
        guard items.indices.contains(oldIndex) else {
            throw VMCollectionIndexError(index: oldIndex, count: items.count)
        }
        guard items.indices.contains(newIndex) else {
            throw VMCollectionIndexError(index: newIndex, count: items.count)
        }
        guard oldIndex != newIndex else { return }

        let item = items.remove(at: oldIndex)
        let key = capturedKeys.remove(at: oldIndex)
        items.insert(item, at: newIndex)
        capturedKeys.insert(key, at: newIndex)
        repairIndex(
            from: Swift.min(oldIndex, newIndex),
            through: Swift.max(oldIndex, newIndex)
        )
        emit(.forMove(
            sender: self,
            senderName: typeName,
            item: item,
            from: oldIndex,
            to: newIndex
        ))
    }

    /// Remove every membership. Empty clear is silent.
    public func clear() {
        guard !items.isEmpty else { return }
        items.removeAll()
        capturedKeys.removeAll()
        keyToIndex.removeAll()
        emit(.forReset(sender: self, senderName: typeName))
    }

    private func removeMembership(at index: Int) {
        let item = items.remove(at: index)
        let key = capturedKeys.remove(at: index)
        keyToIndex.removeValue(forKey: key)
        if index < capturedKeys.count {
            repairIndex(from: index, through: capturedKeys.count - 1)
        }
        emit(.forRemove(sender: self, senderName: typeName, item: item, index: index))
    }

    private func repairIndex(from start: Int, through end: Int) {
        guard start <= end else { return }
        for index in start...end {
            keyToIndex[capturedKeys[index]] = index
        }
    }

    private func emit(_ message: CollectionChangedMessage<T>) {
        subject.send(message)
        hub?.send(message)
    }
}

extension KeyedServicedObservableCollection where T: Equatable {
    /// Remove the first equal membership without reprojecting stored items.
    @discardableResult
    public func remove(_ item: T) -> Bool {
        guard let index = items.firstIndex(of: item) else { return false }
        removeMembership(at: index)
        return true
    }
}

// MARK: - Aggregate membership source (reference items only)

extension KeyedServicedObservableCollection: ObservableMembershipSource where T: AnyObject {
    public typealias Item = T

    public func snapshot() -> [T] { toArray() }

    public func subscribeMembership(_ callback: @escaping () -> Void) -> AnyCancellable {
        collectionChanged.sink { _ in callback() }
    }
}
