//
// DictionaryKeyViewsReadOnlyTests.swift — COL-070 coverage.
//
// Claimed IDs: COL-070.
//
// `ObservableDictionary.keys1` and `keys2` are live, read-only
// `ReadOnlyObservableList` views. They have no mutator and no batch member
// (spec/21-collections.md §4.2, ADR-0193, #1316).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-15).
//
import Combine
import XCTest
@testable import VMx

final class DictionaryKeyViewsReadOnlyTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// COL-070 — the key views are `ReadOnlyObservableList` values that list
    /// the distinct keys in first-appearance order and are not the backing
    /// `ObservableList`. The typed bindings fail to compile on another view
    /// type. Swift cannot check at run time that a member is absent, so the
    /// evidence for "no mutator or batch member" is the declaration of
    /// `ReadOnlyObservableList`.
    func testCOL070KeyViewsAreReadOnlyObservableLists() {
        let sut = ObservableDictionary<String, Int, String>()
        sut.set("a", 1, "x")
        sut.set("b", 2, "y")

        let keys1: ReadOnlyObservableList<String> = sut.keys1
        let keys2: ReadOnlyObservableList<Int> = sut.keys2

        XCTAssertEqual(keys1.toArray(), ["a", "b"])
        XCTAssertEqual(keys2.toArray(), [1, 2])
        XCTAssertEqual(keys1.count, 2)
        XCTAssertEqual(keys1.at(1), "b")
        XCTAssertNil(keys1.at(2))
        XCTAssertFalse((sut.keys1 as AnyObject) is ObservableList<String>)
        XCTAssertFalse((sut.keys2 as AnyObject) is ObservableList<Int>)
        XCTAssertTrue(sut.keys1 === sut.keys1)
    }

    /// The facade forwards each notification of the backing list in order,
    /// with the same payloads.
    func testKeyViewForwardsTheBackingListNotifications() {
        let sut = ObservableDictionary<String, Int, String>()
        var events: [String] = []
        let keys1 = sut.keys1
        keys1.itemAdded.sink { events.append("add:\($0.item):\($0.index)") }
            .store(in: &cancellables)
        keys1.itemRemoved.sink { events.append("remove:\($0.item):\($0.index)") }
            .store(in: &cancellables)
        keys1.reset.sink { events.append("reset") }.store(in: &cancellables)
        keys1.propertyChanged.sink { events.append("prop:\($0)") }
            .store(in: &cancellables)

        sut.set("a", 1, "x")
        sut.set("b", 2, "y")
        sut.delete("a", 1)
        sut.clear()

        XCTAssertEqual(events, [
            "add:a:0", "prop:Count",
            "add:b:1", "prop:Count",
            "remove:a:0", "prop:Count",
            "reset", "prop:Count",
        ])
    }
}
