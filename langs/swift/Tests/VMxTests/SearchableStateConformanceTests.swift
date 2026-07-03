// SearchableState conformance tests — COMP-014..018 + GRP-007..010.
// See spec/06-composite-vm.md, spec/07-group-vm.md, ADR-0014.
//
// All tests drive debounce deterministically via search() (the force-immediate
// path through PassthroughSubject → Publishers.Merge → filteredSubject.send)
// which is synchronous — no XCTestExpectation needed.  This mirrors the
// strategy used for HIER-013 in HierarchicalCompositionTests.swift.

import Combine
import XCTest

@testable import VMx

// Case-insensitive substring predicate — mirrors `ciSubstr` in searchFilter.test.ts.
private func ciSubstr(_ item: String, _ term: String) -> Bool {
    guard !term.isEmpty else { return true }
    return item.lowercased().contains(term.lowercased())
}

final class SearchableStateConformanceTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // MARK: — Composite context (COMP-014..018)

    /// COMP-014 — defaults to empty search term; filtered emits all items.
    func testCOMP014DefaultSearchTermEmitsAllItems() {
        let items = ["apple", "banana", "cherry"]
        let sut = SearchableState<String>(
            items: { items },
            predicate: ciSubstr
        )
        var snap: [[String]] = []
        sut.filtered.sink { snap.append($0) }.store(in: &cancellables)

        XCTAssertEqual(sut.searchTerm, "")
        XCTAssertEqual(snap.last, items)

        sut.dispose()
    }

    /// COMP-015 — setting SearchTerm triggers recompute; filtered narrows to matching items.
    func testCOMP015SearchTermTriggersRecompute() {
        let items = ["apple", "banana", "cherry"]
        let sut = SearchableState<String>(
            items: { items },
            predicate: ciSubstr,
            debounce: .milliseconds(0)
        )
        var snap: [[String]] = []
        sut.filtered.sink { snap.append($0) }.store(in: &cancellables)

        sut.searchTerm = "an"
        sut.search()

        XCTAssertEqual(snap.last, ["banana"])

        sut.dispose()
    }

    /// COMP-016 — search() forces immediate recompute, bypassing debounce.
    func testCOMP016SearchBypassesDebounce() {
        let items = ["one", "two"]
        let sut = SearchableState<String>(
            items: { items },
            predicate: { i, t in t.isEmpty || i == t },
            debounce: .seconds(1)
        )
        var snap: [[String]] = []
        sut.filtered.sink { snap.append($0) }.store(in: &cancellables)

        sut.searchTerm = "two"
        sut.search()

        XCTAssertEqual(snap.last, ["two"])

        sut.dispose()
    }

    /// COMP-017 — user-supplied predicate controls which items match the term.
    func testCOMP017UserSuppliedPredicate() {
        let items = ["a", "bb", "ccc"]
        let sut = SearchableState<String>(
            items: { items },
            predicate: { i, t in i.count > t.count },
            debounce: .milliseconds(0)
        )
        var snap: [[String]] = []
        sut.filtered.sink { snap.append($0) }.store(in: &cancellables)

        sut.searchTerm = "bb"
        sut.search()

        XCTAssertEqual(snap.last, ["ccc"])

        sut.dispose()
    }

    /// COMP-018 — filtered does NOT auto-observe source mutations; explicit search() recomputes.
    func testCOMP018ExplicitSearchRecomputesAfterSourceMutation() {
        var items = ["one"]
        let sut = SearchableState<String>(
            items: { items },
            predicate: { _, _ in true },
            debounce: .milliseconds(0)
        )
        var snap: [[String]] = []
        sut.filtered.sink { snap.append($0) }.store(in: &cancellables)

        let countAfterSubscribe = snap.count
        items.append("two")
        // The "does NOT auto-observe" half: mutating the source must NOT emit a
        // new filtered snapshot on its own.
        XCTAssertEqual(snap.count, countAfterSubscribe,
                       "source mutation must not auto-trigger a filtered emission")

        sut.search()
        // The recompute half: an explicit search() re-reads the source.
        XCTAssertEqual(snap.last, ["one", "two"])

        sut.dispose()
    }

    // MARK: — Group context (GRP-007..010)

    /// GRP-007 — defaults to empty search term (group context).
    func testGRP007DefaultSearchTermGroup() {
        let items = ["x", "y"]
        let sut = SearchableState<String>(
            items: { items },
            predicate: ciSubstr
        )
        XCTAssertEqual(sut.searchTerm, "")
        sut.dispose()
    }

    /// GRP-008 — setting SearchTerm triggers recompute (group context).
    func testGRP008SearchTermTriggersRecomputeGroup() {
        let items = ["x", "yx", "z"]
        let sut = SearchableState<String>(
            items: { items },
            predicate: ciSubstr,
            debounce: .milliseconds(0)
        )
        var snap: [[String]] = []
        sut.filtered.sink { snap.append($0) }.store(in: &cancellables)

        sut.searchTerm = "x"
        sut.search()

        XCTAssertEqual(snap.last, ["x", "yx"])

        sut.dispose()
    }

    /// GRP-009 — search() forces immediate recompute, bypassing debounce (group context).
    func testGRP009SearchBypassesDebounceGroup() {
        let items = ["a", "b"]
        let sut = SearchableState<String>(
            items: { items },
            predicate: { i, t in t.isEmpty || i == t },
            debounce: .seconds(1)
        )
        var snap: [[String]] = []
        sut.filtered.sink { snap.append($0) }.store(in: &cancellables)

        sut.searchTerm = "b"
        sut.search()

        XCTAssertEqual(snap.last, ["b"])

        sut.dispose()
    }

    /// GRP-010 — user-supplied predicate over integers (item > Int(term)) (group context).
    func testGRP010UserSuppliedPredicateIntegers() {
        let items = [1, 2, 3, 4]
        let sut = SearchableState<Int>(
            items: { items },
            predicate: { i, t in i > (Int(t) ?? 0) },
            debounce: .milliseconds(0)
        )
        var snap: [[Int]] = []
        sut.filtered.sink { snap.append($0) }.store(in: &cancellables)

        sut.searchTerm = "2"
        sut.search()

        XCTAssertEqual(snap.last, [3, 4])

        sut.dispose()
    }

    /// Once disposed, `searchTerm` reads empty (parity with C#/Python/TypeScript,
    /// which guard the getter rather than returning the frozen last value), and the
    /// setter + search() are inert.
    func testSearchTermReadsEmptyAfterDispose() {
        let items = ["apple", "banana", "cherry"]
        let sut = SearchableState<String>(items: { items }, predicate: ciSubstr)
        sut.searchTerm = "an"
        XCTAssertEqual(sut.searchTerm, "an")

        sut.dispose()

        XCTAssertEqual(sut.searchTerm, "", "getter reads empty after dispose")
        sut.searchTerm = "xyz" // inert
        XCTAssertEqual(sut.searchTerm, "", "setter is a no-op after dispose")
        sut.search() // inert, no crash
    }
}
