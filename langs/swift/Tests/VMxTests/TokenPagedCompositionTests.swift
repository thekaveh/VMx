//
// TokenPagedCompositionTests.swift — COL-024..COL-031.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class TokenPagedCompositionTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// COL-024 — token-paged initial state.
    func testCOL024InitialState() {
        let sut = TokenPagedComposition<Int, String>(
            fetchNext: { token in token == nil ? ([1, 2], "next") : ([], nil) }
        )

        XCTAssertEqual(sut.items, [])
        XCTAssertNil(sut.currentToken)
        XCTAssertTrue(sut.hasMore)
        XCTAssertTrue(sut.loadMoreCommand.canExecute())
    }

    /// COL-025 — loadMore appends returned items and advances token.
    func testCOL025LoadMoreAppendsAndAdvancesToken() async throws {
        var calls: [String?] = []
        let sut = TokenPagedComposition<Int, String>(fetchNext: { token in
            calls.append(token)
            return token == nil ? ([1, 2], "two") : ([3], nil)
        })

        try await sut.loadMoreCommand.executeAsync()
        XCTAssertEqual(sut.items, [1, 2])
        XCTAssertEqual(sut.currentToken, "two")
        XCTAssertTrue(sut.hasMore)

        try await sut.loadMoreCommand.executeAsync()
        XCTAssertEqual(sut.items, [1, 2, 3])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
        // Catalog COL-025: the later load passes the advanced token to fetchNext
        // (not merely "fetch ran twice").
        XCTAssertEqual(calls, [nil, "two"])
    }

    func testLoadMoreDoesNotMutateOrNotifyWhenDisposedDuringFetch() async throws {
        var continuation: CheckedContinuation<([Int], String?), Error>?
        let fetchStarted = expectation(description: "loadMore fetch started")
        let sut = TokenPagedComposition<Int, String>(fetchNext: { _ in
            try await withCheckedThrowingContinuation { cont in
                continuation = cont
                fetchStarted.fulfill()
            }
        })
        var collectionEvents = 0
        var propertyEvents = 0
        sut.collectionChanged.sink { _ in collectionEvents += 1 }.store(in: &cancellables)
        sut.propertyChanged.sink { _ in propertyEvents += 1 }.store(in: &cancellables)

        let run = Task { try await sut.loadMoreCommand.executeAsync() }
        await fulfillment(of: [fetchStarted], timeout: 2.0)
        sut.dispose()
        continuation?.resume(returning: ([1, 2], "next"))
        try await run.value

        XCTAssertEqual(sut.items, [])
        XCTAssertNil(sut.currentToken)
        XCTAssertTrue(sut.hasMore)
        XCTAssertEqual(collectionEvents, 0)
        XCTAssertEqual(propertyEvents, 0)
    }

    /// COL-026 — terminal token disables loadMore.
    func testCOL026TerminalTokenDisablesLoadMore() async throws {
        let sut = TokenPagedComposition<Int, String>(
            fetchNext: { _ in ([1], nil) }
        )

        try await sut.loadMoreCommand.executeAsync()

        XCTAssertFalse(sut.hasMore)
        XCTAssertFalse(sut.loadMoreCommand.canExecute())
    }

    /// COL-027 — refresh clears and refetches first page.
    func testCOL027RefreshRefetchesFirstPage() async throws {
        var pages: [([Int], String?)] = [([1, 2], "next"), ([9], nil)]
        let sut = TokenPagedComposition<Int, String>(fetchNext: { token in
            XCTAssertNil(token)
            return pages.removeFirst()
        })

        try await sut.loadMoreCommand.executeAsync()
        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [9])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
    }

    func testRefreshDoesNotMutateOrNotifyWhenDisposedDuringFetch() async throws {
        var continuation: CheckedContinuation<([Int], String?), Error>?
        let fetchStarted = expectation(description: "refresh fetch started")
        let sut = TokenPagedComposition<Int, String>(fetchNext: { _ in
            try await withCheckedThrowingContinuation { cont in
                continuation = cont
                fetchStarted.fulfill()
            }
        })
        var collectionEvents = 0
        var propertyEvents = 0
        sut.collectionChanged.sink { _ in collectionEvents += 1 }.store(in: &cancellables)
        sut.propertyChanged.sink { _ in propertyEvents += 1 }.store(in: &cancellables)

        let run = Task { try await sut.refreshCommand.executeAsync() }
        await fulfillment(of: [fetchStarted], timeout: 2.0)
        sut.dispose()
        continuation?.resume(returning: ([9], nil))
        try await run.value

        XCTAssertEqual(sut.items, [])
        XCTAssertNil(sut.currentToken)
        XCTAssertTrue(sut.hasMore)
        XCTAssertEqual(collectionEvents, 0)
        XCTAssertEqual(propertyEvents, 0)
    }

    /// COL-028 — refresh dedup guard suppresses redundant mutation.
    func testCOL028RefreshDedupSuppressesRedundantMutation() async throws {
        let sut = TokenPagedComposition<Int, String>(
            fetchNext: { _ in ([1, 2], "next") },
            pagesEqual: { $0 == $1 }
        )
        var events = 0
        sut.collectionChanged.sink { _ in events += 1 }.store(in: &cancellables)

        try await sut.loadMoreCommand.executeAsync()
        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [1, 2])
        XCTAssertEqual(events, 1)
    }

    /// COL-029 — collectionChanged uses reset events.
    func testCOL029CollectionChangedUsesReset() async throws {
        let sut = TokenPagedComposition<Int, String>(
            fetchNext: { _ in ([1, 2], nil) }
        )
        var actions: [CollectionChangedAction] = []
        sut.collectionChanged.sink { actions.append($0.action) }.store(in: &cancellables)

        try await sut.loadMoreCommand.executeAsync()

        XCTAssertEqual(actions, [.reset])
    }

    /// COL-030 — autoConstructOnAdd constructs component VMs added by a page.
    func testCOL030AutoConstructsAddedComponentVMs() async throws {
        let child = try ComponentVM.builder().name("child").withNullServices().build()
        let sut = TokenPagedComposition<ComponentVM, String>(
            fetchNext: { _ in ([child], nil) },
            autoConstructOnAdd: true
        )

        try await sut.loadMoreCommand.executeAsync()

        XCTAssertTrue(child.isConstructed)
    }

    /// COL-031 — PagedComposition observes CompositeVM collection changes.
    func testCOL031PagedCompositionObservesCompositeChanges() throws {
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("source")
            .withNullServices()
            .children { [] }
            .build()
        let sut = PagedComposition<ComponentVM>(sourceComposite: composite, pageSize: 2)
        var seen: [String] = []
        sut.propertyChanged.sink { seen.append($0) }.store(in: &cancellables)

        composite.add(try ComponentVM.builder().name("a").withNullServices().build())

        XCTAssertEqual(sut.pageCount, 1)
        XCTAssertTrue(seen.contains("items"))
    }
}
