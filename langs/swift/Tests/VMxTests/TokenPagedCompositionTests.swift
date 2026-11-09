//
// TokenPagedCompositionTests.swift — COL-024..COL-031.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-15).
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

        XCTAssertTrue(sut.items.isEmpty)
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

    func testAutoConstructReentrantDisposeDoesNotCommitOrFault() async throws {
        var sut: TokenPagedComposition<ComponentVM, String>!
        let child = try ComponentVM.builder()
            .name("child")
            .withNullServices()
            .onConstruct { sut.dispose() }
            .build()
        sut = TokenPagedComposition<ComponentVM, String>(
            fetchNext: { _ in ([child], "next") },
            autoConstructOnAdd: true
        )
        var collectionEvents = 0
        var propertyEvents = 0
        sut.collectionChanged.sink { _ in collectionEvents += 1 }.store(in: &cancellables)
        sut.propertyChanged.sink { _ in propertyEvents += 1 }.store(in: &cancellables)

        try await sut.loadMoreCommand.executeAsync()

        XCTAssertTrue(child.isConstructed)
        XCTAssertTrue(sut.items.isEmpty)
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

    /// Thread-safe fetch harness for the #1161 regressions (spec 21 §6.2,
    /// ADR-0169). Pages [1] and [101] load; then a refresh fetch can be held.
    private final class TerminalAfterAdmissionHarness: @unchecked Sendable {
        let lock = NSLock()
        var calls: [String?] = []
        var holdNextFirstPage = 0
        var held: [CheckedContinuation<([Int], String?), Error>] = []
        let heldStarted = DispatchSemaphore(value: 0)
        var resets = 0
        let resetSeen = DispatchSemaphore(value: 0)

        func fetch(_ token: String?) async throws -> ([Int], String?) {
            let hold = lock.withLock { () -> Bool in
                calls.append(token)
                guard token == nil, holdNextFirstPage > 0 else { return false }
                holdNextFirstPage -= 1
                return true
            }
            if hold {
                return try await withCheckedThrowingContinuation { continuation in
                    lock.withLock { held.append(continuation) }
                    heldStarted.signal()
                }
            }
            // Page 1. Before the fix a gated-out load refetched it here.
            return token == nil ? ([1], "1") : ([101], "2")
        }

        func takeHeld() -> CheckedContinuation<([Int], String?), Error>? {
            lock.withLock { held.isEmpty ? nil : held.removeFirst() }
        }

        var callCount: Int { lock.withLock { calls.count } }
        func calls(since start: Int) -> [String?] { lock.withLock { Array(calls[start...]) } }
    }

    /// COL-026 / #1161 — a refresh commits a terminal token after loadMore was
    /// admitted but before its body starts. The load fetches nothing and appends
    /// nothing; before the fix it refetched page 1 and appended it again.
    func testCOL026TerminalTokenCommittedAfterAdmissionFetchesNothing() async throws {
        let harness = TerminalAfterAdmissionHarness()
        let sut = TokenPagedComposition<Int, String>(fetchNext: harness.fetch)
        try await sut.loadMoreCommand.executeAsync()
        try await sut.loadMoreCommand.executeAsync()
        XCTAssertEqual(sut.items, [1, 101])
        XCTAssertEqual(sut.currentToken, "2")

        let callsBefore = harness.callCount
        harness.lock.withLock { harness.holdNextFirstPage = 1 }
        let refresh = Task.detached { try await sut.refreshCommand.executeAsync() }
        XCTAssertEqual(harness.heldStarted.wait(timeout: .now() + 2), .success)

        sut.collectionChanged.sink { _ in
            harness.lock.withLock { harness.resets += 1 }
            harness.resetSeen.signal()
        }.store(in: &cancellables)
        let armed = ManagedAtomicFlag()
        var resetWait: DispatchTimeoutResult?
        // admit() fires canExecuteChanged after admission and before the body
        // Task starts; the refresh commits its terminal page in that window.
        sut.loadMoreCommand.canExecuteChanged.sink { _ in
            guard armed.takeOnce() else { return }
            harness.takeHeld()?.resume(returning: ([1, 101, 555], nil))
            resetWait = harness.resetSeen.wait(timeout: .now() + 2)
        }.store(in: &cancellables)

        try await Task.detached { try await sut.loadMoreCommand.executeAsync() }.value
        try await refresh.value

        XCTAssertEqual(resetWait, .success)
        XCTAssertEqual(sut.items, [1, 101, 555])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
        XCTAssertEqual(harness.calls(since: callsBefore), [nil])
        XCTAssertEqual(harness.lock.withLock { harness.resets }, 1)
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

    func testRefreshSupersedesAnOlderInFlightLoadMore() async throws {
        let gate = NSLock()
        var call = 0
        var loadContinuation: CheckedContinuation<([Int], String?), Error>?
        var refreshContinuation: CheckedContinuation<([Int], String?), Error>?
        let loadStarted = expectation(description: "loadMore fetch started")
        let refreshStarted = expectation(description: "refresh fetch started")
        let sut = TokenPagedComposition<Int, String>(fetchNext: { _ in
            try await withCheckedThrowingContinuation { continuation in
                gate.lock()
                defer { gate.unlock() }
                if call == 0 {
                    loadContinuation = continuation
                    loadStarted.fulfill()
                } else {
                    refreshContinuation = continuation
                    refreshStarted.fulfill()
                }
                call += 1
            }
        })

        let load = Task { try await sut.loadMoreCommand.executeAsync() }
        await fulfillment(of: [loadStarted], timeout: 2.0)
        let refresh = Task { try await sut.refreshCommand.executeAsync() }
        await fulfillment(of: [refreshStarted], timeout: 2.0)

        refreshContinuation?.resume(returning: ([9], "fresh"))
        try await refresh.value
        XCTAssertEqual(sut.items, [9])

        loadContinuation?.resume(returning: ([1], "stale"))
        try await load.value

        XCTAssertEqual(sut.items, [9])
        XCTAssertEqual(sut.currentToken, "fresh")
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

    func testRefreshComparerReentrantDisposeDoesNotCommitOrDeadlock() async throws {
        var sut: TokenPagedComposition<Int, String>!
        sut = TokenPagedComposition<Int, String>(
            fetchNext: { _ in ([1], "next") },
            pagesEqual: { left, right in
                sut.dispose()
                return left == right
            }
        )

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [])
        XCTAssertNil(sut.currentToken)
        XCTAssertTrue(sut.hasMore)
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

    func testCollectionObserverReentrantDisposeStopsLaterNotifications() async throws {
        let sut = TokenPagedComposition<Int, String>(
            fetchNext: { _ in ([1], nil) }
        )
        var propertyEvents: [String] = []
        sut.collectionChanged.sink { _ in sut.dispose() }.store(in: &cancellables)
        sut.propertyChanged.sink { propertyEvents.append($0) }.store(in: &cancellables)

        try await sut.loadMoreCommand.executeAsync()

        XCTAssertEqual(sut.items, [1])
        XCTAssertEqual(propertyEvents, [])
    }

    /// COL-030 — autoConstructOnAdd constructs component VMs added by a page.
    /// Catalog: the added VMs are constructed BEFORE subscribers observe the
    /// reset, so construction is checked inside the observer.
    func testCOL030AutoConstructsAddedComponentVMs() async throws {
        let first = try ComponentVM.builder().name("first").withNullServices().build()
        let second = try ComponentVM.builder().name("second").withNullServices().build()
        let sut = TokenPagedComposition<ComponentVM, String>(
            fetchNext: { _ in ([first, second], nil) },
            autoConstructOnAdd: true
        )
        var resetsObserved = 0
        var constructedAtReset: [Bool] = []
        sut.collectionChanged.sink { event in
            guard event.action == .reset else { return }
            resetsObserved += 1
            constructedAtReset = [first.isConstructed, second.isConstructed]
        }.store(in: &cancellables)

        try await sut.loadMoreCommand.executeAsync()

        XCTAssertEqual(resetsObserved, 1)
        XCTAssertEqual(constructedAtReset, [true, true],
            "children must be Constructed before subscribers see the Reset")
        XCTAssertTrue(first.isConstructed)
        XCTAssertTrue(second.isConstructed)
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

/// A one-shot flag that is safe to take from any thread.
private final class ManagedAtomicFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var available = true

    func takeOnce() -> Bool {
        lock.withLock {
            defer { available = false }
            return available
        }
    }
}
