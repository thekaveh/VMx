//
// GlobalSearchVMTests — latest-term re-run for GlobalSearchVM.searchNow().
//
// The refresh command refuses an execution while a fetch is in flight. These
// tests type during a held fetch and check that exactly one more fetch runs,
// for the latest term, once the held fetch settles (issue #762).
//
// The "Load more" tests check that the loaded pages never mix two search
// terms (issue #1070).
//
import Combine
import XCTest
import VMx
@testable import NotesShowcaseCore

/// Repository whose `searchNotes` calls wait while the test holds them.
/// It records the term and the token of every call, so a test can count fetches.
private final class HeldSearchRepository: NoteRepository, @unchecked Sendable {
    private let store = InMemoryNoteRepository(
        seed: SeedData.build(),
        loadAllDelay: 0,
        loadNotesDelay: 0
    )
    private let lock = NSLock()
    private var holding = true
    private var held: [CheckedContinuation<Void, Never>] = []
    private var _terms: [String] = []
    private var _tokens: [String?] = []
    private var _failingTerm: String?
    private var _emptyLaterPages = false
    private var _failLaterPages = false
    private var _holdFirstPagesOnly = false

    /// Makes later pages throw.
    func failLaterPages() {
        lock.withLock { _failLaterPages = true }
    }

    /// Holds later first-page calls until `release()`. Other pages run.
    func holdFirstPages() {
        lock.withLock {
            holding = true
            _holdFirstPagesOnly = true
        }
    }

    /// Makes later pages come back empty, as after the notes are deleted.
    func returnEmptyLaterPages() {
        lock.withLock { _emptyLaterPages = true }
    }

    private struct SearchFailed: Error {}

    /// Makes later first-page searches for `term` throw.
    func failFirstPages(for term: String?) {
        lock.withLock { _failingTerm = term }
    }

    /// The term of each `searchNotes` call, in call order.
    var terms: [String] { lock.withLock { _terms } }

    /// The token of each `searchNotes` call, in call order.
    var tokens: [String?] { lock.withLock { _tokens } }

    /// Holds every later `searchNotes` call until `release()`.
    func hold() {
        lock.withLock { holding = true }
    }

    /// Lets held and later `searchNotes` calls run.
    func release() {
        let waiting = lock.withLock { () -> [CheckedContinuation<Void, Never>] in
            holding = false
            _holdFirstPagesOnly = false
            defer { held.removeAll() }
            return held
        }
        waiting.forEach { $0.resume() }
    }

    func searchNotes(
        term: String,
        token: String?,
        pageSize: Int
    ) async throws -> (items: [NoteModel], nextToken: String?) {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            let resumeNow = lock.withLock { () -> Bool in
                _terms.append(term)
                _tokens.append(token)
                guard holding, !_holdFirstPagesOnly || token == nil else { return true }
                held.append(continuation)
                return false
            }
            if resumeNow { continuation.resume() }
        }
        if token == nil, lock.withLock({ _failingTerm }) == term { throw SearchFailed() }
        if token != nil, lock.withLock({ _emptyLaterPages }) { return ([], nil) }
        if token != nil, lock.withLock({ _failLaterPages }) { throw SearchFailed() }
        return try await store.searchNotes(term: term, token: token, pageSize: pageSize)
    }

    func loadAll() async throws -> (notebooks: [NotebookModel], notes: [NoteModel]) {
        try await store.loadAll()
    }

    func loadNotes(notebookId: String) async throws -> [NoteModel] {
        try await store.loadNotes(notebookId: notebookId)
    }

    func saveNote(_ note: NoteModel) async throws { try await store.saveNote(note) }
    func deleteNote(id: String) async throws { try await store.deleteNote(id: id) }
    func addNotebook(_ notebook: NotebookModel) async throws { try await store.addNotebook(notebook) }
    func export(
        notebooks: [NotebookModel],
        notes: [NoteModel],
        path: String
    ) async throws {
        try await store.export(notebooks: notebooks, notes: notes, path: path)
    }
}

final class GlobalSearchVMTests: XCTestCase {

    // MARK: - Helpers

    private func buildVM(repo: any NoteRepository, pageSize: Int = 5) throws -> GlobalSearchVM {
        try GlobalSearchVM.builder()
            .name("global-search")
            .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            .repository(repo)
            .pageSize(pageSize)
            // Tests force each search through `searchNow()`; keep the
            // debounced path idle for the test's lifetime.
            .searchDebounce(.seconds(3600))
            .build()
    }

    /// Polls `condition` with 1 ms sleeps so cooperative-pool fetch tasks can
    /// advance. Returns without failing; the caller asserts the outcome.
    private func waitUntil(_ condition: @escaping () -> Bool, attempts: Int = 2_000) async {
        for _ in 0..<attempts {
            if condition() { return }
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
    }

    /// Waits until `count` fetches ran and the refresh command is idle, then
    /// waits a further 50 ms so that an unwanted extra fetch can show up.
    private func settle(
        _ vm: GlobalSearchVM,
        _ repo: HeldSearchRepository,
        fetches count: Int
    ) async {
        await waitUntil { repo.terms.count >= count && !vm.refreshCommand.isExecuting }
        try? await Task.sleep(nanoseconds: 50_000_000)
        await waitUntil { !vm.refreshCommand.isExecuting }
    }

    // MARK: - Tests

    func testSearchNow_duringAFetch_leavesResultsForTheLatestTerm() async throws {
        let repo = HeldSearchRepository()
        let vm = try buildVM(repo: repo)
        defer { vm.dispose() }

        vm.searchTerm = "Q"
        vm.searchNow()
        await waitUntil { repo.terms.count == 1 }
        XCTAssertEqual(["Q"], repo.terms)

        vm.searchTerm = "Travel"
        vm.searchNow()
        repo.release()

        await settle(vm, repo, fetches: 2)
        XCTAssertEqual(["Travel ideas"], vm.results.map { $0.title })
    }

    func testSearchNow_runsOnceWhenIdle_andOnceMoreForCallsDuringAFetch() async throws {
        let repo = HeldSearchRepository()
        let vm = try buildVM(repo: repo)
        defer { vm.dispose() }

        // Idle: the call starts a fetch at once, and nothing re-runs it.
        vm.searchTerm = "review"
        vm.searchNow()
        XCTAssertTrue(vm.refreshCommand.isExecuting, "an idle searchNow() starts a fetch at once")
        await waitUntil { repo.terms.count == 1 }
        repo.release()
        await settle(vm, repo, fetches: 1)
        XCTAssertEqual(["review"], repo.terms)

        // Busy: three calls during one fetch cause exactly one more fetch,
        // for the latest term.
        repo.hold()
        vm.searchTerm = "Q"
        vm.searchNow()
        await waitUntil { repo.terms.count == 2 }
        XCTAssertEqual(["review", "Q"], repo.terms)

        for term in ["T", "Tr", "Travel"] {
            vm.searchTerm = term
            vm.searchNow()
        }
        repo.release()

        await settle(vm, repo, fetches: 3)
        XCTAssertEqual(["review", "Q", "Travel"], repo.terms)
        XCTAssertEqual(["Travel ideas"], vm.results.map { $0.title })
    }

    func testSearchNow_refusedBeforeDispose_doesNotRunAfterDispose() async throws {
        let repo = HeldSearchRepository()
        let vm = try buildVM(repo: repo)

        vm.searchTerm = "Q"
        vm.searchNow()
        await waitUntil { repo.terms.count == 1 }

        vm.searchTerm = "Travel"
        vm.searchNow()
        vm.dispose()
        repo.release()

        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(["Q"], repo.terms)
        XCTAssertTrue(vm.results.isEmpty)
    }

    private func matches(_ note: NoteVM, _ term: String) -> Bool {
        let model = note.model
        return "\(model.title) \(model.body) \(model.tags.joined(separator: " "))"
            .lowercased()
            .contains(term)
    }

    func testLoadMore_afterAnUnsearchedTermEdit_continuesTheTermOfTheLoadedPages() async throws {
        let repo = HeldSearchRepository()
        repo.release()
        let vm = try buildVM(repo: repo, pageSize: 1)
        defer { vm.dispose() }

        vm.searchTerm = "review"
        try await vm.refreshCommand.executeAsync()
        // Edit the term without a search, as the C# view does before "Search".
        vm.searchTerm = "plan"
        try await vm.loadMoreCommand.executeAsync()

        XCTAssertEqual(["review", "review"], repo.terms)
        XCTAssertEqual([nil, "1"], repo.tokens)
        let results = vm.results
        XCTAssertEqual(2, results.count)
        XCTAssertTrue(results.allSatisfy { matches($0, "review") })
    }

    func testLoadMore_duringARefresh_endsOnTheCurrentTerm() async throws {
        let repo = HeldSearchRepository()
        repo.release()
        let vm = try buildVM(repo: repo, pageSize: 1)
        defer { vm.dispose() }

        vm.searchTerm = "review"
        try await vm.refreshCommand.executeAsync()
        repo.hold()
        vm.searchTerm = "plan"
        vm.searchNow()
        await waitUntil { repo.terms.count == 2 }
        XCTAssertTrue(vm.refreshCommand.isExecuting, "the refresh waits in the repository")
        vm.loadMoreCommand.execute()
        repo.release()

        let idle = { !vm.refreshCommand.isExecuting && !vm.loadMoreCommand.isExecuting }
        await waitUntil(idle)
        try await Task.sleep(nanoseconds: 50_000_000)
        await waitUntil(idle)

        let results = vm.results
        let ids = results.map { $0.model.id }
        XCTAssertFalse(results.isEmpty)
        let sharedTerms = ["review", "plan"].filter { term in
            results.allSatisfy { matches($0, term) }
        }
        XCTAssertFalse(sharedTerms.isEmpty, "results \(ids) mix two terms")
        XCTAssertEqual(["plan"], sharedTerms, "results \(ids)")
    }

    func testLoadMore_thenASearchBeforeItsTaskStarts_endsOnTheCurrentTerm() async throws {
        try await runLoadMoreThenSearchRace(emptyLaterPages: false)
    }

    func testLoadMore_ofAnEmptyPage_thenASearchBeforeItsTaskStarts_endsOnTheCurrentTerm() async throws {
        try await runLoadMoreThenSearchRace(emptyLaterPages: true)
    }

    private func runLoadMoreThenSearchRace(emptyLaterPages: Bool) async throws {
        // The load is admitted first, and its task starts on another thread. The
        // search can start a refresh before that task runs. The order varies, so
        // the test repeats the steps.
        for attempt in 1...30 {
            let repo = HeldSearchRepository()
            repo.release()
            if emptyLaterPages { repo.returnEmptyLaterPages() }
            let vm = try buildVM(repo: repo, pageSize: 1)
            vm.searchTerm = "review"
            try await vm.refreshCommand.executeAsync()

            vm.loadMoreCommand.execute()
            vm.searchTerm = "plan"
            vm.searchNow()
            let idle = { !vm.refreshCommand.isExecuting && !vm.loadMoreCommand.isExecuting }
            await waitUntil(idle)
            try await Task.sleep(nanoseconds: 5_000_000)
            await waitUntil(idle)

            let results = vm.results
            let ids = results.map { $0.model.id }
            vm.dispose()
            XCTAssertFalse(results.isEmpty, "attempt \(attempt)")
            XCTAssertTrue(
                results.allSatisfy { matches($0, "plan") },
                "attempt \(attempt): results \(ids)"
            )
        }
    }

    func testRefresh_forANewTermWhoseFirstPageMatches_dropsTheOldTermPages() async throws {
        let repo = HeldSearchRepository()
        repo.release()
        let vm = try buildVM(repo: repo, pageSize: 1)
        defer { vm.dispose() }

        try await vm.refreshCommand.executeAsync()
        try await vm.loadMoreCommand.executeAsync()
        XCTAssertEqual(["note-01", "note-02"], vm.results.map { $0.model.id })
        // The first "review" page is note-01 again, the head of the loaded pages.
        vm.searchTerm = "review"
        try await vm.refreshCommand.executeAsync()
        try await vm.loadMoreCommand.executeAsync()

        XCTAssertEqual(["review", "review"], Array(repo.terms.suffix(2)))
        XCTAssertEqual([nil, "1"], Array(repo.tokens.suffix(2)))
        let results = vm.results
        XCTAssertEqual(2, results.count)
        XCTAssertTrue(results.allSatisfy { matches($0, "review") })
    }

    func testASearchDuringALoad_fetchesTheNewTermOnce() async throws {
        let repo = HeldSearchRepository()
        repo.release()
        let vm = try buildVM(repo: repo, pageSize: 1)
        defer { vm.dispose() }
        vm.searchTerm = "review"
        try await vm.refreshCommand.executeAsync()

        // The load fetches first, so the refresh that starts later discards it.
        repo.hold()
        vm.loadMoreCommand.execute()
        await waitUntil { repo.terms.count == 2 }
        vm.searchTerm = "plan"
        vm.searchNow()
        await waitUntil { repo.terms.count == 3 }
        repo.release()
        let idle = { !vm.refreshCommand.isExecuting && !vm.loadMoreCommand.isExecuting }
        await waitUntil(idle)
        try await Task.sleep(nanoseconds: 50_000_000)
        await waitUntil(idle)

        XCTAssertEqual(["review", "review", "plan"], repo.terms)
        XCTAssertEqual([nil, "1", nil], repo.tokens)
        XCTAssertTrue(vm.results.allSatisfy { matches($0, "plan") })
    }

    func testLoadMore_afterAFailedSearch_doesNotRetryThatSearch() async throws {
        let repo = HeldSearchRepository()
        repo.release()
        let vm = try buildVM(repo: repo, pageSize: 1)
        defer { vm.dispose() }
        vm.searchTerm = "review"
        try await vm.refreshCommand.executeAsync()
        repo.failFirstPages(for: "plan")
        vm.searchTerm = "plan"
        vm.searchNow()
        await waitUntil { repo.terms.count == 2 && !vm.refreshCommand.isExecuting }
        repo.failFirstPages(for: nil)

        try await vm.loadMoreCommand.executeAsync()
        try await Task.sleep(nanoseconds: 50_000_000)
        await waitUntil { !vm.refreshCommand.isExecuting }

        XCTAssertEqual(["review", "plan", "review"], repo.terms)
        XCTAssertEqual([nil, nil, "1"], repo.tokens)
        XCTAssertEqual(2, vm.results.count)
    }

    // MARK: - A load that discards a refresh

    private enum LaterPage { case normal, empty, failing }

    /// Counts the events that a test hook sees.
    private final class EventCounter: @unchecked Sendable {
        private let lock = NSLock()
        private var count = 0
        func next() -> Int { lock.withLock { count += 1; return count } }
    }

    /// Runs the order in which the load discards the refresh. The second
    /// `canExecuteChanged` event of "Load more" comes from the inner load's
    /// admission. That is after the in-flight check and before the load starts.
    /// The hook starts the "plan" refresh there and waits for its fetch.
    private func runDiscardedRefresh(
        laterPage: LaterPage,
        failRefresh: Bool = false
    ) async throws -> (GlobalSearchVM, HeldSearchRepository) {
        let repo = HeldSearchRepository()
        repo.release()
        let vm = try buildVM(repo: repo, pageSize: 1)
        vm.searchTerm = "review"
        try await vm.refreshCommand.executeAsync()
        switch laterPage {
        case .normal: break
        case .empty: repo.returnEmptyLaterPages()
        case .failing: repo.failLaterPages()
        }
        if failRefresh { repo.failFirstPages(for: "plan") }

        let events = EventCounter()
        let hook = vm.loadMoreCommand.canExecuteChanged.sink { [vm, repo] in
            guard events.next() == 2 else { return }
            repo.holdFirstPages()
            vm.searchTerm = "plan"
            vm.searchNow()
            let deadline = Date().addingTimeInterval(2)
            while !repo.terms.contains("plan") && Date() < deadline { usleep(100) }
        }
        vm.loadMoreCommand.execute()
        await waitUntil { !vm.loadMoreCommand.isExecuting }
        try await Task.sleep(nanoseconds: 20_000_000)
        repo.release()
        let idle = { !vm.refreshCommand.isExecuting && !vm.loadMoreCommand.isExecuting }
        await waitUntil(idle)
        try await Task.sleep(nanoseconds: 100_000_000)
        await waitUntil(idle)
        hook.cancel()

        // The "plan" refresh fetched before the load, so the load discarded it.
        let calls = zip(repo.terms, repo.tokens).map { "\($0)@\($1 ?? "nil")" }
        let refreshAt = calls.firstIndex(of: "plan@nil")
        let loadAt = calls.firstIndex(of: "review@1")
        XCTAssertNotNil(refreshAt, "calls \(calls)")
        XCTAssertNotNil(loadAt, "calls \(calls)")
        if let refreshAt, let loadAt {
            XCTAssertLessThan(refreshAt, loadAt, "calls \(calls)")
        }
        return (vm, repo)
    }

    func testADiscardedRefresh_runsAgain_afterANormalPage() async throws {
        let (vm, _) = try await runDiscardedRefresh(laterPage: .normal)
        defer { vm.dispose() }
        XCTAssertFalse(vm.results.isEmpty)
        XCTAssertTrue(vm.results.allSatisfy { matches($0, "plan") })
    }

    func testADiscardedRefresh_runsAgain_afterAnEmptyPage() async throws {
        let (vm, _) = try await runDiscardedRefresh(laterPage: .empty)
        defer { vm.dispose() }
        XCTAssertFalse(vm.results.isEmpty)
        XCTAssertTrue(vm.results.allSatisfy { matches($0, "plan") })
    }

    func testADiscardedRefresh_runsAgain_afterAFailedPage() async throws {
        let (vm, _) = try await runDiscardedRefresh(laterPage: .failing)
        defer { vm.dispose() }
        XCTAssertFalse(vm.results.isEmpty)
        XCTAssertTrue(vm.results.allSatisfy { matches($0, "plan") })
    }

    func testADiscardedRefreshThatFailed_doesNotRunAgain() async throws {
        let (vm, repo) = try await runDiscardedRefresh(laterPage: .normal, failRefresh: true)
        defer { vm.dispose() }
        let planFirstPages = zip(repo.terms, repo.tokens).filter { $0.0 == "plan" && $0.1 == nil }
        XCTAssertEqual(1, planFirstPages.count)
    }
}
