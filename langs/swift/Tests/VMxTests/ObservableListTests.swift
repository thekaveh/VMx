//
// ObservableListTests.swift — conformance tests for ObservableList<T>.
//
// Claimed IDs: COL-005, COL-006, COL-007, COL-008, COL-009, COL-023.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class ObservableListTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // ── COL-005 ──────────────────────────────────────────────────────────────

    /// COL-005 — ObservableList ItemAdded emits (item, index) on append.
    func testCOL005AppendEmitsItemAddedWithCorrectPayload() {
        let sut = ObservableList<String>()
        sut.append("a") // pre-populate so index is predictable

        var received: [ItemAddedEvent<String>] = []
        sut.itemAdded
            .sink { received.append($0) }
            .store(in: &cancellables)

        sut.append("b")

        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received[0].item, "b")
        XCTAssertEqual(received[0].index, 1)
    }

    // ── COL-006 ──────────────────────────────────────────────────────────────

    /// COL-006 — ObservableList ItemRemoved emits (item, indexBeforeRemoval) on removeAt.
    func testCOL006RemoveAtEmitsItemRemovedWithIndexBeforeRemoval() {
        let sut = ObservableList<String>()
        sut.append("x")
        sut.append("y")
        sut.append("z")

        var received: [ItemRemovedEvent<String>] = []
        sut.itemRemoved
            .sink { received.append($0) }
            .store(in: &cancellables)

        sut.removeAt(1) // remove "y" at index 1

        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received[0].item, "y")
        XCTAssertEqual(received[0].index, 1) // index before removal
    }

    // ── COL-007 ──────────────────────────────────────────────────────────────

    /// COL-007 — ObservableList ItemReplaced emits (newItem, oldItem, index) on replace.
    func testCOL007ReplaceEmitsItemReplacedWithCorrectPayload() {
        let sut = ObservableList<String>()
        sut.append("old")
        sut.append("other")

        var received: [ItemReplacedEvent<String>] = []
        sut.itemReplaced
            .sink { received.append($0) }
            .store(in: &cancellables)
        // Replace does not change the count, so it must NOT fire "Count".
        var countChannel: [String] = []
        sut.propertyChanged
            .sink { countChannel.append($0) }
            .store(in: &cancellables)

        sut.replace(at: 0, with: "new")

        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received[0].newItem, "new")
        XCTAssertEqual(received[0].oldItem, "old")
        XCTAssertEqual(received[0].index, 0)
        XCTAssertEqual(countChannel, [], "replace must not emit propertyChanged(\"Count\")")
    }

    // ── COL-008 ──────────────────────────────────────────────────────────────

    /// COL-008 — ItemAdded fires before propertyChanged("Count") on every add.
    func testCOL008GranularEventFiresBeforePropertyChangedCount() {
        let sut = ObservableList<Int>()
        var callOrder: [String] = []

        sut.itemAdded
            .sink { _ in callOrder.append("item_added") }
            .store(in: &cancellables)
        sut.propertyChanged
            .sink { name in callOrder.append("property_changed:\(name)") }
            .store(in: &cancellables)

        sut.append(42)

        XCTAssertEqual(callOrder, ["item_added", "property_changed:Count"])
    }

    // ── COL-009 ──────────────────────────────────────────────────────────────

    /// COL-009 — Inside withBatch only a single reset fires; granular events are suppressed.
    func testCOL009InsideBatchOnlyResetFiresGranularEventsSuppressed() {
        let sut = ObservableList<Int>()

        var granularEvents: [String] = []
        var resets = 0

        sut.itemAdded.sink { _ in granularEvents.append("added") }.store(in: &cancellables)
        sut.itemRemoved.sink { _ in granularEvents.append("removed") }.store(in: &cancellables)
        sut.itemReplaced.sink { _ in granularEvents.append("replaced") }.store(in: &cancellables)
        sut.reset.sink { resets += 1 }.store(in: &cancellables)

        sut.withBatch {
            sut.append(1)
            sut.append(2)
            sut.removeAt(0)
            sut.replace(at: 0, with: 99)
        }

        XCTAssertEqual(granularEvents, [])
        XCTAssertEqual(resets, 1)
    }

    // ── COL-023 ──────────────────────────────────────────────────────────────

    /// COL-023 — Batch with count-changing mutations emits reset then propertyChanged("Count").
    func testCOL023CountChangingBatchEmitsResetThenPropertyChangedCount() {
        let sut = ObservableList<Int>()
        sut.append(10) // pre-populate: count = 1

        var callOrder: [String] = []
        var countAtReset = -1
        var countAtPropertyChanged = -1

        sut.reset
            .sink {
                countAtReset = sut.count
                callOrder.append("reset")
            }
            .store(in: &cancellables)
        sut.propertyChanged
            .sink { name in
                if name == "Count" {
                    countAtPropertyChanged = sut.count
                    callOrder.append("property_changed:Count")
                }
            }
            .store(in: &cancellables)

        // Add two items — count goes from 1 to 3
        sut.withBatch {
            sut.append(20)
            sut.append(30)
        }

        // reset fires before propertyChanged("Count") — ordering is normative
        XCTAssertEqual(callOrder, ["reset", "property_changed:Count"])
        // Count is already updated when both events fire
        XCTAssertEqual(countAtReset, 3)
        XCTAssertEqual(countAtPropertyChanged, 3)
    }

    /// COL-023 — Empty batch emits neither reset nor propertyChanged("Count").
    func testCOL023EmptyBatchEmitsNothing() {
        let sut = ObservableList<Int>()
        sut.append(1)

        var events: [String] = []
        sut.reset.sink { events.append("reset") }.store(in: &cancellables)
        sut.propertyChanged.sink { name in events.append("pc:\(name)") }.store(in: &cancellables)

        sut.withBatch { /* nothing */ }

        XCTAssertEqual(events, [])
    }

    /// Clearing an already-empty list emits neither reset nor
    /// propertyChanged("Count") — ADR-0037 §2.2, mirroring the empty-batch case.
    func testClearOnEmptyListEmitsNothing() {
        let sut = ObservableList<Int>()

        var events: [String] = []
        sut.reset.sink { events.append("reset") }.store(in: &cancellables)
        sut.propertyChanged.sink { name in events.append("pc:\(name)") }.store(in: &cancellables)

        sut.clear()

        XCTAssertEqual(events, [])
    }

    /// COL-023 — Count-preserving batch (replace only) emits reset but NOT propertyChanged("Count").
    func testCOL023CountPreservingBatchEmitsResetButNotCount() {
        let sut = ObservableList<Int>()
        sut.append(1)
        sut.append(2)

        var events: [String] = []
        sut.reset.sink { events.append("reset") }.store(in: &cancellables)
        sut.propertyChanged.sink { name in events.append("pc:\(name)") }.store(in: &cancellables)

        sut.withBatch {
            sut.replace(at: 0, with: 99)
        }

        // reset fires because there was a mutation, but no Count notification
        XCTAssertEqual(events, ["reset"])
    }
}
