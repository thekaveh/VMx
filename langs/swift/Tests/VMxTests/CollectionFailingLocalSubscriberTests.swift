//
// CollectionFailingLocalSubscriberTests.swift — COL-066 structural coverage.
//
// Claimed IDs: COL-066.
//
// COL-066 requires that a failing local subscriber does not suppress the hub
// message (spec/01-concepts.md §1.4, spec/21-collections.md §2.5, ADR-0171).
// In Swift a local subscriber cannot fail: every local publisher has the
// failure type `Never`, and a Combine `sink` closure cannot throw. These tests
// pin that structure and the delivery a local subscriber still sees.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import Combine
import XCTest
@testable import VMx

final class CollectionFailingLocalSubscriberTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func failureType<P: Publisher>(of _: P) -> Any.Type { P.Failure.self }

    /// COL-066 — structural: no Swift local collection subscriber can fail, so
    /// every committed change reaches the hub exactly once.
    func testCOL066LocalPublishersCannotFail() {
        let serviced = ServicedObservableCollection<String>()
        let keyed = KeyedServicedObservableCollection<String, String>(keyOf: { $0 })
        let dictionary = ObservableDictionary<String, Int, String>()

        XCTAssertTrue(failureType(of: serviced.collectionChanged) == Never.self)
        XCTAssertTrue(failureType(of: keyed.collectionChanged) == Never.self)
        XCTAssertTrue(failureType(of: dictionary.itemAdded) == Never.self)
        XCTAssertTrue(failureType(of: dictionary.itemRemoved) == Never.self)
        XCTAssertTrue(failureType(of: dictionary.itemReplaced) == Never.self)
        XCTAssertTrue(failureType(of: dictionary.reset) == Never.self)
    }

    /// COL-066 — each committed change sends exactly one hub message after the
    /// local delivery.
    func testCOL066EachCommittedChangeSendsOneHubMessage() throws {
        let hub = MessageHub()
        let serviced = ServicedObservableCollection<String>(hub: hub)
        let keyed = KeyedServicedObservableCollection<String, String>(keyOf: { $0 }, hub: hub)
        let dictionary = ObservableDictionary<String, Int, String>(hub: hub)
        var order: [String] = []
        hub.messages.sink { _ in order.append("hub") }.store(in: &cancellables)
        serviced.collectionChanged.sink { _ in order.append("local") }.store(in: &cancellables)
        keyed.collectionChanged.sink { _ in order.append("local") }.store(in: &cancellables)
        dictionary.itemAdded.sink { _ in order.append("local") }.store(in: &cancellables)

        serviced.append("a")
        try keyed.append("b")
        try dictionary.add("c", 1, "one")

        XCTAssertEqual(serviced.toArray(), ["a"])
        XCTAssertEqual(keyed.get("b"), "b")
        XCTAssertEqual(dictionary.get("c", 1), "one")
        XCTAssertEqual(order, ["local", "hub", "local", "hub", "local", "hub"])
    }
}
