//
// ObservableDictionaryTests.swift — conformance tests for ObservableDictionary.
//
// Claimed IDs: COL-010, COL-011, COL-012, COL-013, COL-014, COL-015, COL-022.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class ObservableDictionaryTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// COL-022 — the hub add index is captured before a reentrant add.
    func testCOL022HubAddIndexIsCapturedBeforeAReentrantAdd() {
        let hub = MessageHub()
        let sut = ObservableDictionary<String, String, Int>(hub: hub)
        var indices: [String: Int] = [:]
        hub.messages
            .compactMap { $0 as? CollectionChangedMessage<DictionaryEntry<String, String, Int>> }
            .sink { message in
                for item in message.newItems { indices[item.key1] = message.index }
            }
            .store(in: &cancellables)
        sut.itemAdded
            .sink { event in
                if event.key1 == "a" { sut.set("b", "y", 2) }
            }
            .store(in: &cancellables)

        sut.set("a", "x", 1)

        XCTAssertEqual(indices, ["a": 0, "b": 1])
    }

    // #733: key-view subscribers run before the hub publication.
    private func hubAddIndices(_ hub: MessageHub) -> () -> [(Int, Int)] {
        var adds: [(Int, Int)] = []
        hub.messages
            .compactMap { $0 as? CollectionChangedMessage<DictionaryEntry<String, String, Int>> }
            .filter { $0.action == .add }
            .sink { message in
                for item in message.newItems { adds.append((item.value, message.index)) }
            }
            .store(in: &cancellables)
        return { adds }
    }

    func testHubAddIndexIsCapturedBeforeAKeyViewReentrantAdd() {
        for view in ["keys1", "keys2"] {
            let hub = MessageHub()
            let sut = ObservableDictionary<String, String, Int>(hub: hub)
            let adds = hubAddIndices(hub)
            var nested = false
            let keyAdded = view == "keys1"
                ? sut.keys1.itemAdded.map { _ in () }.eraseToAnyPublisher()
                : sut.keys2.itemAdded.map { _ in () }.eraseToAnyPublisher()
            keyAdded.sink {
                guard !nested else { return }
                nested = true
                sut.set("z", "z", 1)
            }.store(in: &cancellables)

            sut.set("a", "a", 0)

            XCTAssertEqual(adds().map { $0.0 }, [1, 0], view)
            XCTAssertEqual(adds().map { $0.1 }, [1, 0], view)
        }
    }

    func testHubAddIndexFollowsAKeyViewReentrantDeleteOrClear() {
        for (nested, expected) in [("delete", 0), ("clear", -1)] {
            let hub = MessageHub()
            let sut = ObservableDictionary<String, String, Int>(hub: hub)
            sut.set("x", "x", 9)
            let adds = hubAddIndices(hub)
            var done = false
            sut.keys1.itemAdded.sink { _ in
                guard !done else { return }
                done = true
                if nested == "delete" { _ = sut.delete("x", "x") } else { sut.clear() }
            }.store(in: &cancellables)

            sut.set("a", "a", 0)

            XCTAssertEqual(adds().count, 1, nested)
            XCTAssertEqual(adds().first?.1, expected, nested)
        }
    }

    // #772: an entry added from a key-view subscriber keeps both views in
    // first-appearance order.
    func testKeyViewsKeepFirstAppearanceOrderAfterAKeyViewReentrantAdd() {
        for view in ["keys1", "keys2"] {
            let sut = ObservableDictionary<String, Int, String>()
            var nested = false
            let keyAdded = view == "keys1"
                ? sut.keys1.itemAdded.map { _ in () }.eraseToAnyPublisher()
                : sut.keys2.itemAdded.map { _ in () }.eraseToAnyPublisher()
            keyAdded.sink {
                guard !nested else { return }
                nested = true
                sut.set("b", 2, "nested")
            }.store(in: &cancellables)

            sut.set("a", 1, "outer")

            XCTAssertEqual(sut.keys1.toArray(), ["a", "b"], view)
            XCTAssertEqual(sut.keys2.toArray(), [1, 2], view)
        }
    }

    func testKeys2ListsTheNewKey2BeforeKeys1Notifies() {
        let sut = ObservableDictionary<String, Int, String>()
        var seen: [[Int]] = []
        sut.keys1.itemAdded.sink { _ in seen.append(sut.keys2.toArray()) }
            .store(in: &cancellables)

        sut.set("a", 1, "outer")

        XCTAssertEqual(seen, [[1]])
    }

    /// Runs `nested` once, from the keys2 handler for key2 1, then sets (a, 1).
    private func addFromAKeys2Handler(
        _ sut: ObservableDictionary<String, Int, String>, _ nested: @escaping () -> Void
    ) {
        var done = false
        sut.keys2.itemAdded.sink { event in
            guard !done, event.item == 1 else { return }
            done = true
            nested()
        }.store(in: &cancellables)
        sut.set("a", 1, "outer")
    }

    func testKeyViewsStayEmptyWhenAKeys2HandlerRemovesTheNewEntry() {
        let sut = ObservableDictionary<String, Int, String>()

        addFromAKeys2Handler(sut) { _ = sut.delete("a", 1) }

        XCTAssertEqual(sut.size, 0)
        XCTAssertEqual(sut.keys1.toArray(), [])
        XCTAssertEqual(sut.keys2.toArray(), [])
    }

    func testKeys1ListsAPendingKey1BeforeAKeyThatAKeys2HandlerAdds() {
        let sut = ObservableDictionary<String, Int, String>()
        sut.set("x", 0, "first")

        addFromAKeys2Handler(sut) {
            sut.set("c", 5, "nested")
            sut.set("a", 3, "nested")
        }

        XCTAssertEqual(sut.keys1.toArray(), ["x", "a", "c"])
        XCTAssertEqual(sut.keys2.toArray(), [0, 1, 5, 3])
    }

    func testKeys1KeepsItsOrderWhenAKeys2HandlerMovesAKey1Later() {
        let sut = ObservableDictionary<String, Int, String>()
        sut.set("x", 0, "first")
        sut.set("y", 2, "second")

        addFromAKeys2Handler(sut) {
            sut.set("x", 4, "nested")
            _ = sut.delete("x", 0)
        }

        XCTAssertEqual(sut.keys1.toArray(), ["x", "y", "a"])
        XCTAssertEqual(sut.keys2.toArray(), [2, 1, 4])
    }

    // #1075: an entry added from a key-view reset handler during clear keeps
    // both views equal to the keys of the remaining entries.
    func testKeyViewsMatchTheEntriesAfterAKeyViewResetHandlerAddsDuringClear() {
        for view in ["keys1", "keys2"] {
            let sut = ObservableDictionary<String, String, String>()
            sut.set("a", "a", "outer")
            var done = false
            let reset = view == "keys1" ? sut.keys1.reset : sut.keys2.reset
            reset.sink {
                guard !done else { return }
                done = true
                sut.set("b", "b", "nested")
            }.store(in: &cancellables)

            sut.clear()

            XCTAssertEqual(sut.entries().map { "\($0.key1)\($0.key2)" }, ["bb"], view)
            XCTAssertEqual(sut.keys1.toArray(), ["b"], view)
            XCTAssertEqual(sut.keys2.toArray(), ["b"], view)

            sut.delete("b", "b")

            XCTAssertEqual(sut.size, 0, view)
            XCTAssertEqual(sut.keys1.toArray(), [], view)
            XCTAssertEqual(sut.keys2.toArray(), [], view)
        }
    }

    // #1075: an entry added or removed from a key-view itemRemoved handler
    // during delete keeps both views equal to the distinct keys of the entries.
    // keys1 never lists a key twice, also while a subscriber runs.
    func testKeyViewsMatchTheEntriesAfterAKeyViewHandlerChangesThemDuringDelete() {
        let cases: [(view: String, nested: String, keys1: [String], keys2: [String])] = [
            ("keys1", "add", ["b", "c", "a"], ["y", "z", "x"]),
            ("keys1", "delete", ["c"], ["z"]),
            ("keys2", "add", ["b", "c", "a"], ["y", "z", "x"]),
            ("keys2", "delete", ["c"], ["z"]),
        ]
        for (view, nested, keys1, keys2) in cases {
            let label = "\(view) \(nested)"
            let sut = ObservableDictionary<String, String, String>()
            sut.set("a", "x", "outer")
            sut.set("b", "y", "kept")
            sut.set("c", "z", "kept")
            var done = false
            let itemRemoved = view == "keys1"
                ? sut.keys1.itemRemoved.map { _ in () }.eraseToAnyPublisher()
                : sut.keys2.itemRemoved.map { _ in () }.eraseToAnyPublisher()
            itemRemoved.sink {
                guard !done else { return }
                done = true
                if nested == "add" { sut.set("a", "x", "nested") } else { sut.delete("b", "y") }
            }.store(in: &cancellables)
            var snapshots: [[String]] = []
            sut.keys1.itemAdded.sink { _ in snapshots.append(sut.keys1.toArray()) }
                .store(in: &cancellables)

            sut.delete("a", "x")

            var seen1 = Set<String>()
            var seen2 = Set<String>()
            let entries = sut.entries()
            XCTAssertEqual(entries.map(\.key1).filter { seen1.insert($0).inserted }, keys1, label)
            XCTAssertEqual(entries.map(\.key2).filter { seen2.insert($0).inserted }, keys2, label)
            XCTAssertEqual(sut.keys1.toArray(), keys1, label)
            XCTAssertEqual(sut.keys2.toArray(), keys2, label)
            XCTAssertTrue(snapshots.allSatisfy { Set($0).count == $0.count }, label)
        }
    }

    // #1075: delete and clear update keys2 first, as an add does, so a keys1
    // subscriber already reads the updated keys2.
    func testKeys2IsUpdatedWhenKeys1NotifiesADeleteOrAClear() {
        let sut = ObservableDictionary<String, String, String>()
        sut.set("a", "a", "first")
        sut.set("b", "b", "second")
        var seen: [[String]] = []
        sut.keys1.itemRemoved.sink { _ in seen.append(sut.keys2.toArray()) }
            .store(in: &cancellables)
        sut.keys1.reset.sink { seen.append(sut.keys2.toArray()) }
            .store(in: &cancellables)

        sut.delete("a", "a")
        sut.clear()

        XCTAssertEqual(seen, [["b"], []])
    }

    func testHubAddIndexFollowsTheKeyPairAfterANestedClearAndReAdd() {
        let hub = MessageHub()
        let sut = ObservableDictionary<String, String, Int>(hub: hub)
        let adds = hubAddIndices(hub)
        var done = false
        sut.keys1.itemAdded.sink { _ in
            guard !done else { return }
            done = true
            sut.clear()
            sut.set("a", "a", 7)
        }.store(in: &cancellables)

        sut.set("a", "a", 0)

        XCTAssertEqual(adds().map { $0.0 }, [7, 0])
        XCTAssertEqual(adds().map { $0.1 }, [0, 0])
    }

    // ── COL-010 ──────────────────────────────────────────────────────────────

    /// COL-010 — ObservableDictionary insert sets has() and get() returns value.
    func testCOL010InsertSetsHasAndGetReturnsValue() {
        let sut = ObservableDictionary<String, Int, Double>()
        var added: [DictionaryItemAddedEvent<String, Int, Double>] = []
        sut.itemAdded.sink { added.append($0) }.store(in: &cancellables)

        sut.set("alpha", 1, 3.14)

        // has() is true after insert
        XCTAssertTrue(sut.has("alpha", 1))

        // get() returns the correct value
        XCTAssertEqual(sut.get("alpha", 1) ?? .nan, 3.14, accuracy: 1e-9)

        // size incremented
        XCTAssertEqual(sut.size, 1)

        // itemAdded event fired with correct payload
        XCTAssertEqual(added.count, 1)
        XCTAssertEqual(added[0].key1, "alpha")
        XCTAssertEqual(added[0].key2, 1)
        XCTAssertEqual(added[0].value, 3.14, accuracy: 1e-9)

        // keys1 contains the new Key1; keys2 contains the new Key2
        XCTAssertTrue(sut.keys1.toArray().contains("alpha"))
        XCTAssertTrue(sut.keys2.toArray().contains(1))
    }

    // ── COL-011 ──────────────────────────────────────────────────────────────

    /// COL-011 — ObservableDictionary remove clears the entry and fires itemRemoved.
    func testCOL011RemoveClearsEntryAndFiresItemRemoved() {
        let sut = ObservableDictionary<String, Int, Double>()
        sut.set("alpha", 1, 3.14)
        sut.set("alpha", 2, 2.72) // same key1, different key2
        sut.set("beta", 1, 1.41)  // different key1, same key2

        var removed: [DictionaryItemRemovedEvent<String, Int, Double>] = []
        sut.itemRemoved.sink { removed.append($0) }.store(in: &cancellables)

        let result = sut.delete("alpha", 1)

        // Returns true
        XCTAssertTrue(result)

        // Entry no longer present; size decremented
        XCTAssertFalse(sut.has("alpha", 1))
        XCTAssertEqual(sut.size, 2)

        // itemRemoved fired with the correct payload
        XCTAssertEqual(removed.count, 1)
        XCTAssertEqual(removed[0].key1, "alpha")
        XCTAssertEqual(removed[0].key2, 1)
        XCTAssertEqual(removed[0].value, 3.14, accuracy: 1e-9)

        // "alpha" still in keys1 (because ("alpha",2) remains)
        XCTAssertTrue(sut.keys1.toArray().contains("alpha"))
        // Key2=1 still in keys2 (because ("beta",1) remains)
        XCTAssertTrue(sut.keys2.toArray().contains(1))

        // Remove the last entry holding key2=2
        sut.delete("alpha", 2)
        XCTAssertFalse(sut.keys2.toArray().contains(2))

        // Remove the last entry holding key1="beta"
        sut.delete("beta", 1)
        XCTAssertFalse(sut.keys1.toArray().contains("beta"))
        XCTAssertFalse(sut.keys2.toArray().contains(1))

        // delete() of an absent pair returns false
        XCTAssertFalse(sut.delete("nope", 99))
    }

    // ── COL-012 ──────────────────────────────────────────────────────────────

    /// COL-012 — Replacing an entry fires itemReplaced, not added/removed.
    func testCOL012ReplaceFiresItemReplacedNotAddedOrRemoved() {
        let sut = ObservableDictionary<String, Int, Double>()
        sut.set("alpha", 1, 3.14)

        var added: [String] = []
        var removed: [String] = []
        var replaced: [DictionaryItemReplacedEvent<String, Int, Double>] = []

        sut.itemAdded.sink { _ in added.append("added") }.store(in: &cancellables)
        sut.itemRemoved.sink { _ in removed.append("removed") }.store(in: &cancellables)
        sut.itemReplaced.sink { replaced.append($0) }.store(in: &cancellables)

        // set() on an existing key pair triggers a replace
        sut.set("alpha", 1, 9.99)

        // New value is accessible; size unchanged
        XCTAssertEqual(sut.get("alpha", 1) ?? .nan, 9.99, accuracy: 1e-9)
        XCTAssertEqual(sut.size, 1)

        // itemReplaced fired, NOT added or removed
        XCTAssertEqual(added.count, 0, "replace must NOT fire itemAdded")
        XCTAssertEqual(removed.count, 0, "replace must NOT fire itemRemoved")
        XCTAssertEqual(replaced.count, 1)
        XCTAssertEqual(replaced[0].key1, "alpha")
        XCTAssertEqual(replaced[0].key2, 1)
        XCTAssertEqual(replaced[0].newValue, 9.99, accuracy: 1e-9)
        XCTAssertEqual(replaced[0].oldValue, 3.14, accuracy: 1e-9)
    }

    // ── COL-013 ──────────────────────────────────────────────────────────────

    /// COL-013 — keys1/keys2 views reflect distinct keys in first-appearance
    /// order and drop a key when its last entry is removed.
    func testCOL013KeyViewsReflectDistinctKeysInSync() {
        let sut = ObservableDictionary<String, Int, Double>()

        var keys1Added: [String] = []
        var keys1Removed: [String] = []
        sut.keys1.itemAdded.sink { keys1Added.append($0.item) }.store(in: &cancellables)
        sut.keys1.itemRemoved.sink { keys1Removed.append($0.item) }.store(in: &cancellables)

        var keys2Added: [Int] = []
        var keys2Removed: [Int] = []
        sut.keys2.itemAdded.sink { keys2Added.append($0.item) }.store(in: &cancellables)
        sut.keys2.itemRemoved.sink { keys2Removed.append($0.item) }.store(in: &cancellables)

        // First entry — both axes get new values
        sut.set("alpha", 1, 1.0)
        XCTAssertEqual(keys1Added, ["alpha"])
        XCTAssertEqual(keys2Added, [1])

        // Second entry with same Key1 — keys1 must NOT fire again
        sut.set("alpha", 2, 2.0)
        XCTAssertEqual(keys1Added.count, 1, "Key1='alpha' already present")
        XCTAssertTrue(keys2Added.contains(2))

        // Entry with a new Key1 but an existing Key2
        sut.set("beta", 1, 3.0)
        XCTAssertTrue(keys1Added.contains("beta"))
        XCTAssertEqual(keys2Added.count, 2, "Key2=1 already present")

        // First-appearance ordering of the live views
        XCTAssertEqual(sut.keys1.toArray(), ["alpha", "beta"])
        XCTAssertEqual(sut.keys2.toArray(), [1, 2])

        // Remove ("alpha", 1) — "alpha" still alive via ("alpha", 2)
        sut.delete("alpha", 1)
        XCTAssertEqual(keys1Removed.count, 0, "alpha still has an entry")

        // Remove ("alpha", 2) — "alpha" now gone
        sut.delete("alpha", 2)
        XCTAssertTrue(keys1Removed.contains("alpha"))

        // Key2=2 disappeared when ("alpha",2) was removed
        XCTAssertTrue(keys2Removed.contains(2))
    }

    // ── COL-014 ──────────────────────────────────────────────────────────────

    /// COL-014 — Enumerating ObservableDictionary yields entries in insertion order.
    func testCOL014EnumerationYieldsInsertionOrder() {
        let sut = ObservableDictionary<String, Int, Double>()
        sut.set("alpha", 1, 1.1)
        sut.set("beta", 2, 2.2)
        sut.set("gamma", 1, 3.3)
        sut.set("alpha", 2, 4.4)

        // Iterate via Sequence conformance (insertion order).
        let entries = Array(sut)

        XCTAssertEqual(entries.count, 4)
        XCTAssertEqual(entries[0].key1, "alpha")
        XCTAssertEqual(entries[0].key2, 1)
        XCTAssertEqual(entries[0].value, 1.1, accuracy: 1e-9)
        XCTAssertEqual(entries[1].key1, "beta")
        XCTAssertEqual(entries[1].key2, 2)
        XCTAssertEqual(entries[1].value, 2.2, accuracy: 1e-9)
        XCTAssertEqual(entries[2].key1, "gamma")
        XCTAssertEqual(entries[2].key2, 1)
        XCTAssertEqual(entries[2].value, 3.3, accuracy: 1e-9)
        XCTAssertEqual(entries[3].key1, "alpha")
        XCTAssertEqual(entries[3].key2, 2)
        XCTAssertEqual(entries[3].value, 4.4, accuracy: 1e-9)

        // A replace updates the value in place but preserves order.
        sut.set("beta", 2, 22.2)
        let afterReplace = sut.entries()
        XCTAssertEqual(afterReplace[1].key1, "beta")
        XCTAssertEqual(afterReplace[1].value, 22.2, accuracy: 1e-9)
    }

    // ── COL-015 ──────────────────────────────────────────────────────────────

    /// COL-015 — clear() resets size to 0 and empties keys1 and keys2 views.
    func testCOL015ClearResetsSizeAndEmptiesKeyViews() {
        let sut = ObservableDictionary<String, Int, Double>()
        sut.set("alpha", 1, 1.0)
        sut.set("beta", 2, 2.0)

        var granular: [String] = []
        var resetFired: [Bool] = []

        sut.itemAdded.sink { _ in granular.append("added") }.store(in: &cancellables)
        sut.itemRemoved.sink { _ in granular.append("removed") }.store(in: &cancellables)
        sut.reset.sink { resetFired.append(true) }.store(in: &cancellables)

        // Subscribers on the keys1 / keys2 views record their removal events.
        var keys1Events: [String] = []
        var keys2Events: [String] = []
        sut.keys1.reset.sink { keys1Events.append("reset") }.store(in: &cancellables)
        sut.keys1.itemRemoved.sink { _ in keys1Events.append("removed") }.store(in: &cancellables)
        sut.keys1.propertyChanged.sink { keys1Events.append("pc:\($0)") }.store(in: &cancellables)
        sut.keys2.reset.sink { keys2Events.append("reset") }.store(in: &cancellables)
        sut.keys2.itemRemoved.sink { _ in keys2Events.append("removed") }.store(in: &cancellables)
        sut.keys2.propertyChanged.sink { keys2Events.append("pc:\($0)") }.store(in: &cancellables)

        sut.clear()

        // Size drops to zero
        XCTAssertEqual(sut.size, 0)

        // keys1 and keys2 are empty
        XCTAssertEqual(sut.keys1.count, 0)
        XCTAssertEqual(sut.keys2.count, 0)

        // Each key view emitted exactly one bulk removal (Reset) plus its Count
        // change — clear is a whole-list removal, not per-key removals.
        XCTAssertEqual(keys1Events, ["reset", "pc:Count"], "keys1 must emit one Reset removal")
        XCTAssertEqual(keys2Events, ["reset", "pc:Count"], "keys2 must emit one Reset removal")

        // reset fired exactly once
        XCTAssertEqual(resetFired.count, 1)

        // No individual itemAdded/itemRemoved events fired during clear
        XCTAssertEqual(granular.count, 0, "clear must NOT fire per-entry events")
    }

    // ── COL-022 ──────────────────────────────────────────────────────────────

    /// COL-022 — mutations publish CollectionChangedMessage to the hub with
    /// keys + value in the payload, after the local granular event.
    func testCOL022HubPublicationCarriesKeysAndValue() {
        let hub = MessageHub()
        let sut = ObservableDictionary<String, Int, Double>(hub: hub)

        var received: [CollectionChangedMessage<DictionaryEntry<String, Int, Double>>] = []
        hub.messages
            .compactMap { $0 as? CollectionChangedMessage<DictionaryEntry<String, Int, Double>> }
            .sink { received.append($0) }
            .store(in: &cancellables)

        // Local-before-hub ordering on add.
        var callOrder: [String] = []
        sut.itemAdded.sink { _ in callOrder.append("local") }.store(in: &cancellables)
        hub.messages.sink { _ in callOrder.append("hub") }.store(in: &cancellables)

        // Add — publishes an "add" message; newItems[0] carries key1, key2, value.
        sut.set("alpha", 1, 3.14)
        XCTAssertEqual(callOrder, ["local", "hub"], "local granular event fires before hub")
        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received[0].action, .add)
        XCTAssertTrue(received[0].sender === sut)
        let addEntry = received[0].newItems[0]
        XCTAssertEqual(addEntry.key1, "alpha")
        XCTAssertEqual(addEntry.key2, 1)
        XCTAssertEqual(addEntry.value, 3.14, accuracy: 1e-9)

        received.removeAll()

        // Replace via set on an existing key — publishes a "replace" message.
        sut.set("alpha", 1, 9.99)
        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received[0].action, .replace)
        let replaceNew = received[0].newItems[0]
        let replaceOld = received[0].oldItems[0]
        XCTAssertEqual(replaceNew.key1, "alpha")
        XCTAssertEqual(replaceNew.key2, 1)
        XCTAssertEqual(replaceNew.value, 9.99, accuracy: 1e-9)
        XCTAssertEqual(replaceOld.key1, "alpha")
        XCTAssertEqual(replaceOld.key2, 1)
        XCTAssertEqual(replaceOld.value, 3.14, accuracy: 1e-9)

        received.removeAll()

        // Remove — publishes a "remove" message; oldItems[0] carries the entry.
        sut.delete("alpha", 1)
        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received[0].action, .remove)
        let removeEntry = received[0].oldItems[0]
        XCTAssertEqual(removeEntry.key1, "alpha")
        XCTAssertEqual(removeEntry.key2, 1)
        XCTAssertEqual(removeEntry.value, 9.99, accuracy: 1e-9)

        received.removeAll()

        // Clear — publishes a single "reset" message (no items).
        sut.set("beta", 2, 2.72)
        received.removeAll() // discard the Add above
        sut.clear()
        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received[0].action, .reset)
        XCTAssertEqual(received[0].newItems.count, 0)
        XCTAssertEqual(received[0].oldItems.count, 0)
    }

    /// COL-022 — no-hub construction: no errors and no publication on any mutation.
    func testCOL022NoHubFallbackDoesNotThrow() {
        // Construct without a hub — must not trap on any mutation.
        let sut = ObservableDictionary<String, Int, Double>()
        sut.set("x", 1, 1.0)
        sut.set("x", 1, 2.0) // replace
        sut.delete("x", 1)
        sut.set("y", 2, 3.0)
        sut.clear()

        // Reached here without trapping → null-hub fallback holds.
        XCTAssertEqual(sut.size, 0)
    }

    /// add(_:_:_:) strict-inserts and throws duplicateKey on an existing pair
    /// (unlike set, which upserts) — spec/21 §4.1, parity with C#/Python/TS.
    func testStrictAddInsertsAndThrowsOnDuplicate() throws {
        let sut = ObservableDictionary<String, Int, Double>()
        var added: [DictionaryItemAddedEvent<String, Int, Double>] = []
        sut.itemAdded.sink { added.append($0) }.store(in: &cancellables)

        try sut.add("alpha", 1, 3.14)
        XCTAssertTrue(sut.has("alpha", 1))
        XCTAssertEqual(sut.get("alpha", 1) ?? .nan, 3.14, accuracy: 1e-9)
        XCTAssertEqual(added.count, 1)

        XCTAssertThrowsError(try sut.add("alpha", 1, 9.99)) { error in
            guard case ObservableDictionaryError.duplicateKey = error else {
                return XCTFail("expected duplicateKey, got \(error)")
            }
        }
        // Value unchanged, no second add event.
        XCTAssertEqual(sut.get("alpha", 1) ?? .nan, 3.14, accuracy: 1e-9)
        XCTAssertEqual(added.count, 1)
    }
}
