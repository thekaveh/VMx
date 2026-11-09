//
// DictionaryKeyViewOrderTests.swift — COL-067 coverage.
//
// Claimed IDs: COL-067.
//
// An `ObservableDictionary` mutation changes the entries and `size`, then each
// key view that changes, then raises the dictionary events and sends the hub
// message. A key view changes only when a distinct key first appears or last
// disappears, so a mutation can change both views, one view, or none. The
// order of two key-view notifications is not checked
// (spec/21-collections.md §4.2, ADR-0177, #1176, #1429).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
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
        extra: [(String, Int, String)] = [],
        changed: [String] = ["keys1", "keys2"],
        expected: Snapshot,
        _ act: (ObservableDictionary<String, Int, String>) throws -> Void
    ) throws {
        let hub = MessageHub()
        let dictionary = ObservableDictionary<String, Int, String>(hub: hub)
        try dictionary.add("a", 1, "one")
        try dictionary.add("b", 2, "two")
        for (key1, key2, value) in extra {
            try dictionary.add(key1, key2, value)
        }
        let start = read(dictionary)
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
        // A view that does not change keeps its start content.
        if !changed.contains("keys1") { XCTAssertEqual(final.keys1, start.keys1, mutation) }
        if !changed.contains("keys2") { XCTAssertEqual(final.keys2, start.keys2, mutation) }
        // Each changed key view notifies first, in an unspecified order; then
        // the dictionary event, then the hub message. An unchanged view stays
        // silent.
        let views = changed.count
        XCTAssertEqual(seen.prefix(views).map(\.channel).sorted(), changed.sorted(), mutation)
        XCTAssertEqual(seen.dropFirst(views).map(\.channel), ["dictionary", "hub"], mutation)
        // A key-view handler sees the updated entries, size and own view.
        for (channel, state) in seen.prefix(views) {
            XCTAssertEqual(state.entries, final.entries, mutation)
            XCTAssertEqual(state.size, final.size, mutation)
            if channel == "keys1" {
                XCTAssertEqual(state.keys1, final.keys1, mutation)
            } else {
                XCTAssertEqual(state.keys2, final.keys2, mutation)
            }
        }
        // The dictionary event and the hub message see both views updated.
        for (_, state) in seen.dropFirst(views) {
            XCTAssertEqual(state, final, mutation)
        }
        cancellables.removeAll()
    }

    /// COL-067 — dictionary events and the hub message follow the key-view
    /// updates on add, set insert, delete and clear, which change both views,
    /// and on mutations that change one key view or none.
    func testCOL067DictionaryEventsAndHubMessageFollowTheKeyViews() throws {
        let added = Snapshot(entries: "a1one,b2two,c3three", size: 3, keys1: "a,b,c", keys2: "1,2,3")
        try check("add", expected: added) { try $0.add("c", 3, "three") }
        try check("set insert", expected: added) { $0.set("c", 3, "three") }
        try check("delete", expected: Snapshot(entries: "b2two", size: 1, keys1: "b", keys2: "2")) {
            XCTAssertTrue($0.delete("a", 1))
        }
        try check("clear", expected: Snapshot(entries: "", size: 0, keys1: "", keys2: "")) {
            $0.clear()
        }
        // Only a new keys2 value appears; "a" is already in keys1.
        try check(
            "add of a new keys2 value only",
            changed: ["keys2"],
            expected: Snapshot(entries: "a1one,b2two,a3three", size: 3, keys1: "a,b", keys2: "1,2,3")
        ) { try $0.add("a", 3, "three") }
        // Only the keys2 value 1 disappears; ("a", 3) keeps "a" in keys1.
        try check(
            "delete of the last keys2 value only",
            extra: [("a", 3, "three")],
            changed: ["keys2"],
            expected: Snapshot(entries: "b2two,a3three", size: 2, keys1: "a,b", keys2: "2,3")
        ) { XCTAssertTrue($0.delete("a", 1)) }
        // Both keys already appear in other entries, so no key view changes.
        try check(
            "add that changes no key view",
            changed: [],
            expected: Snapshot(entries: "a1one,b2two,a2a-two", size: 3, keys1: "a,b", keys2: "1,2")
        ) { try $0.add("a", 2, "a-two") }
    }
}
