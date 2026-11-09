//
// CollectionNotificationStepTests.swift — COL-072 structural coverage.
//
// Claimed IDs: COL-072.
//
// COL-072 requires that a failing subscriber skips no later notification step
// of a committed collection change (spec/21-collections.md §2.5, §3.3, §4.6,
// ADR-0220). In Swift a subscriber cannot fail: every `ObservableList` and
// key-view publisher has the failure type `Never`, and a Combine `sink`
// closure cannot throw. These tests pin that structure and check that each
// mutation still runs every later step once.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-15).
//
import Combine
import XCTest
@testable import VMx

final class CollectionNotificationStepTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func failureType<P: Publisher>(of _: P) -> Any.Type { P.Failure.self }

    private func assertCannotFail<K>(_ view: ReadOnlyObservableList<K>, _ name: String) {
        XCTAssertTrue(failureType(of: view.itemAdded) == Never.self, name)
        XCTAssertTrue(failureType(of: view.itemRemoved) == Never.self, name)
        XCTAssertTrue(failureType(of: view.itemReplaced) == Never.self, name)
        XCTAssertTrue(failureType(of: view.reset) == Never.self, name)
        XCTAssertTrue(failureType(of: view.propertyChanged) == Never.self, name)
    }

    /// COL-072 — structural: no `ObservableList` or key-view subscriber can
    /// fail, so no notification step can be skipped by a failing subscriber.
    func testCOL072ListAndKeyViewPublishersCannotFail() {
        let list = ObservableList<Int>()
        let dictionary = ObservableDictionary<String, Int, String>()

        XCTAssertTrue(failureType(of: list.itemAdded) == Never.self)
        XCTAssertTrue(failureType(of: list.itemRemoved) == Never.self)
        XCTAssertTrue(failureType(of: list.itemReplaced) == Never.self)
        XCTAssertTrue(failureType(of: list.reset) == Never.self)
        XCTAssertTrue(failureType(of: list.propertyChanged) == Never.self)
        assertCannotFail(dictionary.keys1, "keys1")
        assertCannotFail(dictionary.keys2, "keys2")
    }

    /// COL-072 — each list mutation reaches two subscribers of its event once,
    /// then sends `Count` once.
    func testCOL072ListMutationRunsEveryStepOnce() {
        let cases: [(String, Int, (ObservableList<Int>) -> AnyPublisher<Void, Never>, (ObservableList<Int>) -> Void, Int)] = [
            ("append", 0, { $0.itemAdded.map { _ in () }.eraseToAnyPublisher() }, { $0.append(1) }, 1),
            ("insert", 0, { $0.itemAdded.map { _ in () }.eraseToAnyPublisher() }, { $0.insert(1, at: 0) }, 1),
            ("removeAt", 1, { $0.itemRemoved.map { _ in () }.eraseToAnyPublisher() }, { $0.removeAt(0) }, 0),
            ("clear", 1, { $0.reset }, { $0.clear() }, 0),
            ("replaceAll", 1, { $0.reset }, { $0.replaceAll([1, 2]) }, 2),
            ("withBatch", 0, { $0.reset }, { list in list.withBatch { list.append(1) } }, 1),
        ]
        for (name, initial, event, act, finalCount) in cases {
            let list = ObservableList<Int>()
            for _ in 0..<initial { list.append(1) }
            var first = 0, second = 0
            var names: [String] = []
            event(list).sink { first += 1 }.store(in: &cancellables)
            event(list).sink { second += 1 }.store(in: &cancellables)
            list.propertyChanged.sink { names.append($0) }.store(in: &cancellables)

            act(list)

            XCTAssertEqual(list.count, finalCount, name)
            XCTAssertEqual([first, second], [1, 1], name)
            XCTAssertEqual(names, ["Count"], name)
        }
    }

    /// COL-072 — a key-view notification is followed by the dictionary event
    /// and one hub message, and both views match the entries.
    func testCOL072KeyViewNotificationPrecedesEveryDictionaryStep() throws {
        let cases: [(String, (ObservableDictionary<String, Int, String>) throws -> Void)] = [
            ("add", { try $0.add("b", 2, "x") }),
            ("set", { $0.set("b", 2, "x") }),
            ("delete", { _ = $0.delete("a", 1) }),
            ("clear", { $0.clear() }),
        ]
        for (name, act) in cases {
            let hub = MessageHub()
            let dictionary = ObservableDictionary<String, Int, String>(hub: hub)
            try dictionary.add("a", 1, "v")
            var order: [String] = []
            hub.messages.sink { _ in order.append("hub") }.store(in: &cancellables)
            dictionary.itemAdded.sink { _ in order.append("event") }.store(in: &cancellables)
            dictionary.itemRemoved.sink { _ in order.append("event") }.store(in: &cancellables)
            dictionary.reset.sink { order.append("event") }.store(in: &cancellables)
            let views: [AnyPublisher<Void, Never>] = [
                dictionary.keys1.itemAdded.map { _ in () }.eraseToAnyPublisher(),
                dictionary.keys1.itemRemoved.map { _ in () }.eraseToAnyPublisher(),
                dictionary.keys1.reset,
                dictionary.keys2.itemAdded.map { _ in () }.eraseToAnyPublisher(),
                dictionary.keys2.itemRemoved.map { _ in () }.eraseToAnyPublisher(),
                dictionary.keys2.reset,
            ]
            for view in views {
                view.sink { order.append("view") }.store(in: &cancellables)
            }

            try act(dictionary)

            XCTAssertEqual(order, ["view", "view", "event", "hub"], name)
            let entries = dictionary.entries()
            var keys1: [String] = []
            var keys2: [Int] = []
            for entry in entries {
                if !keys1.contains(entry.key1) { keys1.append(entry.key1) }
                if !keys2.contains(entry.key2) { keys2.append(entry.key2) }
            }
            XCTAssertEqual(dictionary.keys1.toArray(), keys1, name)
            XCTAssertEqual(dictionary.keys2.toArray(), keys2, name)
            cancellables.removeAll()
        }
    }
}
