//
// TokenPagingNotificationStepTests.swift — COL-073 structural and ordering coverage.
//
// Claimed IDs: COL-073.
//
// COL-073 requires that a failing subscriber of a token-paging notification step
// skips no later step of the committed load or refresh (spec/21-collections.md
// §6.2, ADR-0239, extends ADR-0220). In Swift a subscriber cannot fail: every
// `TokenPagedComposition` publisher has the failure type `Never`, and a Combine
// `sink` closure cannot throw. These tests pin that structure, check that each
// load or refresh runs every later step once and in order, and check that a
// subscriber that disposes the composition stops the later steps.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-15).
//
import XCTest
import Combine
@testable import VMx

final class TokenPagingNotificationStepTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func failureType<P: Publisher>(of _: P) -> Any.Type { P.Failure.self }

    /// A first page that a test can change between calls; later pages are terminal.
    private final class FirstPage: @unchecked Sendable {
        private let lock = NSLock()
        private var _page: ([Int], String?)

        init(_ page: ([Int], String?)) { _page = page }

        var page: ([Int], String?) {
            get { lock.withLock { _page } }
            set { lock.withLock { _page = newValue } }
        }
    }

    /// Records the notifications of one composition in the order they arrive.
    private final class Trace: @unchecked Sendable {
        private let lock = NSLock()
        private var _entries: [String] = []

        var entries: [String] { lock.withLock { _entries } }

        func append(_ entry: String) { lock.withLock { _entries.append(entry) } }
    }

    private func pager(_ firstPage: FirstPage) -> TokenPagedComposition<Int, String> {
        TokenPagedComposition<Int, String>(
            fetchNext: { token in token == nil ? firstPage.page : ([3], nil) },
            pagesEqual: { $0 == $1 }
        )
    }

    /// Observes the collection, property and one command's eligibility signals. A
    /// command raises its own canExecuteChanged when it starts and finishes, so the
    /// trace observes the command that the test does not execute.
    private func record(_ sut: TokenPagedComposition<Int, String>, observingRefresh: Bool) -> Trace {
        let trace = Trace()
        sut.collectionChanged
            .sink { event in trace.append(event.action == .reset ? "collection:reset" : "collection:other") }
            .store(in: &cancellables)
        sut.propertyChanged
            .sink { trace.append("property:\($0)") }
            .store(in: &cancellables)
        if observingRefresh {
            sut.refreshCommand.canExecuteChanged
                .sink { trace.append("command:canExecuteChanged") }
                .store(in: &cancellables)
        } else {
            sut.loadMoreCommand.canExecuteChanged
                .sink { trace.append("command:canExecuteChanged") }
                .store(in: &cancellables)
        }
        return trace
    }

    /// COL-073 — structural: no token-paging publisher can fail, so no notification
    /// step can be skipped by a failing subscriber.
    func testCOL073TokenPagingPublishersCannotFail() {
        let sut = pager(FirstPage(([1, 2], nil)))

        XCTAssertTrue(failureType(of: sut.collectionChanged) == Never.self)
        XCTAssertTrue(failureType(of: sut.propertyChanged) == Never.self)
        XCTAssertTrue(failureType(of: sut.loadMoreCommand.canExecuteChanged) == Never.self)
        XCTAssertTrue(failureType(of: sut.refreshCommand.canExecuteChanged) == Never.self)
    }

    /// COL-073 — an appending load runs the Reset event, the three property
    /// notifications and the command re-signal once each, in that order.
    func testCOL073AppendingLoadRunsEveryStepOnceInOrder() async throws {
        let sut = pager(FirstPage(([1, 2], nil)))
        let trace = record(sut, observingRefresh: true)

        try await sut.loadMoreCommand.executeAsync()

        XCTAssertEqual(sut.items, [1, 2])
        XCTAssertFalse(sut.hasMore)
        XCTAssertEqual(
            trace.entries,
            [
                "collection:reset",
                "property:items",
                "property:currentToken",
                "property:hasMore",
                "command:canExecuteChanged",
            ]
        )
    }

    /// COL-073 — a replacing refresh runs the same steps once each, in the same order.
    func testCOL073ReplacingRefreshRunsEveryStepOnceInOrder() async throws {
        let firstPage = FirstPage(([1, 2], "t2"))
        let sut = pager(firstPage)
        try await sut.loadMoreCommand.executeAsync()
        firstPage.page = ([9], nil)
        let trace = record(sut, observingRefresh: false)

        try await sut.refreshCommand.executeAsync()

        XCTAssertEqual(sut.items, [9])
        XCTAssertNil(sut.currentToken)
        XCTAssertFalse(sut.hasMore)
        XCTAssertEqual(
            trace.entries,
            [
                "collection:reset",
                "property:items",
                "property:currentToken",
                "property:hasMore",
                "command:canExecuteChanged",
            ]
        )
    }

    /// COL-073 — a Reset subscriber that disposes the composition stops the later
    /// property and command steps.
    func testCOL073DisposingResetSubscriberStopsTheLaterSteps() async throws {
        let sut = pager(FirstPage(([1, 2], nil)))
        let trace = Trace()
        sut.collectionChanged
            .sink { _ in sut.dispose() }
            .store(in: &cancellables)
        sut.propertyChanged
            .sink { trace.append("property:\($0)") }
            .store(in: &cancellables)
        sut.refreshCommand.canExecuteChanged
            .sink { trace.append("command:canExecuteChanged") }
            .store(in: &cancellables)

        try await sut.loadMoreCommand.executeAsync()

        XCTAssertEqual(trace.entries, [])
    }
}
