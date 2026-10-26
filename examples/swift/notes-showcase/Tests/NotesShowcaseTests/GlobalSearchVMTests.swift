//
// GlobalSearchVMTests — latest-term re-run for GlobalSearchVM.searchNow().
//
// The refresh command refuses an execution while a fetch is in flight. These
// tests type during a held fetch and check that exactly one more fetch runs,
// for the latest term, once the held fetch settles (issue #762).
//
import XCTest
import VMx
@testable import NotesShowcaseCore

/// Repository whose `searchNotes` calls wait while the test holds them.
/// It records the term of every call, so a test can count fetches.
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

    /// The term of each `searchNotes` call, in call order.
    var terms: [String] { lock.withLock { _terms } }

    /// Holds every later `searchNotes` call until `release()`.
    func hold() {
        lock.withLock { holding = true }
    }

    /// Lets held and later `searchNotes` calls run.
    func release() {
        let waiting = lock.withLock { () -> [CheckedContinuation<Void, Never>] in
            holding = false
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
                guard holding else { return true }
                held.append(continuation)
                return false
            }
            if resumeNow { continuation.resume() }
        }
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

    private func buildVM(repo: any NoteRepository) throws -> GlobalSearchVM {
        try GlobalSearchVM.builder()
            .name("global-search")
            .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            .repository(repo)
            .pageSize(5)
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
}
