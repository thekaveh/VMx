import Combine
import XCTest

@testable import VMx

private func searchMatches(_ item: String, _ term: String) -> Bool {
    term.isEmpty || item.lowercased().contains(term.lowercased())
}

/// Records snapshots and supplier reads from any thread.
private final class SearchEvents {
    private let lock = NSLock()
    private var storedSnapshots: [[String]] = []
    private var storedReads = 0

    var snapshots: [[String]] { lock.withLock { storedSnapshots } }
    var reads: Int { lock.withLock { storedReads } }

    func record(_ snapshot: [String]) { lock.withLock { storedSnapshots.append(snapshot) } }
    func read() { lock.withLock { storedReads += 1 } }
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
        wait(for: [pendingTerm], timeout: hangGuard)
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

    /// SRCH-008 — construction starts no term debounce (ADR-0198).
    func testSRCH008ConstructionStartsNoTermDebounce() {
        let itemsLock = NSLock()
        var items = ["one"]
        let scheduler = DispatchQueue(label: "vmx.search-construction-debounce")
        let sut = SearchableState<String>(
            items: { itemsLock.withLock { items } },
            predicate: searchMatches,
            debounce: .milliseconds(50),
            scheduler: scheduler
        )
        let events = SearchEvents()
        sut.filtered.sink { events.record($0) }.store(in: &cancellables)
        XCTAssertEqual(events.snapshots, [["one"]], "only the replayed value on subscribe")

        itemsLock.withLock { items.append("two") }
        expectNoFurtherValue(from: sut, within: 0.2)
        XCTAssertEqual(events.snapshots.count, 1,
                       "SRCH-008: construction must not start a term debounce")

        sut.search()
        XCTAssertEqual(events.snapshots.count, 2)
        XCTAssertEqual(events.snapshots.last, ["one", "two"])

        let termValue = expectation(description: "one value after the term debounce")
        let termWatch = sut.filtered.dropFirst().first().sink { _ in termValue.fulfill() }
        sut.searchTerm = "o"
        wait(for: [termValue], timeout: 1)
        termWatch.cancel()
        expectNoFurtherValue(from: sut, within: 0.2)
        XCTAssertEqual(events.snapshots.count, 3,
                       "SRCH-008: a new term emits once after its debounce window")
        XCTAssertEqual(events.snapshots.last, ["one", "two"])
        sut.dispose()
    }

    private func expectNoFurtherValue(from sut: SearchableState<String>, within seconds: TimeInterval) {
        let further = expectation(description: "no further filtered value")
        further.isInverted = true
        let watch = sut.filtered.dropFirst().sink { _ in further.fulfill() }
        wait(for: [further], timeout: seconds)
        watch.cancel()
    }

    /// A zero debounce on the main queue reads the supplier once at
    /// construction and sends no later snapshot (#550, ADR-0198).
    func testZeroDebounceConstructionReadsSupplierOnce() {
        let events = SearchEvents()
        let sut = SearchableState<String>(
            items: {
                events.read()
                return ["one"]
            },
            predicate: searchMatches,
            debounce: .milliseconds(0)
        )
        let laterValue = expectation(description: "no filtered value after construction")
        laterValue.isInverted = true
        sut.filtered.dropFirst().sink { _ in laterValue.fulfill() }.store(in: &cancellables)

        wait(for: [laterValue], timeout: 0.2)

        XCTAssertEqual(events.reads, 1, "construction reads the supplier once")
        sut.dispose()
    }
}
