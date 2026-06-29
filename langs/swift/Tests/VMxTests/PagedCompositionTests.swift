//
// PagedCompositionTests.swift — conformance tests for PagedComposition<TVM>.
//
// Claimed IDs: COL-016, COL-017, COL-018, COL-019, COL-020, COL-021.
//
// Ports langs/typescript/tests/conformance/col-016-to-021-paged-composition.test.ts.
// See spec/21-collections.md §5 and ADR-0023.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class PagedCompositionTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // ── COL-016 ──────────────────────────────────────────────────────────────

    /// COL-016 — PagedComposition clamps currentPageIndex to [0, pageCount-1] when source shrinks via setSource.
    func testCOL016CurrentPageIndexReclampedOnSourceShrink() {
        // Given: 10-item source, pageSize=3 → pageCount=4 (ceil(10/3))
        let source = (0..<10).map { "item\($0)" }
        let sut = PagedComposition<String>(source: source, pageSize: 3)
        XCTAssertEqual(sut.pageCount, 4)

        // Navigate to page index 2 (third page)
        sut.currentPageIndex = 2
        XCTAssertEqual(sut.currentPageIndex, 2)

        // Replace source with 4 items — pageCount drops to 2, index re-clamps to 1
        let smaller = (0..<4).map { "item\($0)" }
        sut.setSource(smaller)

        XCTAssertEqual(sut.pageCount, 2) // ceil(4/3)
        XCTAssertEqual(sut.currentPageIndex, 1) // clamped from 2 to pageCount-1=1
    }

    // ── COL-017 ──────────────────────────────────────────────────────────────

    /// COL-017 — PagedComposition pageCount equals ceil(sourceCount / pageSize) and updates via setSource.
    func testCOL017PageCountDerivedFromSourceCountAndPageSize() {
        // Given: pageSize=5, empty source → pageCount=0 (spec §5.4)
        let sut = PagedComposition<Int>(source: [], pageSize: 5)
        XCTAssertEqual(sut.pageCount, 0)

        // 5 items → exactly one page
        sut.setSource(Array(0..<5))
        XCTAssertEqual(sut.pageCount, 1)

        // 6 items → 2 pages
        sut.setSource(Array(0..<6))
        XCTAssertEqual(sut.pageCount, 2)

        // Back to 5 items → 1 page
        sut.setSource(Array(0..<5))
        XCTAssertEqual(sut.pageCount, 1)
    }

    // ── COL-018 ──────────────────────────────────────────────────────────────

    /// COL-018 — PagedComposition moveToFirstPage / moveToLastPage are no-ops when already at bounds.
    func testCOL018NavigationNoOpsAtBounds() {
        // Given: pageSize=3, 8 items → pageCount=3
        let sut = PagedComposition<Int>(source: Array(0..<8), pageSize: 3)
        XCTAssertEqual(sut.pageCount, 3)

        // moveToFirstPage at index 0 is a no-op
        XCTAssertEqual(sut.currentPageIndex, 0)
        sut.moveToFirstPage()
        XCTAssertEqual(sut.currentPageIndex, 0)

        // moveToPreviousPage at lower bound is a no-op
        sut.moveToPreviousPage()
        XCTAssertEqual(sut.currentPageIndex, 0)

        // Navigate to upper bound
        sut.moveToLastPage()
        XCTAssertEqual(sut.currentPageIndex, 2)

        // moveToLastPage when already last is a no-op
        sut.moveToLastPage()
        XCTAssertEqual(sut.currentPageIndex, 2)

        // moveToNextPage at upper bound is a no-op
        sut.moveToNextPage()
        XCTAssertEqual(sut.currentPageIndex, 2)
    }

    // ── COL-019 ──────────────────────────────────────────────────────────────

    /// COL-019 — PagedComposition pageSize==0 disables paging and items yields the full source.
    func testCOL019PageSizeZeroDisablesPagingAndYieldsAllItems() {
        // Given: 7-item source with pageSize=0
        let sut = PagedComposition<Int>(source: Array(0..<7), pageSize: 0)

        XCTAssertFalse(sut.isPagingEnabled)
        XCTAssertEqual(sut.pageCount, 1)
        XCTAssertEqual(sut.currentPageIndex, 0)
        XCTAssertEqual(sut.items, [0, 1, 2, 3, 4, 5, 6])
    }

    // ── COL-020 ──────────────────────────────────────────────────────────────

    /// COL-020 — PagedComposition on empty source: pageCount==0, items empty, navigation is a no-op.
    func testCOL020EmptySourceYieldsZeroPageCountAndNoNavigation() {
        // Given: empty source with pageSize=5
        let sut = PagedComposition<String>(source: [], pageSize: 5)

        XCTAssertEqual(sut.pageCount, 0)
        XCTAssertEqual(sut.currentPageIndex, 0)
        XCTAssertEqual(sut.items, [])

        // All navigation verbs must not move the index
        sut.moveToFirstPage()
        sut.moveToPreviousPage()
        sut.moveToNextPage()
        sut.moveToLastPage()

        XCTAssertEqual(sut.currentPageIndex, 0)
    }

    // ── COL-021 ──────────────────────────────────────────────────────────────

    /// COL-021 — PagedComposition wrapping SearchableState filtered view pages the filtered count.
    func testCOL021FilterThenPageComposition() {
        // Source: 10 items — 4 Alpha items, 6 Zeta items
        let allItems: [String] =
            (0..<4).map { "Alpha\($0)" } + (0..<6).map { "Zeta\($0)" }

        // SearchableState: empty term → all pass; "Alpha" → only Alpha items pass
        let searchable = SearchableState<String>(
            items: { allItems },
            predicate: { item, term in
                term.isEmpty || item.lowercased().hasPrefix(term.lowercased())
            }
        )

        // Track the current filtered snapshot (CurrentValueSubject delivers current value synchronously)
        var filteredSnapshot: [String] = []
        searchable.filtered
            .sink { filteredSnapshot = $0 }
            .store(in: &cancellables)

        // Force immediate recompute so filteredSnapshot reflects all 10 items
        searchable.search()

        // PagedComposition wraps the current filtered snapshot, pageSize=3
        let sut = PagedComposition<String>(source: filteredSnapshot, pageSize: 3)

        // With empty search term all 10 items pass → ceil(10/3) = 4 pages
        XCTAssertEqual(sut.pageCount, 4)

        // Apply search term → forces synchronous recompute → filteredSnapshot has 4 Alpha items
        searchable.searchTerm = "Alpha"
        searchable.search()

        // Update the paged composition source to the filtered result
        sut.setSource(filteredSnapshot)

        XCTAssertEqual(sut.pageCount, 2) // ceil(4/3)

        // Page 0 should yield the first 3 filtered items
        sut.currentPageIndex = 0
        XCTAssertEqual(sut.items, ["Alpha0", "Alpha1", "Alpha2"])

        // Items on page 0 must NOT include any Zeta items
        XCTAssertFalse(sut.items.contains { $0.hasPrefix("Zeta") })

        searchable.dispose()
    }
}
