import Combine
import XCTest
@testable import VMx

private final class KeyedItem: Equatable {
    var key: String
    let value: String
    var lifecycleCalls = 0

    init(_ key: String, _ value: String) {
        self.key = key
        self.value = value
    }

    static func == (lhs: KeyedItem, rhs: KeyedItem) -> Bool { lhs.value == rhs.value }
    func dispose() { lifecycleCalls += 1 }
    func reparent() { lifecycleCalls += 1 }
}

private enum KeyProjectionFailure: Error, Equatable { case rejected }

private final class ReferenceKey: Hashable {
    var value: String

    init(_ value: String) { self.value = value }

    static func == (lhs: ReferenceKey, rhs: ReferenceKey) -> Bool {
        lhs.value == rhs.value
    }

    func hash(into hasher: inout Hasher) { hasher.combine(value) }
}

private final class ReferenceKeyItem {
    let key: ReferenceKey
    let value: String

    init(_ key: ReferenceKey, _ value: String) {
        self.key = key
        self.value = value
    }
}

final class KeyedServicedObservableCollectionTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func makeCollection(
        hub: (any MessageHubProtocol)? = nil,
        projections: ((String) -> Void)? = nil
    ) -> KeyedServicedObservableCollection<String, KeyedItem> {
        KeyedServicedObservableCollection(keyOf: { item in
            projections?(item.key)
            if item.key == "throw" { throw KeyProjectionFailure.rejected }
            return item.key
        }, hub: hub)
    }

    /// COL-056 — lookup uses captured keys without reprojecting and order remains list-like.
    func testCOL056CapturedLookupAndOrder() throws {
        var projected: [String] = []
        let sut = makeCollection { projected.append($0) }
        let a = KeyedItem("a", "a")
        let b = KeyedItem("b", "b")
        let c = KeyedItem("c", "c")
        try [a, b, c].forEach(sut.append)
        var messages = 0
        sut.collectionChanged.sink { _ in messages += 1 }.store(in: &cancellables)

        for key in ["a", "b", "c"] {
            XCTAssertTrue(sut.get(key) === ["a": a, "b": b, "c": c][key])
            XCTAssertTrue(sut.containsKey(key))
        }
        XCTAssertEqual(projected, ["a", "b", "c"])
        XCTAssertEqual(sut.toArray().map(\.value), ["a", "b", "c"])
        XCTAssertEqual(Array(sut).map(\.value), ["a", "b", "c"])
        XCTAssertTrue(sut.at(1) === b)

        b.key = "renamed"
        XCTAssertTrue(sut.get("b") === b)
        XCTAssertNil(sut.get("renamed"))
        XCTAssertEqual(projected, ["a", "b", "c"])
        XCTAssertEqual(messages, 0)
    }

    /// COL-057 — duplicate and projection failures are typed, atomic, and silent.
    func testCOL057FailuresAreAtomicAndExactThrowingSurfaceCompiles() throws {
        let hub = MessageHub()
        let sut = makeCollection(hub: hub)
        let a = KeyedItem("a", "a")
        let b = KeyedItem("b", "b")
        try sut.append(a)
        try sut.append(b)
        var local = 0
        var external = 0
        sut.collectionChanged.sink { _ in local += 1 }.store(in: &cancellables)
        hub.messages.compactMap { $0 as? CollectionChangedMessage<KeyedItem> }
            .sink { _ in external += 1 }.store(in: &cancellables)

        func assertDuplicate(_ body: () throws -> Void) {
            XCTAssertThrowsError(try body()) { error in
                guard case KeyedServicedCollectionError.duplicateKey = error else {
                    return XCTFail("unexpected error: \(error)")
                }
            }
            XCTAssertEqual(sut.toArray().map(\.value), ["a", "b"])
            XCTAssertTrue(sut.get("a") === a && sut.get("b") === b)
            XCTAssertEqual(local, 0)
            XCTAssertEqual(external, 0)
        }

        assertDuplicate { try sut.append(KeyedItem("a", "duplicate")) }
        assertDuplicate { try sut.replace(at: 0, with: KeyedItem("b", "duplicate")) }
        assertDuplicate { try sut.setAt(0, KeyedItem("b", "duplicate")) }
        assertDuplicate { try sut.replaceAll([KeyedItem("x", "x"), KeyedItem("x", "duplicate")]) }
        XCTAssertThrowsError(try sut.append(KeyedItem("throw", "bad"))) {
            XCTAssertEqual($0 as? KeyProjectionFailure, .rejected)
        }
        XCTAssertThrowsError(try sut.upsert(KeyedItem("throw", "bad"))) {
            XCTAssertEqual($0 as? KeyProjectionFailure, .rejected)
        }
        XCTAssertEqual(sut.toArray().map(\.value), ["a", "b"])
        XCTAssertEqual(local, 0)
        XCTAssertEqual(external, 0)
    }

    /// COL-058 — upsert appends missing keys and replaces present keys in place.
    func testCOL058UpsertOutcomesAndPayloads() throws {
        let sut = makeCollection()
        let a = KeyedItem("a", "a")
        let b = KeyedItem("b", "b")
        try sut.append(a)
        try sut.append(b)
        var messages: [CollectionChangedMessage<KeyedItem>] = []
        sut.collectionChanged.sink { messages.append($0) }.store(in: &cancellables)

        let c = KeyedItem("c", "c")
        XCTAssertTrue(try sut.upsert(c))
        let b2 = KeyedItem("b", "b2")
        XCTAssertFalse(try sut.upsert(b2))
        XCTAssertFalse(try sut.upsert(b2))

        XCTAssertEqual(sut.toArray().map(\.value), ["a", "b2", "c"])
        XCTAssertEqual(messages.map(\.action), [.add, .replace, .replace])
        XCTAssertEqual(messages[0].newIndex, 2)
        XCTAssertTrue(messages[1].oldItems[0] === b && messages[1].newItems[0] === b2)
        XCTAssertEqual(messages[1].oldIndex, 1)
        XCTAssertEqual(messages[1].newIndex, 1)
        XCTAssertTrue(messages[2].oldItems[0] === b2 && messages[2].newItems[0] === b2)
    }

    /// COL-059 — keyed delete uses the captured index and reports missing keys silently.
    func testCOL059DeleteUsesCapturedPreRemovalPosition() throws {
        let sut = makeCollection()
        let a = KeyedItem("a", "a")
        let b = KeyedItem("b", "b")
        let c = KeyedItem("c", "c")
        try [a, b, c].forEach(sut.append)
        var messages: [CollectionChangedMessage<KeyedItem>] = []
        sut.collectionChanged.sink { messages.append($0) }.store(in: &cancellables)

        XCTAssertTrue(sut.delete("b"))
        XCTAssertFalse(sut.delete("missing"))

        XCTAssertEqual(sut.toArray().map(\.value), ["a", "c"])
        XCTAssertNil(sut.get("b"))
        XCTAssertEqual(messages.count, 1)
        XCTAssertEqual(messages[0].action, .remove)
        XCTAssertTrue(messages[0].oldItems[0] === b)
        XCTAssertEqual(messages[0].oldIndex, 1)
    }

    /// COL-060 — removals and explicit replacement rekey every shifted membership correctly.
    func testCOL060RemovalAndExplicitRekeyKeepIndexSynchronized() throws {
        let sut = makeCollection()
        let firstA = KeyedItem("a", "equal")
        let b = KeyedItem("b", "b")
        let secondA = KeyedItem("c", "equal")
        try [firstA, b, secondA].forEach(sut.append)

        firstA.key = "b"
        XCTAssertThrowsError(try sut.replace(at: 0, with: firstA)) {
            guard case KeyedServicedCollectionError.duplicateKey = $0 else {
                return XCTFail("unexpected error: \($0)")
            }
        }
        XCTAssertTrue(sut.get("a") === firstA && sut.get("b") === b)
        firstA.key = "a"

        XCTAssertTrue(sut.remove(KeyedItem("unused", "equal")))
        XCTAssertTrue(sut.get("b") === b && sut.get("c") === secondA)
        sut.removeAt(0)
        XCTAssertTrue(sut.get("c") === secondA)

        secondA.key = "d"
        try sut.replace(at: 0, with: secondA)
        XCTAssertNil(sut.get("c"))
        XCTAssertTrue(sut.get("d") === secondA)

        let fresh = makeCollection()
        let mutable = KeyedItem("old", "same")
        try fresh.append(mutable)
        mutable.key = "new"
        XCTAssertTrue(try fresh.upsert(mutable))
        XCTAssertEqual(fresh.count, 2)
        XCTAssertTrue(fresh.get("old") === mutable && fresh.get("new") === mutable)
    }

    func testCOL060ReplaceAndUpsertRecaptureDistinctEqualReferenceKeys() throws {
        let sut = KeyedServicedObservableCollection<ReferenceKey, ReferenceKeyItem>(
            keyOf: { $0.key }
        )

        let retiredReplaceKey = ReferenceKey("a")
        try sut.append(ReferenceKeyItem(retiredReplaceKey, "old-a"))
        let replacementKey = ReferenceKey("a")
        let replacement = ReferenceKeyItem(replacementKey, "new-a")
        try sut.replace(at: 0, with: replacement)
        retiredReplaceKey.value = "retired-a"
        XCTAssertTrue(sut.get(ReferenceKey("a")) === replacement)

        let retiredUpsertKey = ReferenceKey("b")
        try sut.append(ReferenceKeyItem(retiredUpsertKey, "old-b"))
        let upsertKey = ReferenceKey("b")
        let upserted = ReferenceKeyItem(upsertKey, "new-b")
        XCTAssertFalse(try sut.upsert(upserted))
        retiredUpsertKey.value = "retired-b"
        XCTAssertTrue(sut.get(ReferenceKey("b")) === upserted)
        XCTAssertNil(sut.get(ReferenceKey("retired-a")))
        XCTAssertNil(sut.get(ReferenceKey("retired-b")))
    }

    /// COL-061 — replaceAll preflights keys, snapshots self input, and emits one Reset.
    func testCOL061ReplaceAllPreflightsAndSnapshotsSelf() throws {
        let sut = makeCollection()
        let a = KeyedItem("a", "a")
        let b = KeyedItem("b", "b")
        try [a, b].forEach(sut.append)
        var messages: [CollectionChangedMessage<KeyedItem>] = []
        sut.collectionChanged.sink { messages.append($0) }.store(in: &cancellables)

        try sut.replaceAll(sut)
        XCTAssertEqual(messages.map(\.action), [.reset])
        XCTAssertTrue(sut.get("a") === a && sut.get("b") === b)

        XCTAssertThrowsError(try sut.replaceAll([KeyedItem("x", "x"), KeyedItem("throw", "bad")])) {
            XCTAssertEqual($0 as? KeyProjectionFailure, .rejected)
        }
        XCTAssertEqual(sut.toArray().map(\.value), ["a", "b"])
        XCTAssertEqual(messages.count, 1)

        let empty = makeCollection()
        var emptyMessages = 0
        empty.collectionChanged.sink { _ in emptyMessages += 1 }.store(in: &cancellables)
        try empty.replaceAll([KeyedItem]())
        XCTAssertEqual(emptyMessages, 0)
    }

    /// COL-062 — move, clear, removeLast, and value removal preserve keys and ownership.
    func testCOL062ConveniencesPreserveInvariantsAndOwnership() throws {
        let sut = makeCollection()
        let a = KeyedItem("a", "a")
        let b = KeyedItem("b", "b")
        let c = KeyedItem("c", "c")
        try [a, b, c].forEach(sut.append)
        var actions: [CollectionChangedAction] = []
        sut.collectionChanged.sink { actions.append($0.action) }.store(in: &cancellables)

        try sut.move(from: 0, to: 2)
        XCTAssertTrue(sut.get("a") === a && sut.at(2) === a)
        XCTAssertTrue(sut.remove(b))
        XCTAssertTrue(sut.removeLast() === a)
        sut.clear()
        sut.clear()

        XCTAssertEqual(actions, [.move, .remove, .remove, .reset])
        XCTAssertEqual(sut.count, 0)
        XCTAssertFalse(["a", "b", "c"].contains(where: sut.containsKey))
        XCTAssertTrue([a, b, c].allSatisfy { $0.lifecycleCalls == 0 })
    }

    /// COL-063 — local delivery is immediate and hub transactions defer equivalent messages.
    func testCOL063LocalBeforeHubAndHubBatching() throws {
        let hub = MessageHub()
        let sut = makeCollection(hub: hub)
        var observations: [String] = []
        sut.collectionChanged.sink { _ in observations.append("local:\(sut.toArray().map(\.value))") }
            .store(in: &cancellables)
        hub.messages.compactMap { $0 as? CollectionChangedMessage<KeyedItem> }
            .sink { _ in observations.append("hub:\(sut.toArray().map(\.value))") }
            .store(in: &cancellables)

        try sut.append(KeyedItem("a", "a"))
        XCTAssertEqual(observations, ["local:[\"a\"]", "hub:[\"a\"]"])
        observations.removeAll()

        try hub.batch {
            try sut.append(KeyedItem("b", "b"))
            _ = sut.delete("a")
            XCTAssertEqual(observations, ["local:[\"a\", \"b\"]", "local:[\"b\"]"])
        }
        XCTAssertEqual(observations, [
            "local:[\"a\", \"b\"]", "local:[\"b\"]", "hub:[\"b\"]", "hub:[\"b\"]",
        ])
    }

    /// COL-064 — reentrant mutation observes a fully synchronized key index per operation.
    func testCOL064ReentrantMutationKeepsIndexConsistentAndLocalBeforeOwnHub() throws {
        let hub = MessageHub()
        let sut = makeCollection(hub: hub)
        var observations: [String] = []
        var reentered = false
        sut.collectionChanged.sink { message in
            let key = message.newItems.first?.key ?? message.oldItems.first?.key ?? "reset"
            observations.append("local:\(key)")
            XCTAssertEqual(sut.toArray().allSatisfy { sut.get($0.key) === $0 }, true)
            if !reentered && key == "outer" {
                reentered = true
                do {
                    try sut.append(KeyedItem("inner", "inner"))
                } catch {
                    XCTFail("reentrant append failed: \(error)")
                }
            }
        }.store(in: &cancellables)
        hub.messages.compactMap { $0 as? CollectionChangedMessage<KeyedItem> }.sink { message in
            let key = message.newItems.first?.key ?? "reset"
            observations.append("hub:\(key)")
            XCTAssertTrue(sut.containsKey("outer"))
            XCTAssertTrue(sut.containsKey("inner"))
        }.store(in: &cancellables)

        try sut.append(KeyedItem("outer", "outer"))

        XCTAssertEqual(sut.toArray().map(\.key), ["outer", "inner"])
        for key in ["outer", "inner"] {
            XCTAssertLessThan(observations.firstIndex(of: "local:\(key)")!,
                              observations.firstIndex(of: "hub:\(key)")!)
        }
    }
}
