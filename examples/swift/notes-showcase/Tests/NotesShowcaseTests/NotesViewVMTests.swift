//
// NotesViewVMTests — scenario tests for NotesViewVM.
//
// Ports NotesShowcase.Tests/ViewModels/NotesViewVMTests.cs (C# Avalonia flavor).
// No conformance-ID markers (scenario IDs live in THEME-00x only).
//
// Search determinism: SearchableState debounce is bypassed by calling `search()`
// after setting `searchTerm`; this triggers the `forceSearchSubject` path, which
// fires the `filtered` sink synchronously (no scheduler involvement).
//
import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - Helpers

private func makeRepo(
    loadNotesDelay: TimeInterval = 0,
    saveNoteDelay: TimeInterval = 0,
    deleteNoteDelay: TimeInterval = 0
) -> InMemoryNoteRepository {
    InMemoryNoteRepository(
        seed: SeedData.build(),
        loadAllDelay: 0,
        loadNotesDelay: loadNotesDelay,
        saveNoteDelay: saveNoteDelay,
        deleteNoteDelay: deleteNoteDelay
    )
}

private func buildVM(
    repo: any NoteRepository,
    pageSize: Int = 5
) throws -> NotesViewVM {
    let hub = MessageHub()
    let dispatcher = ImmediateDispatcher.INSTANCE
    return try NotesViewVM.builder()
        .name("notes")
        .services(hub: hub, dispatcher: dispatcher)
        .repository(repo)
        .pageSize(pageSize)
        // Zero debounce + .main scheduler so debounced path resolves quickly;
        // tests drive immediate flush via `vm.search()`.
        .searchDebounce(.milliseconds(0))
        .build()
}

private actor ControlledLoadRepository: NoteRepository {
    private let seed = SeedData.build()
    private var firstLoadStarted = false
    private var startWaiters: [CheckedContinuation<Void, Never>] = []
    private var firstLoadGate: CheckedContinuation<Void, Never>?

    func waitForFirstLoad() async {
        if firstLoadStarted { return }
        await withCheckedContinuation { startWaiters.append($0) }
    }

    func releaseFirstLoad() {
        firstLoadGate?.resume()
        firstLoadGate = nil
    }

    func loadNotes(notebookId: String) async throws -> [NoteModel] {
        if notebookId == "nb-reviews" {
            firstLoadStarted = true
            let waiters = startWaiters
            startWaiters.removeAll()
            waiters.forEach { $0.resume() }
            await withCheckedContinuation { firstLoadGate = $0 }
        }
        return seed.notes.filter { $0.notebookId == notebookId }
    }

    func loadAll() async throws -> (notebooks: [NotebookModel], notes: [NoteModel]) {
        seed
    }

    func searchNotes(
        term: String,
        token: String?,
        pageSize: Int
    ) async throws -> (items: [NoteModel], nextToken: String?) {
        fatalError("not used")
    }

    func saveNote(_ note: NoteModel) async throws { fatalError("not used") }
    func deleteNote(id: String) async throws { fatalError("not used") }
    func addNotebook(_ notebook: NotebookModel) async throws { fatalError("not used") }
    func export(
        notebooks: [NotebookModel],
        notes: [NoteModel],
        path: String
    ) async throws { fatalError("not used") }
}

private func buildAndBind(
    notebookId: String = "nb-reviews",
    pageSize: Int = 5
) async throws -> (NotesViewVM, InMemoryNoteRepository) {
    let repo = makeRepo()
    let vm = try buildVM(repo: repo, pageSize: pageSize)
    try vm.construct()
    await vm.bindTo(notebookId: notebookId)
    return (vm, repo)
}

// MARK: - NotesViewVMTests

final class NotesViewVMTests: XCTestCase {

    // MARK: - bindTo

    func testBindTo_loads_notes_for_the_notebook() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        XCTAssertFalse(vm.visibleItems.isEmpty, "Expected non-empty visible items after bindTo")
        XCTAssertTrue(
            vm.filteredItems.allSatisfy { $0.model.notebookId == "nb-reviews" },
            "All filtered items should belong to nb-reviews"
        )
        XCTAssertEqual("nb-reviews", vm.boundNotebookId)
    }

    // MARK: - Paging

    func testPageSize5_yields_two_pages_for_seven_reviews_notes() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews", pageSize: 5)
        // nb-reviews has 7 notes → ceil(7/5) = 2 pages.
        XCTAssertEqual(2, vm.pageCount, "Expected 2 pages for 7 notes with page size 5")
        XCTAssertEqual(5, vm.visibleItems.count, "First page should have 5 items")
        vm.moveToNextPageCommand.execute()
        XCTAssertEqual(2, vm.visibleItems.count, "Second page should have the remaining 2 items")
    }

    func testPagination_no_op_at_boundaries() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        let first = vm.currentPageIndex
        XCTAssertFalse(vm.moveToFirstPageCommand.canExecute())
        XCTAssertFalse(vm.moveToPreviousPageCommand.canExecute())
        XCTAssertTrue(vm.moveToNextPageCommand.canExecute())
        XCTAssertTrue(vm.moveToLastPageCommand.canExecute())
        vm.moveToFirstPageCommand.execute()  // already at page 0
        XCTAssertEqual(first, vm.currentPageIndex)

        vm.moveToLastPageCommand.execute()
        let last = vm.currentPageIndex
        XCTAssertTrue(vm.moveToFirstPageCommand.canExecute())
        XCTAssertTrue(vm.moveToPreviousPageCommand.canExecute())
        XCTAssertFalse(vm.moveToNextPageCommand.canExecute())
        XCTAssertFalse(vm.moveToLastPageCommand.canExecute())
        vm.moveToNextPageCommand.execute()   // already at last page
        XCTAssertEqual(last, vm.currentPageIndex)
    }

    func testMoveToNextPage_and_back_works() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews", pageSize: 5)
        XCTAssertEqual(0, vm.currentPageIndex)
        vm.moveToNextPageCommand.execute()
        XCTAssertEqual(1, vm.currentPageIndex)
        vm.moveToPreviousPageCommand.execute()
        XCTAssertEqual(0, vm.currentPageIndex)
    }

    func testPageLabel_reflects_current_page_and_count() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews", pageSize: 5)
        XCTAssertEqual("Page 1 of 2", vm.pageLabel)
        XCTAssertEqual("Page 1 of 2", try vm.pageLabelDerived.value)
        vm.moveToNextPageCommand.execute()
        XCTAssertEqual("Page 2 of 2", vm.pageLabel)
        XCTAssertEqual("Page 2 of 2", try vm.pageLabelDerived.value)
    }

    // MARK: - Starred filter

    func testShowStarredOnly_restricts_to_starred_notes() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        vm.showStarredOnly = true
        XCTAssertTrue(
            vm.filteredItems.allSatisfy { $0.starred },
            "Only starred notes should be visible"
        )
        // nb-reviews has 2 starred notes per SeedData.
        XCTAssertFalse(vm.filteredItems.isEmpty, "Expected at least one starred note")
    }

    func testShowStarredOnly_false_restores_all_notes() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        vm.showStarredOnly = true
        let starredCount = vm.filteredItems.count
        vm.showStarredOnly = false
        XCTAssertTrue(
            vm.filteredItems.count > starredCount,
            "Disabling starred filter should show more notes"
        )
    }

    // MARK: - Custom filter predicate

    func testFilter_predicate_restricts_visible_items() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        vm.filter = { $0.title.contains("Q1") }
        XCTAssertEqual(1, vm.filteredItems.count)
        XCTAssertTrue(vm.filteredItems[0].title.contains("Q1"))
        vm.filter = nil
        XCTAssertTrue(vm.filteredItems.count > 1, "Clearing filter should restore all notes")
    }

    func testIsEmpty_true_when_filter_excludes_everything() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        XCTAssertFalse(try vm.isEmptyDerived.value)
        vm.filter = { _ in false }
        XCTAssertTrue(vm.isEmpty)
        XCTAssertTrue(try vm.isEmptyDerived.value)
        XCTAssertTrue(vm.visibleItems.isEmpty)
    }

    // MARK: - Search

    func testSearch_filters_by_title_match() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        let before = vm.filteredItems.count
        XCTAssertTrue(before > 1, "Precondition: multiple notes loaded")

        vm.searchTerm = "Q1"
        vm.search()  // force-flush past the debounce

        XCTAssertEqual(1, vm.filteredItems.count)
        XCTAssertTrue(vm.filteredItems[0].title.contains("Q1"))
    }

    func testSearch_empty_term_restores_all() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        let before = vm.filteredItems.count
        vm.searchTerm = "Q1"
        vm.search()
        XCTAssertEqual(1, vm.filteredItems.count)

        vm.searchTerm = ""
        vm.search()
        XCTAssertEqual(before, vm.filteredItems.count)
    }

    // MARK: - bindTo to a different notebook

    func testBindTo_different_notebook_swaps_items() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        let beforeIds = vm.filteredItems.map { $0.noteId }
        await vm.bindTo(notebookId: "nb-work")
        let afterIds = vm.filteredItems.map { $0.noteId }
        XCTAssertNotEqual(beforeIds, afterIds)
        XCTAssertTrue(
            vm.filteredItems.allSatisfy { $0.model.notebookId == "nb-work" },
            "All filtered items should belong to nb-work after rebind"
        )
    }

    func testOverlappingBindTo_onlyLatestRequestCanCommit() async throws {
        let repo = ControlledLoadRepository()
        let vm = try buildVM(repo: repo)
        try vm.construct()
        let transferableVM = FlagshipTransferBox(vm)

        let first = Task { [transferableVM] in
            await transferableVM.value.bindTo(notebookId: "nb-reviews")
        }
        await repo.waitForFirstLoad()
        let second = Task { [transferableVM] in
            await transferableVM.value.bindTo(notebookId: "nb-work")
        }
        await second.value
        await repo.releaseFirstLoad()
        await first.value

        XCTAssertEqual("nb-work", vm.boundNotebookId)
        XCTAssertTrue(vm.filteredItems.allSatisfy {
            $0.model.notebookId == "nb-work"
        })
    }

    // MARK: - Current selection

    func testCurrent_setter_is_idempotent() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        let first = vm.visibleItems[0]
        vm.current = first
        XCTAssertTrue(vm.current === first)
        vm.current = first  // idempotent
        XCTAssertTrue(vm.current === first)
        vm.current = nil
        XCTAssertNil(vm.current)
    }

    // MARK: - refreshNote

    func testRefreshNote_re_seats_model_and_recomputes_filter() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        // Grab the first note and apply a title filter that matches its current title.
        let original = vm.filteredItems[0].model
        vm.filter = { $0.title == original.title }
        XCTAssertEqual(1, vm.filteredItems.count)

        // Refresh with a new title — should now fall outside the filter.
        let updated = original.with(title: "RENAMED_\(original.title)")
        vm.refreshNote(updated)

        // The re-seated vm's title no longer matches the filter.
        XCTAssertTrue(vm.filteredItems.isEmpty,
                      "Updated note should not pass the old title filter")
    }

    // MARK: - Delete

    func testDeleteNote_removes_from_inner_and_clears_current() async throws {
        let repo = makeRepo(deleteNoteDelay: 0)
        let vm = try buildVM(repo: repo, pageSize: 5)
        try vm.construct()
        await vm.bindTo(notebookId: "nb-personal")

        let before = vm.inner.count
        XCTAssertTrue(before > 0, "Precondition: notes loaded")
        let target = vm.inner.at(0)
        vm.current = target

        // Await the same async relay the UI invokes through the synchronous
        // Command surface. Foreground removal completes before this returns.
        let deleteCommand = try XCTUnwrap(target.deleteCommand as? AsyncRelayCommand)
        try await deleteCommand.executeAsync()

        XCTAssertEqual(before - 1, vm.inner.count,
                       "Inner count should decrement by 1 after delete")
        XCTAssertNil(vm.current, "Current should be cleared when the selected note is deleted")
    }

    // MARK: - Reconstruct

    func testReconstruct_keeps_items_via_rebind() async throws {
        let (vm, _) = try await buildAndBind(notebookId: "nb-reviews")
        let before = vm.filteredItems.count
        try vm.reconstruct()
        // After reconstruct, prior items are torn down.
        await vm.bindTo(notebookId: "nb-reviews")
        XCTAssertEqual(before, vm.filteredItems.count,
                       "Rebind after reconstruct should restore the same item count")
    }

    // MARK: - Global search token paging

    func testRepositorySearchNotes_returnsTokenPagesOverAllNotes() async throws {
        let repo = makeRepo(loadNotesDelay: 0)

        let first = try await repo.searchNotes(term: "review", token: nil, pageSize: 2)

        XCTAssertEqual(2, first.items.count)
        XCTAssertEqual("2", first.nextToken)
        XCTAssertTrue(first.items.allSatisfy {
            "\($0.title) \($0.body) \($0.tags.joined(separator: " "))"
                .lowercased()
                .contains("review")
        })

        let second = try await repo.searchNotes(
            term: "review",
            token: first.nextToken,
            pageSize: 2
        )
        XCTAssertFalse(second.items.isEmpty)
        XCTAssertNotEqual(first.items[0].id, second.items[0].id)
    }

    func testGlobalSearchVM_refreshes_resetsTerms_andLoadsMore() async throws {
        let repo = makeRepo(loadNotesDelay: 0)
        let vm = try GlobalSearchVM.builder()
            .name("global-search")
            .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            .repository(repo)
            .pageSize(2)
            .searchDebounce(.milliseconds(0))
            .build()

        vm.searchTerm = "review"
        try await vm.refreshCommand.executeAsync()
        XCTAssertEqual(2, vm.results.count)
        XCTAssertTrue(vm.hasMore)

        try await vm.loadMoreCommand.executeAsync()
        XCTAssertGreaterThan(vm.results.count, 2)
        let replacedResults = vm.results

        vm.searchTerm = "travel"
        try await vm.refreshCommand.executeAsync()
        XCTAssertTrue(vm.results.allSatisfy { $0.model.notebookId == "nb-personal" })
        let finalResults = vm.results
        vm.dispose()
        XCTAssertTrue((replacedResults + finalResults).allSatisfy { $0.status == .disposed })
    }
}
