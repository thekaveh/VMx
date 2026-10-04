//
// TokenRefreshCursorTests.swift — COL-065: a token-paged refresh keeps
// `items` and `currentToken` describing one loaded prefix (spec 21 §6.2,
// ADR-0136).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class TokenRefreshCursorTests: XCTestCase {
    private typealias Page = ([Int], String?)

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// First page can change between calls; later pages are keyed by token.
    private final class Backend: @unchecked Sendable {
        private let lock = NSLock()
        private var _requested: [String?] = []
        private var _firstPage: Page = ([1, 2], "t2")
        private var _error: Error?

        var requested: [String?] { lock.withLock { _requested } }

        func setFirstPage(_ page: Page) { lock.withLock { _firstPage = page } }

        func setError(_ error: Error) { lock.withLock { _error = error } }

        func fetch(_ token: String?) throws -> Page {
            try lock.withLock {
                _requested.append(token)
                if let _error { throw _error }
                switch token {
                case nil: return _firstPage
                case "t2"?: return ([3, 4], "t3")
                case "t3"?: return ([5, 6], "t4")
                case "t4"?: return ([7], nil)
                default: return ([], nil)
                }
            }
        }
    }

    private struct Offline: Error {}

    private func pager(_ backend: Backend) -> TokenPagedComposition<Int, String> {
        TokenPagedComposition<Int, String>(
            fetchNext: { token in try backend.fetch(token) },
            pagesEqual: { $0 == $1 }
        )
    }

    private func load(_ sut: TokenPagedComposition<Int, String>, _ count: Int) async throws {
        for _ in 0..<count {
            try await sut.loadMoreCommand.executeAsync()
        }
    }

    /// Records collection, property, and LoadMore eligibility signals in order.
    private final class Trace: @unchecked Sendable {
        private let lock = NSLock()
        private var _entries: [String] = []
        var entries: [String] { lock.withLock { _entries } }
        var resets: Int { entries.filter { $0 == "collection:reset" }.count }
        func append(_ entry: String) { lock.withLock { _entries.append(entry) } }
    }

    private func record(_ sut: TokenPagedComposition<Int, String>) -> Trace {
        let trace = Trace()
        sut.collectionChanged
            .sink { event in trace.append(event.action == .reset ? "collection:reset" : "collection:other") }
            .store(in: &cancellables)
        sut.propertyChanged
            .sink { trace.append("property:\($0)") }
            .store(in: &cancellables)
        sut.loadMoreCommand.canExecuteChanged
            .sink { trace.append("loadMore:canExecuteChanged") }
            .store(in: &cancellables)
        return trace
    }

    /// COL-065 — token-paged refresh keeps the cursor aligned with the retained accumulator.
    func testCOL065UnchangedHeadRefreshKeepsCursorSoLoadMoreNeverRefetchesPageTwo() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 3)

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [1, 2, 3, 4, 5, 6])
        XCTAssertEqual(sut.currentToken, "t4")
        XCTAssertTrue(sut.hasMore)

        try await sut.loadMoreCommand.executeAsync()

        XCTAssertEqual(sut.items, [1, 2, 3, 4, 5, 6, 7])
        XCTAssertEqual(backend.requested, [nil, "t2", "t3", nil, "t4"])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
    }

    /// COL-065 — a shorter matching non-terminal head keeps the accumulator and cursor.
    func testShorterMatchingNonTerminalHeadKeepsAccumulatorAndCursor() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 2)
        backend.setFirstPage(([1], "u1"))

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [1, 2, 3, 4])
        XCTAssertEqual(sut.currentToken, "t3")
    }

    /// COL-065 — an unchanged single page adopts a changed opaque token.
    func testUnchangedSinglePageAdoptsChangedOpaqueTokenWithoutReset() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 1)
        backend.setFirstPage(([1, 2], "fresh-t2"))
        let trace = record(sut)

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [1, 2])
        XCTAssertEqual(sut.currentToken, "fresh-t2")
        XCTAssertEqual(trace.resets, 0)
    }

    /// COL-065 — an unchanged single page adopts a newly terminal token.
    func testUnchangedSinglePageAdoptsNewlyTerminalToken() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 1)
        backend.setFirstPage(([1, 2], nil))

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [1, 2])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
        XCTAssertFalse(sut.loadMoreCommand.canExecute())
    }

    /// COL-065 — a changed head replaces the accumulator and adopts the refreshed token.
    func testChangedHeadReplacesAccumulatorAndAdoptsRefreshedToken() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 2)
        backend.setFirstPage(([9, 2], "u2"))
        let trace = record(sut)

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [9, 2])
        XCTAssertEqual(sut.currentToken, "u2")
        XCTAssertEqual(trace.resets, 1)
    }

    /// COL-065 — a terminal first page shorter than the accumulator replaces it.
    func testTerminalFirstPageShorterThanAccumulatorReplacesIt() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 2)
        backend.setFirstPage(([1, 2], nil))

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [1, 2])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
    }

    /// COL-065 — an empty terminal first page clears a non-empty accumulator.
    func testEmptyTerminalFirstPageClearsNonEmptyAccumulator() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 2)
        backend.setFirstPage(([], nil))
        let trace = record(sut)

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
        XCTAssertEqual(trace.resets, 1)
    }

    /// COL-065 — an empty first page with a continuation replaces and adopts the token.
    func testEmptyFirstPageWithContinuationReplacesAndAdoptsToken() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 2)
        backend.setFirstPage(([], "u1"))

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [])
        XCTAssertEqual(sut.currentToken, "u1")
        XCTAssertTrue(sut.hasMore)
    }

    /// COL-065 — a refresh after reaching the end keeps the terminal cursor.
    func testRefreshAfterReachingTheEndKeepsTerminalCursor() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 4)
        let trace = record(sut)

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [1, 2, 3, 4, 5, 6, 7])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
        XCTAssertFalse(sut.loadMoreCommand.canExecute())
        XCTAssertEqual(trace.resets, 0)
    }

    /// COL-065 — the no-mutation branch publishes properties, then the command signal.
    func testNoMutationBranchPublishesPropertiesThenCommandSignal() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 3)
        let trace = record(sut)

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(trace.entries, [
            "property:items",
            "property:currentToken",
            "property:hasMore",
            "loadMore:canExecuteChanged",
        ])
    }

    /// COL-065 — the replacement branch publishes one reset, properties, then the command signal.
    func testReplacementBranchPublishesResetPropertiesThenCommandSignal() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 3)
        backend.setFirstPage(([8, 9], "u2"))
        let trace = record(sut)

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(trace.entries, [
            "collection:reset",
            "property:items",
            "property:currentToken",
            "property:hasMore",
            "loadMore:canExecuteChanged",
        ])
    }

    func testLoadStartedDuringRefreshMakesTheRefreshResultStale() async throws {
        let gate = NSLock()
        var requested: [String?] = []
        var continuations: [CheckedContinuation<Page, Error>] = []
        let refreshStarted = expectation(description: "refresh fetch started")
        let loadStarted = expectation(description: "second load fetch started")
        let sut = TokenPagedComposition<Int, String>(
            fetchNext: { token in
                if token == nil && gate.withLock({ requested.isEmpty }) {
                    gate.withLock { requested.append(token) }
                    return ([1, 2], "t2")
                }
                return try await withCheckedThrowingContinuation { continuation in
                    gate.withLock {
                        requested.append(token)
                        continuations.append(continuation)
                    }
                    if token == nil { refreshStarted.fulfill() } else { loadStarted.fulfill() }
                }
            },
            pagesEqual: { $0 == $1 }
        )
        try await sut.loadMoreCommand.executeAsync()

        let refresh = Task { try await sut.refreshCommand.executeAsync() }
        await fulfillment(of: [refreshStarted], timeout: 2.0)
        let load = Task { try await sut.loadMoreCommand.executeAsync() }
        await fulfillment(of: [loadStarted], timeout: 2.0)
        gate.withLock { continuations[0] }.resume(returning: ([9], "stale"))
        try await refresh.value
        gate.withLock { continuations[1] }.resume(returning: ([3, 4], "t3"))
        try await load.value

        XCTAssertEqual(gate.withLock { requested }, [nil, nil, "t2"])
        XCTAssertEqual(sut.items, [1, 2, 3, 4])
        XCTAssertEqual(sut.currentToken, "t3")
    }

    func testFailedRefreshFetchLeavesItemsCursorAndNotificationsUntouched() async throws {
        let backend = Backend()
        let sut = pager(backend)
        try await load(sut, 2)
        backend.setError(Offline())
        let trace = record(sut)

        do {
            try await sut.refreshCommand.executeAsync()
            XCTFail("refresh should rethrow the fetch failure")
        } catch is Offline {}

        XCTAssertEqual(sut.items, [1, 2, 3, 4])
        XCTAssertEqual(sut.currentToken, "t3")
        XCTAssertEqual(trace.entries, [])
        XCTAssertFalse(sut.refreshCommand.isExecuting)
    }

    func testDisposalBeforeRetainedPrefixRefreshCompletesLeavesStateUntouched() async throws {
        let backend = Backend()
        let gate = NSLock()
        var hold = false
        var continuation: CheckedContinuation<Page, Error>?
        let refreshStarted = expectation(description: "refresh fetch started")
        let sut = TokenPagedComposition<Int, String>(
            fetchNext: { token in
                guard gate.withLock({ hold }) else { return try backend.fetch(token) }
                return try await withCheckedThrowingContinuation { cont in
                    gate.withLock { continuation = cont }
                    refreshStarted.fulfill()
                }
            },
            pagesEqual: { $0 == $1 }
        )
        try await load(sut, 2)
        gate.withLock { hold = true }
        let trace = record(sut)

        let refresh = Task { try await sut.refreshCommand.executeAsync() }
        await fulfillment(of: [refreshStarted], timeout: 2.0)
        sut.dispose()
        gate.withLock { continuation }?.resume(returning: ([1, 2], "t2"))
        try await refresh.value

        XCTAssertEqual(sut.items, [1, 2, 3, 4])
        XCTAssertEqual(sut.currentToken, "t3")
        XCTAssertEqual(trace.entries, [])
    }

    func testRetainedAndReplacedItemVMsAreNeverDisposedByTheComposition() async throws {
        func vm(_ name: String) throws -> ComponentVM {
            try ComponentVM.builder().name(name).withNullServices().build()
        }
        let loaded = try ["a", "b", "c", "d"].map(vm)
        let equalHead = try ["a", "b"].map(vm)
        let changedHead = try ["x", "y"].map(vm)
        let gate = NSLock()
        var refreshPage = equalHead
        var firstLoad = true
        let sut = TokenPagedComposition<ComponentVM, String>(
            fetchNext: { token in
                gate.withLock { () -> ([ComponentVM], String?) in
                    if token != nil { return (Array(loaded[2...]), "t3") }
                    if firstLoad {
                        firstLoad = false
                        return (Array(loaded[..<2]), "t2")
                    }
                    return (refreshPage, "t2")
                }
            },
            autoConstructOnAdd: true,
            pagesEqual: { left, right in left.map(\.name) == right.map(\.name) }
        )
        try await sut.loadMoreCommand.executeAsync()
        try await sut.loadMoreCommand.executeAsync()

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items.map { ObjectIdentifier($0) }, loaded.map { ObjectIdentifier($0) })
        XCTAssertEqual(sut.currentToken, "t3")
        XCTAssertEqual(equalHead.map(\.status), [.destructed, .destructed])

        gate.withLock { refreshPage = changedHead }
        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items.map { ObjectIdentifier($0) }, changedHead.map { ObjectIdentifier($0) })
        XCTAssertTrue(changedHead.allSatisfy(\.isConstructed))
        XCTAssertTrue(loaded.allSatisfy { $0.status == .constructed })
    }
}
