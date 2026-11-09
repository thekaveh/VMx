//
// DictionaryRemoveReplacePositionsTests.swift — COL-068 coverage.
//
// Claimed IDs: COL-068.
//
// `ObservableDictionary` Remove and Replace hub messages carry the entry's
// position in enumeration order at commit (spec/21-collections.md §4.7,
// ADR-0193, #1316).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import Combine
import XCTest
@testable import VMx

final class DictionaryRemoveReplacePositionsTests: XCTestCase {

    private typealias Message = CollectionChangedMessage<DictionaryEntry<String, Int, String>>

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func record(_ hub: MessageHub) -> () -> [Message] {
        var messages: [Message] = []
        hub.messages
            .compactMap { $0 as? Message }
            .sink { messages.append($0) }
            .store(in: &cancellables)
        return { messages }
    }

    /// COL-068 — Replace sets `index`, `oldIndex` and `newIndex` to the
    /// entry's position; Remove sets `index` and `oldIndex` to the position
    /// before the removal and `newIndex` to -1.
    func testCOL068RemoveAndReplaceCarryTheEntryPosition() {
        let hub = MessageHub()
        let sut = ObservableDictionary<String, Int, String>(hub: hub)
        sut.set("a", 1, "x")
        sut.set("b", 2, "y")
        sut.set("c", 3, "w")
        let messages = record(hub)

        sut.set("c", 3, "z")
        XCTAssertTrue(sut.delete("b", 2))

        let recorded = messages()
        XCTAssertEqual(recorded.map(\.action), [.replace, .remove])
        guard recorded.count == 2 else { return }
        XCTAssertEqual(recorded[0].index, 2)
        XCTAssertEqual(recorded[0].oldIndex, 2)
        XCTAssertEqual(recorded[0].newIndex, 2)
        XCTAssertEqual(recorded[1].index, 1)
        XCTAssertEqual(recorded[1].oldIndex, 1)
        XCTAssertEqual(recorded[1].newIndex, -1)
    }

    /// The Replace position is captured at commit. A local `itemReplaced`
    /// subscriber that removes an earlier entry does not change it.
    func testReplacePositionIsCapturedBeforeLocalSubscribersRun() {
        let hub = MessageHub()
        let sut = ObservableDictionary<String, Int, String>(hub: hub)
        sut.set("a", 1, "x")
        sut.set("b", 2, "y")
        sut.set("c", 3, "w")
        sut.itemReplaced
            .sink { _ in sut.delete("a", 1) }
            .store(in: &cancellables)
        let messages = record(hub)

        sut.set("c", 3, "z")

        let replace = messages().first { $0.action == .replace }
        XCTAssertEqual(replace?.index, 2)
        XCTAssertEqual(replace?.oldIndex, 2)
        XCTAssertEqual(replace?.newIndex, 2)
    }

    /// The Remove position is captured at commit. A local `itemRemoved`
    /// subscriber that removes an earlier entry does not change it.
    func testRemovePositionIsCapturedBeforeLocalSubscribersRun() {
        let hub = MessageHub()
        let sut = ObservableDictionary<String, Int, String>(hub: hub)
        sut.set("a", 1, "x")
        sut.set("b", 2, "y")
        sut.set("c", 3, "w")
        var nested = false
        sut.itemRemoved
            .sink { event in
                guard event.key1 == "c", !nested else { return }
                nested = true
                sut.delete("a", 1)
            }
            .store(in: &cancellables)
        let messages = record(hub)

        sut.delete("c", 3)

        let removeC = messages().first { $0.oldItems.first?.key1 == "c" }
        XCTAssertEqual(removeC?.index, 2)
        XCTAssertEqual(removeC?.oldIndex, 2)
        XCTAssertEqual(removeC?.newIndex, -1)
    }
}
