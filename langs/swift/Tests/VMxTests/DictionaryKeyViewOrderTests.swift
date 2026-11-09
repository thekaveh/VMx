//
// DictionaryKeyViewOrderTests.swift — COL-067 coverage.
//
// Claimed IDs: COL-067.
//
// An `ObservableDictionary` mutation changes the entries and `size`, then both
// key views, then raises the dictionary events and sends the hub message. The
// order of the two key-view notifications is not checked
// (spec/21-collections.md §4.2, ADR-0177, #1176).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-15).
//
import Combine
import XCTest
@testable import VMx

final class DictionaryKeyViewOrderTests: XCTestCase {

    private struct Snapshot: Equatable {
        let entries: String
        let size: Int
        let keys1: String
        let keys2: String
    }

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func read(_ dictionary: ObservableDictionary<String, Int, String>) -> Snapshot {
        Snapshot(
            entries: dictionary.entries().map { "\($0.key1)\($0.key2)\($0.value)" }
                .joined(separator: ","),
            size: dictionary.size,
            keys1: dictionary.keys1.toArray().joined(separator: ","),
            keys2: dictionary.keys2.toArray().map(String.init).joined(separator: ","))
    }

    private func check(
        _ mutation: String,
        expected: Snapshot,
        _ act: (ObservableDictionary<String, Int, String>) throws -> Void
    ) throws {
        let hub = MessageHub()
        let dictionary = ObservableDictionary<String, Int, String>(hub: hub)
        try dictionary.add("a", 1, "one")
        try dictionary.add("b", 2, "two")
        var seen: [(channel: String, state: Snapshot)] = []
        let record: (String) -> Void = { channel in
            seen.append((channel, self.read(dictionary)))
        }
        hub.messages.sink { _ in record("hub") }.store(in: &cancellables)
        dictionary.itemAdded.sink { _ in record("dictionary") }.store(in: &cancellables)
        dictionary.itemRemoved.sink { _ in record("dictionary") }.store(in: &cancellables)
        dictionary.reset.sink { _ in record("dictionary") }.store(in: &cancellables)
        dictionary.keys1.itemAdded.sink { _ in record("keys1") }.store(in: &cancellables)
        dictionary.keys1.itemRemoved.sink { _ in record("keys1") }.store(in: &cancellables)
        dictionary.keys1.reset.sink { _ in record("keys1") }.store(in: &cancellables)
        dictionary.keys2.itemAdded.sink { _ in record("keys2") }.store(in: &cancellables)
        dictionary.keys2.itemRemoved.sink { _ in record("keys2") }.store(in: &cancellables)
        dictionary.keys2.reset.sink { _ in record("keys2") }.store(in: &cancellables)

        try act(dictionary)

        let final = read(dictionary)
        XCTAssertEqual(final, expected, mutation)
        // Both key views notify first, in an unspecified order; then the
        // dictionary event, then the hub message.
        XCTAssertEqual(seen.prefix(2).map(\.channel).sorted(), ["keys1", "keys2"], mutation)
        XCTAssertEqual(seen.dropFirst(2).map(\.channel), ["dictionary", "hub"], mutation)
        // A key-view handler sees the updated entries, size and own view.
        for (channel, state) in seen.prefix(2) {
            XCTAssertEqual(state.entries, final.entries, mutation)
            XCTAssertEqual(state.size, final.size, mutation)
            if channel == "keys1" {
                XCTAssertEqual(state.keys1, final.keys1, mutation)
            } else {
                XCTAssertEqual(state.keys2, final.keys2, mutation)
            }
        }
        // The dictionary event and the hub message see both views updated.
        for (_, state) in seen.dropFirst(2) {
            XCTAssertEqual(state, final, mutation)
        }
        cancellables.removeAll()
    }

    /// COL-067 — dictionary events and the hub message follow both key-view
    /// updates on add, set insert, delete and clear.
    func testCOL067DictionaryEventsAndHubMessageFollowBothKeyViews() throws {
        let added = Snapshot(entries: "a1one,b2two,c3three", size: 3, keys1: "a,b,c", keys2: "1,2,3")
        try check("add", expected: added) { try $0.add("c", 3, "three") }
        try check("set insert", expected: added) { $0.set("c", 3, "three") }
        try check("delete", expected: Snapshot(entries: "b2two", size: 1, keys1: "b", keys2: "2")) {
            XCTAssertTrue($0.delete("a", 1))
        }
        try check("clear", expected: Snapshot(entries: "", size: 0, keys1: "", keys2: "")) {
            $0.clear()
        }
    }
}
