import Combine
import Foundation
import VMx

private final class GlobalSearchResultOwner: @unchecked Sendable {
    private let lock = NSLock()
    private var results: [ObjectIdentifier: NoteVM] = [:]
    private var disposed = false

    func track(_ result: NoteVM) -> NoteVM {
        let disposeImmediately = lock.withLock { () -> Bool in
            guard !disposed else { return true }
            results[ObjectIdentifier(result)] = result
            return false
        }
        if disposeImmediately {
            result.dispose()
        }
        return result
    }

    func disposeAll() {
        let owned = lock.withLock { () -> [NoteVM] in
            disposed = true
            defer { results.removeAll() }
            return Array(results.values)
        }
        for result in owned {
            result.dispose()
        }
    }
}

/// Token-paged search and lifetime owner for every result VM it creates.
public final class GlobalSearchVM: ComponentVMBase {
    private let repo: any NoteRepository
    private let pageSize: Int
    private let search: SearchableState<String>
    private let paged: TokenPagedComposition<NoteVM, String>
    private let resultOwner: GlobalSearchResultOwner
    private var cancellables: Set<AnyCancellable> = []

    private init(
        name: String,
        hint: String,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        repository: any NoteRepository,
        pageSize: Int,
        searchDebounce: DispatchQueue.SchedulerTimeType.Stride
    ) {
        self.repo = repository
        self.pageSize = pageSize
        self.search = SearchableState<String>(
            items: { ["global-search"] },
            predicate: { _, _ in true },
            debounce: searchDebounce
        )
        let resultOwner = GlobalSearchResultOwner()
        self.resultOwner = resultOwner
        let repoRef = repository
        let hubRef = hub
        let dispatcherRef = dispatcher
        self.paged = TokenPagedComposition<NoteVM, String>(
            fetchNext: { [search] token in
                let page = try await repoRef.searchNotes(
                    term: search.searchTerm,
                    token: token,
                    pageSize: pageSize
                )
                let items = try page.items.map { model in
                    resultOwner.track(
                        try NoteVM.builder()
                            .name("global-\(model.id)")
                            .services(hub: hubRef, dispatcher: dispatcherRef)
                            .model(model)
                            .build()
                    )
                }
                return (items, page.nextToken)
            },
            autoConstructOnAdd: true,
            pagesEqual: { left, right in
                left.map { $0.model.id } == right.map { $0.model.id }
            }
        )

        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)

        paged.collectionChanged
            .sink { [weak self] _ in self?.notifyResults() }
            .store(in: &cancellables)
        paged.propertyChanged
            .sink { [weak self] name in
                if name == "hasMore" { self?.notifyHasMore() }
            }
            .store(in: &cancellables)
    }

    public var searchTerm: String {
        get { search.searchTerm }
        set {
            guard search.searchTerm != newValue else { return }
            search.searchTerm = newValue
            _notifyPropertyChanged("searchTerm")
        }
    }

    public func canSearch() -> Bool {
        search.canSearch()
    }

    public func searchNow() {
        search.search()
        refreshCommand.execute()
    }

    public var results: [NoteVM] {
        paged.items
    }

    public var hasMore: Bool {
        paged.hasMore
    }

    public var refreshCommand: AsyncRelayCommand {
        paged.refreshCommand
    }

    public var loadMoreCommand: AsyncRelayCommand {
        paged.loadMoreCommand
    }

    private func notifyResults() {
        _notifyPropertyChanged("results")
    }

    private func notifyHasMore() {
        _notifyPropertyChanged("hasMore")
    }

    public override func _onDispose() {
        cancellables.removeAll()
        resultOwner.disposeAll()
        paged.dispose()
        search.dispose()
        super._onDispose()
    }

    public static func builder() -> GlobalSearchVMBuilder {
        GlobalSearchVMBuilder()
    }

    public struct GlobalSearchVMBuilder {
        private var _name: String?
        private var _hint = ""
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _repo: (any NoteRepository)?
        private var _pageSize = 5
        private var _searchDebounce: DispatchQueue.SchedulerTimeType.Stride = .milliseconds(150)

        fileprivate init() {}

        public func name(_ value: String) -> GlobalSearchVMBuilder {
            var c = self; c._name = value; return c
        }

        public func hint(_ value: String) -> GlobalSearchVMBuilder {
            var c = self; c._hint = value; return c
        }

        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> GlobalSearchVMBuilder {
            var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
        }

        public func repository(_ value: any NoteRepository) -> GlobalSearchVMBuilder {
            var c = self; c._repo = value; return c
        }

        public func pageSize(_ value: Int) -> GlobalSearchVMBuilder {
            var c = self; c._pageSize = value; return c
        }

        public func searchDebounce(_ value: DispatchQueue.SchedulerTimeType.Stride) -> GlobalSearchVMBuilder {
            var c = self; c._searchDebounce = value; return c
        }

        public func build() throws -> GlobalSearchVM {
            guard let name = _name else { throw BuilderValidationError(missingField: "name") }
            guard let hub = _hub else { throw BuilderValidationError(missingField: "hub") }
            guard let dispatcher = _dispatcher else { throw BuilderValidationError(missingField: "dispatcher") }
            guard let repo = _repo else { throw BuilderValidationError(missingField: "repository") }
            return GlobalSearchVM(
                name: name,
                hint: _hint,
                hub: hub,
                dispatcher: dispatcher,
                repository: repo,
                pageSize: _pageSize,
                searchDebounce: _searchDebounce
            )
        }
    }
}
