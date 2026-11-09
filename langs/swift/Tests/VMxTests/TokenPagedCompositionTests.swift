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
        await fulfillment(of: [fetchStarted], timeout: hangGuard)
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
    /// ADR-0169). Pages [1] and [101] load; then first-page fetches can be held.
    private final class TerminalAfterAdmissionHarness: @unchecked Sendable {
        let lock = NSLock()
        private var calls: [String?] = []
        private var holdFirstPages = 0
        private var held: [CheckedContinuation<([Int], String?), Error>] = []
        private var onHeld: [() -> Void] = []

        /// Holds the next first-page fetch and runs `started` once it is held.
        func holdNextFirstPage(_ started: @escaping () -> Void) {
            lock.withLock {
                holdFirstPages += 1
                onHeld.append(started)
            }
        }

        func fetch(_ token: String?) async throws -> ([Int], String?) {
            let hold = lock.withLock { () -> Bool in
                calls.append(token)
                guard token == nil, holdFirstPages > 0 else { return false }
                holdFirstPages -= 1
                return true
            }
            if hold {
                return try await withCheckedThrowingContinuation { continuation in
                    let started = lock.withLock { () -> () -> Void in
                        held.append(continuation)
                        return onHeld.removeFirst()
                    }
                    started()
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

    /// Polls `condition` until it holds or `hangGuard` elapses, without
    /// blocking a Swift concurrency thread.
    private func eventually(_ condition: () -> Bool) async -> Bool {
        let deadline = Date().addingTimeInterval(hangGuard)
        while !condition() {
            if Date() >= deadline { return false }
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
        return true
    }

    /// COL-026 / #1161 — after loadMore is admitted and before its body starts,
    /// a refresh commits a terminal page and a later refresh starts and holds
    /// its fetch. The gated-out load fetches nothing and supersedes nothing
    /// (spec 21 §6.2, ADR-0169), so the later refresh still commits its page.
    /// Before the fix the load refetched page 1, appended it and superseded
    /// the later refresh.
    ///
    /// `execute()` admits on the calling thread and fires `canExecuteChanged`
    /// there before the body task starts. A GCD thread calls it, so the
    /// admission window blocks that thread and never a Swift concurrency
    /// thread; the refreshes run on the cooperative pool meanwhile.
    func testCOL026GatedOutLoadFetchesNothingAndDoesNotSupersedeALaterRefresh() async throws {
        let harness = TerminalAfterAdmissionHarness()
        let sut = TokenPagedComposition<Int, String>(fetchNext: harness.fetch)
        try await sut.loadMoreCommand.executeAsync()
        try await sut.loadMoreCommand.executeAsync()
        XCTAssertEqual(sut.items, [1, 101])
        XCTAssertEqual(sut.currentToken, "2")

        let callsBefore = harness.callCount
        let terminalHeld = expectation(description: "the terminal refresh fetch is held")
        harness.holdNextFirstPage { terminalHeld.fulfill() }
        sut.refreshCommand.execute()
        await fulfillment(of: [terminalHeld], timeout: hangGuard)

        let resets = SharedCounter()
        sut.collectionChanged.sink { _ in resets.increment() }.store(in: &cancellables)

        let window = WindowResults()
        var admission: AnyCancellable?
        admission = sut.loadMoreCommand.canExecuteChanged.sink { _ in
            // Runs on the admitting GCD thread. Leave the subject first, so
            // the refreshes' own notifications never wait for this window.
            admission?.cancel()
            harness.takeHeld()?.resume(returning: ([1, 101, 555], nil))
            window.terminalCommitted = Self.poll {
                !sut.refreshCommand.isExecuting && !sut.hasMore
            }
            let laterHeld = DispatchSemaphore(value: 0)
            harness.holdNextFirstPage { laterHeld.signal() }
            sut.refreshCommand.execute()
            window.laterRefreshHeld = laterHeld.wait(timeout: .now() + hangGuard)
        }
        defer { admission?.cancel() }

        let admitted = expectation(description: "loadMore was admitted")
        let boxedSut = UncheckedSendableBox(sut)
        DispatchQueue.global().async {
            boxedSut.value.loadMoreCommand.execute()
            admitted.fulfill()
        }
        await fulfillment(of: [admitted], timeout: hangGuard)
        XCTAssertEqual(window.terminalCommitted, true, "the terminal refresh did not commit")
        XCTAssertEqual(window.laterRefreshHeld, .success, "the later refresh did not start")
        let loadFinished = await eventually { !sut.loadMoreCommand.isExecuting }
        XCTAssertTrue(loadFinished, "the gated-out load did not finish")

        XCTAssertEqual(sut.items, [1, 101, 555])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
        XCTAssertEqual(
            harness.calls(since: callsBefore), [nil, nil],
            "only the two refreshes fetch; the gated-out load fetches nothing"
        )
        XCTAssertEqual(resets.value, 1, "only the terminal refresh has published a Reset")

        harness.takeHeld()?.resume(returning: ([7], "x"))
        let laterCommitted = await eventually {
            resets.value == 2 && !sut.refreshCommand.isExecuting
        }
        XCTAssertTrue(laterCommitted, "the later refresh did not commit")
        XCTAssertEqual(sut.items, [7])
        XCTAssertEqual(sut.currentToken, "x")
        XCTAssertTrue(sut.hasMore)
    }

    /// Polls `condition` on a non-concurrency thread until it holds or
    /// `hangGuard` elapses.
    private static func poll(_ condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(hangGuard)
        while !condition() {
            if Date() >= deadline { return false }
            Thread.sleep(forTimeInterval: 0.001)
        }
        return true
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
        await fulfillment(of: [loadStarted], timeout: hangGuard)
        let refresh = Task { try await sut.refreshCommand.executeAsync() }
        await fulfillment(of: [refreshStarted], timeout: hangGuard)

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
        await fulfillment(of: [fetchStarted], timeout: hangGuard)
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

/// A counter that is safe to update from any thread.
private final class SharedCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    var value: Int { lock.withLock { count } }
    func increment() { lock.withLock { count += 1 } }
}

/// What the admission window observed, read after the admitting thread
/// returns.
private final class WindowResults: @unchecked Sendable {
    private let lock = NSLock()
    private var _terminalCommitted: Bool?
    private var _laterRefreshHeld: DispatchTimeoutResult?

    var terminalCommitted: Bool? {
        get { lock.withLock { _terminalCommitted } }
        set { lock.withLock { _terminalCommitted = newValue } }
    }

    var laterRefreshHeld: DispatchTimeoutResult? {
        get { lock.withLock { _laterRefreshHeld } }
        set { lock.withLock { _laterRefreshHeld = newValue } }
    }
}
