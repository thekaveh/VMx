import Combine
import Foundation
import VMx

private final class GlobalSearchResultOwner: @unchecked Sendable {
    private let lock = NSLock()
    private var results: [ObjectIdentifier: NoteVM] = [:]
    /// The search term that fetched each owned result.
    private var terms: [ObjectIdentifier: String] = [:]
    private var disposed = false

    func track(_ result: NoteVM, term: String) -> NoteVM {
        let disposeImmediately = lock.withLock { () -> Bool in
            guard !disposed else { return true }
            results[ObjectIdentifier(result)] = result
            terms[ObjectIdentifier(result)] = term
            return false
        }
        if disposeImmediately {
            result.dispose()
        }
        return result
    }

    func term(of result: NoteVM) -> String? {
        lock.withLock { terms[ObjectIdentifier(result)] }
    }

    func disposeAll() {
        let owned = lock.withLock { () -> [NoteVM] in
            disposed = true
            defer {
                results.removeAll()
                terms.removeAll()
            }
            return Array(results.values)
        }
        for result in owned {
            result.dispose()
        }
    }
}

/// Tracks search requests so that a load can find a refresh that it discarded.
private final class SearchRequests: @unchecked Sendable {
    private let lock = NSLock()
    private var term: String?
    private var fetches = 0
    private var lastFetchFailed = false
    private var overlap = false
    private var rerunSearch: (() -> Void)?

    /// The term of the latest `searchNow()` call or first-page fetch.
    var requestedTerm: String? { lock.withLock { term } }
    var firstPageFetches: Int { lock.withLock { fetches } }
    var lastFirstPageFetchFailed: Bool { lock.withLock { lastFetchFailed } }

    func record(_ requested: String) {
        lock.withLock { term = requested }
    }

    func recordFirstPageFetch(_ requested: String) {
        lock.withLock {
            term = requested
            fetches += 1
            lastFetchFailed = false
        }
    }

    func recordFirstPageFailure() {
        lock.withLock { lastFetchFailed = true }
    }

    /// Records that a first-page fetch started while a load ran.
    func markOverlap() {
        lock.withLock { overlap = true }
    }

    /// Returns true once after `markOverlap()`.
    func takeOverlap() -> Bool {
        lock.withLock {
            defer { overlap = false }
            return overlap
        }
    }

    /// Sets the call that checks the results after an overlap and searches
    /// again if needed.
    func onRerun(_ rerun: @escaping () -> Void) {
        lock.withLock { rerunSearch = rerun }
    }

    func rerun() {
        lock.withLock { rerunSearch }?()
    }
}

/// The cursor for the next page. It keeps the term of the loaded pages.
private struct SearchCursor: Sendable {
    let term: String
    let offset: String
}

/// Token-paged search and lifetime owner for every result VM it creates.
public final class GlobalSearchVM: ComponentVMBase {
    private let repo: any NoteRepository
    private let pageSize: Int
    private let search: SearchableState<String>
    private let paged: TokenPagedComposition<NoteVM, SearchCursor>
    private let resultOwner: GlobalSearchResultOwner
    private let searchRequests = SearchRequests()
    private var cancellables: Set<AnyCancellable> = []
    /// Guards `searchPending` and `searchDisposed`. `searchNow()` runs on the
    /// UI thread, and the refresh command settles on a cooperative-pool thread.
    private let pendingSearchLock = NSLock()
    /// A `searchNow()` request that has not started a fetch yet.
    private var searchPending = false
    private var searchDisposed = false

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
        let searchRequests = self.searchRequests
        let repoRef = repository
        let hubRef = hub
        let dispatcherRef = dispatcher
        let paged = TokenPagedComposition<NoteVM, SearchCursor>(
            fetchNext: { [search] cursor in
                // The first page uses the current term. A later page uses the term in
                // the cursor, so "Load more" continues the term of the loaded pages.
                let term = cursor?.term ?? search.searchTerm
                if cursor == nil { searchRequests.recordFirstPageFetch(term) }
                let page: (items: [NoteModel], nextToken: String?)
                do {
                    page = try await repoRef.searchNotes(
                        term: term,
                        token: cursor?.offset,
                        pageSize: pageSize
                    )
                } catch {
                    if cursor == nil { searchRequests.recordFirstPageFailure() }
                    throw error
                }
                let items = try page.items.map { model in
                    resultOwner.track(
                        try NoteVM.builder()
                            .name("global-\(model.id)")
                            .services(hub: hubRef, dispatcher: dispatcherRef)
                            .model(model)
                            .build(),
                        term: term
                    )
                }
                return (items, page.nextToken.map { SearchCursor(term: term, offset: $0) })
            },
            autoConstructOnAdd: true,
            // Pages for different terms are never equal, so a refresh for a new
            // term replaces the loaded pages and their cursor.
            pagesEqual: { left, right in
                left.count == right.count
                    && zip(left, right).allSatisfy { pair in
                        pair.0.model.id == pair.1.model.id
                            && resultOwner.term(of: pair.0) == resultOwner.term(of: pair.1)
                    }
            }
        )
        self.paged = paged
        // A refresh replaces the loaded pages, so "Load more" is not available
        // until the refresh is complete. A call made during a refresh does
        // nothing. A load that starts during a refresh makes the composition
        // discard that refresh (spec 21 §6.2).
        self.loadMoreCommand = AsyncRelayCommand.builder()
            .predicate { [paged] in
                paged.loadMoreCommand.canExecute() && !paged.refreshCommand.isExecuting
            }
            .triggers(paged.loadMoreCommand.canExecuteChanged)
            .triggers(paged.refreshCommand.canExecuteChanged)
            .task { [paged, searchRequests] in
                // The task starts after the predicate passed, on another thread. A
                // refresh can start after the check below and before the load
                // starts. The load then discards that refresh. So when a refresh
                // started during the load, check the results once both are idle.
                let fetches = searchRequests.firstPageFetches
                guard !paged.refreshCommand.isExecuting else { return }
                defer {
                    if searchRequests.firstPageFetches > fetches {
                        searchRequests.markOverlap()
                        searchRequests.rerun()
                    }
                }
                try await paged.loadMoreCommand.executeAsync()
            }
            .build()

        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)

        searchRequests.onRerun { [weak self] in
            self?.dispatcher.scheduleForeground { [weak self] in self?.searchAgainIfDiscarded() }
        }

        paged.collectionChanged
            .sink { [weak self] _ in self?.notifyResults() }
            .store(in: &cancellables)
        // Re-run a search refused during a fetch once the refresh command is
        // idle again. The command reports that through `canExecuteChanged`.
        // The sink also checks for a refresh that a load discarded.
        paged.refreshCommand.canExecuteChanged
            .sink { [weak self] in
                self?.runPendingSearch()
                self?.searchRequests.rerun()
            }
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

    /// Refreshes the results for the current term.
    ///
    /// The refresh command admits one execution at a time and refuses calls
    /// made while a fetch runs. So the request is recorded, and a refused
    /// request runs once the in-flight fetch settles. That fetch reads the
    /// term when it starts, so the latest term always wins. Several calls
    /// made during one fetch cause one more fetch.
    public func searchNow() {
        searchRequests.record(search.searchTerm)
        search.search()
        pendingSearchLock.withLock { searchPending = true }
        runPendingSearch()
    }

    /// After a load that overlapped a refresh, search again if that refresh was
    /// lost. The results then show an older term than the latest request. A
    /// failed first-page fetch is not run again.
    private func searchAgainIfDiscarded() {
        guard !refreshCommand.isExecuting, !paged.loadMoreCommand.isExecuting else { return }
        guard searchRequests.takeOverlap() else { return }
        let shown = paged.items.first.flatMap { resultOwner.term(of: $0) }
        guard let shown,
              let requested = searchRequests.requestedTerm,
              shown != requested,
              !searchRequests.lastFirstPageFetchFailed else { return }
        searchNow()
    }

    private func runPendingSearch() {
        let shouldRun = pendingSearchLock.withLock { () -> Bool in
            guard searchPending, !searchDisposed, !refreshCommand.isExecuting else { return false }
            searchPending = false
            return true
        }
        if shouldRun {
            refreshCommand.execute()
        }
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

    /// Loads and appends the next page. It cannot run while a refresh runs.
    public let loadMoreCommand: AsyncRelayCommand

    private func notifyResults() {
        _notifyPropertyChanged("results")
    }

    private func notifyHasMore() {
        _notifyPropertyChanged("hasMore")
    }

    public override func _onDispose() {
        pendingSearchLock.withLock {
            searchDisposed = true
            searchPending = false
        }
        cancellables.removeAll()
        resultOwner.disposeAll()
        loadMoreCommand.dispose()
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
