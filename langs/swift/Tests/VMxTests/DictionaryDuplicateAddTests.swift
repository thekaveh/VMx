//
// DictionaryDuplicateAddTests.swift — COL-071 coverage.
//
// Claimed IDs: COL-071.
//
// `ObservableDictionary.add` of a key pair that is already present throws
// `ObservableDictionaryError.duplicateKey`. The stored value, the entries, the
// key views and `size` do not change, and no local event or hub message is
// sent (spec/21-collections.md §4.1, ADR-0214, #1308).
//
import Combine
import XCTest
@testable import VMx

final class DictionaryDuplicateAddTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// COL-071 — a duplicate `add` throws `duplicateKey` and changes nothing.
    func testCOL071DuplicateAddThrowsDuplicateKeyAndChangesNothing() throws {
        let hub = MessageHub()
        let dictionary = ObservableDictionary<String, Int, String>(hub: hub)
        try dictionary.add("a", 1, "one")
        try dictionary.add("b", 2, "two")
        var events: [String] = []
        hub.messages.sink { _ in events.append("hub") }.store(in: &cancellables)
        dictionary.itemAdded.sink { _ in events.append("added") }.store(in: &cancellables)
        dictionary.itemRemoved.sink { _ in events.append("removed") }.store(in: &cancellables)
        dictionary.itemReplaced.sink { _ in events.append("replaced") }.store(in: &cancellables)
        dictionary.reset.sink { _ in events.append("reset") }.store(in: &cancellables)
        dictionary.keys1.itemAdded.sink { _ in events.append("keys1") }.store(in: &cancellables)
        dictionary.keys1.itemRemoved.sink { _ in events.append("keys1") }.store(in: &cancellables)
        dictionary.keys1.reset.sink { _ in events.append("keys1") }.store(in: &cancellables)
        dictionary.keys2.itemAdded.sink { _ in events.append("keys2") }.store(in: &cancellables)
        dictionary.keys2.itemRemoved.sink { _ in events.append("keys2") }.store(in: &cancellables)
        dictionary.keys2.reset.sink { _ in events.append("keys2") }.store(in: &cancellables)

        XCTAssertThrowsError(try dictionary.add("a", 1, "uno")) { error in
            guard let typed = error as? ObservableDictionaryError,
                  case .duplicateKey(key1: "a", key2: "1") = typed else {
                return XCTFail("expected duplicateKey, got \(error)")
            }
        }

        XCTAssertEqual(dictionary.get("a", 1), "one")
        XCTAssertEqual(dictionary.size, 2)
        XCTAssertEqual(
            dictionary.entries().map { "\($0.key1)\($0.key2)\($0.value)" },
            ["a1one", "b2two"])
        XCTAssertEqual(dictionary.keys1.toArray(), ["a", "b"])
        XCTAssertEqual(dictionary.keys2.toArray(), [1, 2])
        XCTAssertEqual(events, [])
    }
}
