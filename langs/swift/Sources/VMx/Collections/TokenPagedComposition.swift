//
// TokenPagedComposition.swift — accumulated, forward-only token pagination.
//
import Foundation
import Combine

public final class TokenPagedComposition<TVM, TToken> {
    public typealias Page = ([TVM], TToken?)
    public typealias FetchNext = (TToken?) async throws -> Page
    public typealias PagesEqual = ([TVM], [TVM]) -> Bool

    private let fetchNext: FetchNext
    private let autoConstructOnAdd: Bool
    private let pagesEqual: PagesEqual
    private let stateQueue = DispatchQueue(label: "VMx.TokenPagedComposition.state")
    private var _items: [TVM] = []
    private var _currentToken: TToken?
    private var loadedOnce = false
    private var operationGeneration = 0
    private var disposed = false
    private let collectionChangedSubject = PassthroughSubject<CollectionChangedEvent, Never>()
    private let propertyChangedSubject = PassthroughSubject<String, Never>()
    private let commandChangedSubject = PassthroughSubject<Void, Never>()

    public lazy var loadMoreCommand: AsyncRelayCommand = AsyncRelayCommand.builder()
        .predicate { [weak self] in self?.hasMore == true && self?.isDisposed == false }
        .triggers(commandChangedSubject.eraseToAnyPublisher())
        .task { [weak self] in try await self?.loadMore() }
        .build()

    public lazy var refreshCommand: AsyncRelayCommand = AsyncRelayCommand.builder()
        .predicate { [weak self] in self?.isDisposed == false }
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

    public var items: [TVM] { stateQueue.sync { _items } }

    public var currentToken: TToken? { stateQueue.sync { _currentToken } }

    public var hasMore: Bool {
        stateQueue.sync { !loadedOnce || _currentToken != nil }
    }

    private var isDisposed: Bool { stateQueue.sync { disposed } }

    public var collectionChanged: AnyPublisher<CollectionChangedEvent, Never> {
        collectionChangedSubject.eraseToAnyPublisher()
    }

    public var propertyChanged: AnyPublisher<String, Never> {
        propertyChangedSubject.eraseToAnyPublisher()
    }

    private func loadMore() async throws {
        let start = stateQueue.sync { () -> (disposed: Bool, token: TToken?, generation: Int) in
            guard !disposed else { return (true, nil, operationGeneration) }
            operationGeneration += 1
            return (false, _currentToken, operationGeneration)
        }
        guard !start.disposed else { return }

        let page = try await fetchNext(start.token)
        let isCurrent = stateQueue.sync {
            !disposed && start.generation == operationGeneration
        }
        guard isCurrent else { return }
        try constructIfNeeded(page.0)
        let committed = stateQueue.sync { () -> Bool in
            guard !disposed, start.generation == operationGeneration else { return false }
            _items.append(contentsOf: page.0)
            _currentToken = page.1
            loadedOnce = true
            return true
        }
        guard committed else { return }
        notifyResetIfLive()
    }

    private func refresh() async throws {
        let generation = stateQueue.sync { () -> Int? in
            guard !disposed else { return nil }
            operationGeneration += 1
            return operationGeneration
        }
        guard let generation else { return }
        let page = try await fetchNext(nil)
        let head = stateQueue.sync { () -> [TVM]? in
            guard !disposed, generation == operationGeneration else { return nil }
            return Array(_items.prefix(page.0.count))
        }
        guard let head else { return }
        let pagesMatch = pagesEqual(page.0, head)
        if !pagesMatch {
            try constructIfNeeded(page.0)
        }
        let committed = stateQueue.sync { () -> Bool in
            guard !disposed, generation == operationGeneration else { return false }
            if !pagesMatch {
                _items = page.0
            }
            _currentToken = page.1
            loadedOnce = true
            return true
        }
        guard committed else { return }
        if pagesMatch {
            notifyPropertiesIfLive()
        } else {
            notifyResetIfLive()
        }
    }

    private func constructIfNeeded(_ items: [TVM]) throws {
        guard autoConstructOnAdd else { return }
        for item in items {
            if let vm = item as? ComponentVMBase, !vm.isConstructed {
                try vm.construct()
            }
        }
    }

    private func notifyResetIfLive() {
        guard !isDisposed else { return }
        collectionChangedSubject.send(.reset())
        notifyPropertiesIfLive()
    }

    private func notifyPropertiesIfLive() {
        for name in ["items", "currentToken", "hasMore"] {
            guard !isDisposed else { return }
            propertyChangedSubject.send(name)
        }
        guard !isDisposed else { return }
        commandChangedSubject.send(())
    }

    public func dispose() {
        let shouldDispose = stateQueue.sync { () -> Bool in
            guard !disposed else { return false }
            disposed = true
            return true
        }
        guard shouldDispose else { return }
        loadMoreCommand.dispose()
        refreshCommand.dispose()
        collectionChangedSubject.send(completion: .finished)
        propertyChangedSubject.send(completion: .finished)
        commandChangedSubject.send(completion: .finished)
    }
}
