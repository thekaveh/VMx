//
// TokenPagedComposition.swift — accumulated, forward-only token pagination.
//
import Combine

public final class TokenPagedComposition<TVM, TToken> {
    public typealias Page = ([TVM], TToken?)
    public typealias FetchNext = (TToken?) async throws -> Page
    public typealias PagesEqual = ([TVM], [TVM]) -> Bool

    private let fetchNext: FetchNext
    private let autoConstructOnAdd: Bool
    private let pagesEqual: PagesEqual
    private var _items: [TVM] = []
    private var _currentToken: TToken?
    private var loadedOnce = false
    private var disposed = false
    private let collectionChangedSubject = PassthroughSubject<CollectionChangedEvent, Never>()
    private let propertyChangedSubject = PassthroughSubject<String, Never>()
    private let commandChangedSubject = PassthroughSubject<Void, Never>()

    public lazy var loadMoreCommand: AsyncRelayCommand = AsyncRelayCommand.builder()
        .predicate { [weak self] in self?.hasMore == true && self?.disposed == false }
        .triggers(commandChangedSubject.eraseToAnyPublisher())
        .task { [weak self] in try await self?.loadMore() }
        .build()

    public lazy var refreshCommand: AsyncRelayCommand = AsyncRelayCommand.builder()
        .predicate { [weak self] in self?.disposed == false }
        .triggers(commandChangedSubject.eraseToAnyPublisher())
        .task { [weak self] in try await self?.refresh() }
        .build()

    public init(
        fetchNext: @escaping FetchNext,
        autoConstructOnAdd: Bool = false,
        pagesEqual: @escaping PagesEqual = { _, _ in false }
    ) {
        self.fetchNext = fetchNext
        self.autoConstructOnAdd = autoConstructOnAdd
        self.pagesEqual = pagesEqual
    }

    public var items: [TVM] { _items }

    public var currentToken: TToken? { _currentToken }

    public var hasMore: Bool { !loadedOnce || _currentToken != nil }

    public var collectionChanged: AnyPublisher<CollectionChangedEvent, Never> {
        collectionChangedSubject.eraseToAnyPublisher()
    }

    public var propertyChanged: AnyPublisher<String, Never> {
        propertyChangedSubject.eraseToAnyPublisher()
    }

    private func loadMore() async throws {
        let page = try await fetchNext(_currentToken)
        guard !disposed else { return }
        _items.append(contentsOf: page.0)
        try constructIfNeeded(page.0)
        _currentToken = page.1
        loadedOnce = true
        notifyReset()
    }

    private func refresh() async throws {
        let page = try await fetchNext(nil)
        guard !disposed else { return }
        let head = Array(_items.prefix(page.0.count))
        if pagesEqual(page.0, head) {
            _currentToken = page.1
            loadedOnce = true
            notifyProperties()
            return
        }
        _items = page.0
        try constructIfNeeded(page.0)
        _currentToken = page.1
        loadedOnce = true
        notifyReset()
    }

    private func constructIfNeeded(_ items: [TVM]) throws {
        guard autoConstructOnAdd else { return }
        for item in items {
            if let vm = item as? ComponentVMBase, !vm.isConstructed {
                try vm.construct()
            }
        }
    }

    private func notifyReset() {
        collectionChangedSubject.send(.reset())
        notifyProperties()
    }

    private func notifyProperties() {
        propertyChangedSubject.send("items")
        propertyChangedSubject.send("currentToken")
        propertyChangedSubject.send("hasMore")
        commandChangedSubject.send(())
    }

    public func dispose() {
        guard !disposed else { return }
        disposed = true
        loadMoreCommand.dispose()
        refreshCommand.dispose()
        collectionChangedSubject.send(completion: .finished)
        propertyChangedSubject.send(completion: .finished)
        commandChangedSubject.send(completion: .finished)
    }
}
