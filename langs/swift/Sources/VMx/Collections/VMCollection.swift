import Combine

/// Catchable bounds failure for `VMCollection.move(from:to:)`.
public struct VMCollectionIndexError: Error, Equatable {
    public let index: Int
    public let count: Int

    public init(index: Int, count: Int) {
        self.index = index
        self.count = count
    }
}

/// Shared ordered, observable child-collection capability without selection.
public protocol VMCollection: AnyObject, Sequence where Element == Child {
    associatedtype Child: ComponentVMBase

    var count: Int { get }
    var collectionChanged: AnyPublisher<CollectionChangedEvent, Never> { get }
    func at(_ index: Int) -> Child
    func add(_ child: Child)
    func insert(_ child: Child, at index: Int)
    func remove(_ child: Child) -> Bool
    func removeAt(_ index: Int)
    func replace(at index: Int, with child: Child)
    func clear()
    func move(from fromIndex: Int, to toIndex: Int) throws
    func batchUpdate() -> BatchUpdateHandle
}

/// VM collection that additionally owns a current-child selection slot.
public protocol SelectableVMCollection: VMCollection {
    var current: Child? { get set }
    func selectComponent(_ vm: Child) throws
    func deselectComponent(_ vm: Child) throws
    func canSelectComponent(_ vm: Child) -> Bool
}
