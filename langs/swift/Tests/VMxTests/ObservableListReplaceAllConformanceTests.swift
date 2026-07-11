// ObservableListReplaceAllConformanceTests.swift — COL-040..047.
import Combine
import XCTest
@testable import VMx

private struct NonEquatableItem {}

final class ObservableListReplaceAllConformanceTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func observed(_ items: [Int]) -> (ObservableList<Int>, () -> [String]) {
        let sut = ObservableList<Int>()
        items.forEach(sut.append)
        var events: [String] = []
        sut.itemAdded.sink { _ in events.append("add") }.store(in: &cancellables)
        sut.itemRemoved.sink { _ in events.append("remove") }.store(in: &cancellables)
        sut.itemReplaced.sink { _ in events.append("replace") }.store(in: &cancellables)
        sut.reset.sink { events.append("reset") }.store(in: &cancellables)
        sut.propertyChanged.sink { events.append("property:\($0)") }.store(in: &cancellables)
        return (sut, { events })
    }

    /// COL-040 — growth emits one Reset and Count.
    func testCOL040Growth() {
        let (sut, events) = observed([1])
        sut.replaceAll([2, 3, 4])
        XCTAssertEqual(sut.toArray(), [2, 3, 4])
        XCTAssertEqual(events(), ["reset", "property:Count"])
    }

    /// COL-041 — shrink emits one Reset and Count.
    func testCOL041Shrink() {
        let (sut, events) = observed([1, 2, 3])
        sut.replaceAll([9])
        XCTAssertEqual(events(), ["reset", "property:Count"])
    }

    /// COL-042 — equal count and identical non-empty contents emit Reset without Count.
    func testCOL042EqualCountAndIdentical() {
        let (sut, events) = observed([1, 2])
        sut.replaceAll([3, 4])
        sut.replaceAll([3, 4])
        XCTAssertEqual(events(), ["reset", "reset"])

        let unconstrained = ObservableList<NonEquatableItem>()
        let item = NonEquatableItem()
        unconstrained.append(item)
        unconstrained.replaceAll([item])
    }

    /// COL-043 — empty-to-empty is silent; non-empty-to-empty is effective.
    func testCOL043EmptyCases() {
        let (empty, emptyEvents) = observed([])
        empty.replaceAll([Int]())
        XCTAssertEqual(emptyEvents(), [])
        let (sut, events) = observed([1])
        sut.replaceAll([Int]())
        XCTAssertEqual(events(), ["reset", "property:Count"])
    }

    /// COL-044 — input is materialized before the backing array mutates.
    func testCOL044SnapshotInput() {
        let (sut, events) = observed([1, 2, 3])
        sut.replaceAll(AnySequence { sut.toArray().makeIterator() })
        XCTAssertEqual(sut.toArray(), [1, 2, 3])
        XCTAssertEqual(events(), ["reset"])
    }

    /// COL-045 — nested replacement emits only the outermost Reset.
    func testCOL045NestedBatch() {
        let (sut, events) = observed([1])
        sut.withBatch {
            sut.replaceAll([2, 3])
            XCTAssertEqual(events(), [])
        }
        XCTAssertEqual(events(), ["reset", "property:Count"])
    }

    /// COL-046 — throwing batch exit restores depth and publishes the mutation.
    func testCOL046ExceptionalBatchExit() {
        enum Failure: Error { case boom }
        let (sut, events) = observed([1])
        XCTAssertThrowsError(try sut.withBatch {
            sut.replaceAll([2, 3])
            throw Failure.boom
        })
        XCTAssertEqual(events(), ["reset", "property:Count"])
        sut.replaceAll([4, 5])
        XCTAssertEqual(events(), ["reset", "property:Count", "reset"])
    }

    /// COL-047 — Reset precedes Count and both observe final state.
    func testCOL047OrderingAndFinalState() {
        let sut = ObservableList<Int>()
        sut.append(1)
        var observations: [String] = []
        sut.reset.sink { observations.append("reset:\(sut.toArray())") }.store(in: &cancellables)
        sut.propertyChanged.sink {
            observations.append("\($0):\(sut.toArray())")
        }.store(in: &cancellables)
        sut.replaceAll([7, 8])
        XCTAssertEqual(observations, ["reset:[7, 8]", "Count:[7, 8]"])
    }
}
