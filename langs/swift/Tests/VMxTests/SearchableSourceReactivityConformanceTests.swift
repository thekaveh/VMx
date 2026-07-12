import Combine
import XCTest

@testable import VMx

private func searchMatches(_ item: String, _ term: String) -> Bool {
    term.isEmpty || item.lowercased().contains(term.lowercased())
}

private final class OwnedSearchItem {
    let value: String
    private(set) var disposeCount = 0

    init(_ value: String) {
        self.value = value
    }

    func dispose() {
        disposeCount += 1
    }
}

final class SearchableSourceReactivityConformanceTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// SRCH-001 — an unchanged term refreshes from one source signal.
    func testSRCH001SourceSignalRefreshesUnchangedTerm() {
        var items = ["one"]
        let sourceChanges = PassthroughSubject<Void, Never>()
        let sut = SearchableState<String>(
            items: { items },
            predicate: { _, _ in true },
            debounce: .milliseconds(0),
            sourceChanges: sourceChanges.eraseToAnyPublisher()
        )
        var snapshots: [[String]] = []
        sut.filtered.sink { snapshots.append($0) }.store(in: &cancellables)
        let before = snapshots.count

        items.append("two")
        sourceChanges.send(())

        XCTAssertEqual(snapshots.count, before + 1)
        XCTAssertEqual(snapshots.last, ["one", "two"])
        sut.dispose()
    }

    /// SRCH-002 — remove, replace, reset, and reorder read the latest source.
    func testSRCH002MutationsReadLatestOrderedSnapshot() {
        var items = ["a", "b", "c"]
        let sourceChanges = PassthroughSubject<Void, Never>()
        let sut = SearchableState<String>(
            items: { items },
            predicate: { _, _ in true },
            debounce: .milliseconds(0),
            sourceChanges: sourceChanges.eraseToAnyPublisher()
        )
        var snapshots: [[String]] = []
        sut.filtered.sink { snapshots.append($0) }.store(in: &cancellables)

        items.remove(at: 1)
        sourceChanges.send(())
        XCTAssertEqual(snapshots.last, ["a", "c"])

        items[1] = "replacement"
        sourceChanges.send(())
        XCTAssertEqual(snapshots.last, ["a", "replacement"])

        items = ["reset-1", "reset-2", "reset-3"]
        sourceChanges.send(())
        XCTAssertEqual(snapshots.last, ["reset-1", "reset-2", "reset-3"])

        items.reverse()
        sourceChanges.send(())
        XCTAssertEqual(snapshots.last, ["reset-3", "reset-2", "reset-1"])
        sut.dispose()
    }

    /// SRCH-003 — equal pulses and an upstream-coalesced pulse stay transparent.
    func testSRCH003PulsesPreserveEqualityAndUpstreamCoalescing() {
        var items = ["same"]
        let sourceChanges = PassthroughSubject<Void, Never>()
        let sut = SearchableState<String>(
            items: { items },
            predicate: { _, _ in true },
            debounce: .milliseconds(0),
            sourceChanges: sourceChanges.eraseToAnyPublisher()
        )
        var snapshots: [[String]] = []
        sut.filtered.sink { snapshots.append($0) }.store(in: &cancellables)
        let before = snapshots.count

        sourceChanges.send(())
        sourceChanges.send(())
        XCTAssertEqual(snapshots.count, before + 2)

        items.append(contentsOf: ["batched-1", "batched-2"])
        sourceChanges.send(())
        XCTAssertEqual(snapshots.count, before + 3)
        XCTAssertEqual(snapshots.last, ["same", "batched-1", "batched-2"])
        sut.dispose()
    }

    /// SRCH-004 — source refresh does not consume pending debounced term work.
    func testSRCH004SourceRefreshDoesNotCancelPendingTermDebounce() {
        var items = ["alpha", "beta"]
        let sourceChanges = PassthroughSubject<Void, Never>()
        let scheduler = DispatchQueue(label: "vmx.search-source-reactivity")
        let sut = SearchableState<String>(
            items: { items },
            predicate: searchMatches,
            debounce: .milliseconds(100),
            scheduler: scheduler,
            sourceChanges: sourceChanges.eraseToAnyPublisher()
        )
        var snapshots: [[String]] = []
        sut.filtered.sink { snapshots.append($0) }.store(in: &cancellables)

        sut.searchTerm = "alp"
        items.append("alpine")
        let beforeSignal = snapshots.count
        sourceChanges.send(())

        XCTAssertEqual(snapshots.count, beforeSignal + 1)
        XCTAssertEqual(snapshots.last, ["alpha", "alpine"])

        let pendingTerm = expectation(description: "pending term remains eligible")
        sut.filtered
            .dropFirst()
            .sink { snapshot in
                XCTAssertEqual(snapshot, ["alpha", "alpine"])
                pendingTerm.fulfill()
            }
            .store(in: &cancellables)
        wait(for: [pendingTerm], timeout: 1)
        sut.dispose()
    }

    /// SRCH-005 — source completion is isolated from explicit search.
    func testSRCH005SourceCompletionIsIsolatedFromManualSearch() {
        var items = ["one"]
        let sourceChanges = PassthroughSubject<Void, Never>()
        let sut = SearchableState<String>(
            items: { items },
            predicate: { _, _ in true },
            debounce: .milliseconds(0),
            sourceChanges: sourceChanges.eraseToAnyPublisher()
        )
        var snapshots: [[String]] = []
        var filteredCompleted = false
        sut.filtered.sink(
            receiveCompletion: { _ in filteredCompleted = true },
            receiveValue: { snapshots.append($0) }
        ).store(in: &cancellables)

        sourceChanges.send(completion: .finished)
        items.append("two")
        sut.search()

        XCTAssertFalse(filteredCompleted)
        XCTAssertEqual(snapshots.last, ["one", "two"])
        sut.dispose()
    }

    /// SRCH-006 — disposal cancels once and does not own the source signal.
    func testSRCH006DisposeCancelsOnceWithoutOwningSignal() {
        var subscribeCount = 0
        var cancelCount = 0
        let sourceChanges = PassthroughSubject<Void, Never>()
        let tracked = sourceChanges.handleEvents(
            receiveSubscription: { _ in subscribeCount += 1 },
            receiveCancel: { cancelCount += 1 }
        ).eraseToAnyPublisher()
        let sut = SearchableState<String>(
            items: { ["one"] },
            predicate: { _, _ in true },
            debounce: .milliseconds(0),
            sourceChanges: tracked
        )
        var snapshots: [[String]] = []
        sut.filtered.sink { snapshots.append($0) }.store(in: &cancellables)

        sut.dispose()
        sut.dispose()
        sourceChanges.send(())

        XCTAssertEqual(subscribeCount, 1)
        XCTAssertEqual(cancelCount, 1)
        XCTAssertEqual(snapshots.count, 1)

        var independentHits = 0
        sourceChanges.sink { independentHits += 1 }.store(in: &cancellables)
        sourceChanges.send(())
        XCTAssertEqual(independentHits, 1)
    }

    /// SRCH-007 — omitting the signal preserves explicit refresh and ownership.
    func testSRCH007OmittedSignalPreservesExplicitRefreshAndOwnership() {
        let first = OwnedSearchItem("one")
        let second = OwnedSearchItem("two")
        var items = [first]
        let sut = SearchableState<OwnedSearchItem>(
            items: { items },
            predicate: { _, _ in true },
            debounce: .milliseconds(0)
        )
        var snapshots: [[OwnedSearchItem]] = []
        sut.filtered.sink { snapshots.append($0) }.store(in: &cancellables)
        let beforeMutation = snapshots.count

        items.append(second)
        XCTAssertEqual(snapshots.count, beforeMutation)

        sut.search()
        XCTAssertEqual(snapshots.last?.map(\.value), ["one", "two"])
        sut.dispose()

        XCTAssertEqual(first.disposeCount, 0)
        XCTAssertEqual(second.disposeCount, 0)
    }
}
