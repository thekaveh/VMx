//
// ServicedObservableCollectionTests.swift — conformance tests for
// ServicedObservableCollection<T>.
//
// Claimed IDs: COL-001, COL-002, COL-003, COL-004.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import Combine
import XCTest
@testable import VMx

final class ServicedObservableCollectionTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // ── COL-001 ──────────────────────────────────────────────────────────────

    /// COL-001 — ServicedObservableCollection publishes to hub after local CollectionChanged on add.
    func testCOL001AppendPublishesToHubAfterLocalEvent() {
        let hub = MessageHub()
        let sut = ServicedObservableCollection<String>(hub: hub)

        var localEvents: [CollectionChangedMessage<String>] = []
        var hubMessages: [any Message] = []
        var callOrder: [String] = []

        sut.collectionChanged
            .sink { msg in
                localEvents.append(msg)
                callOrder.append("local")
            }
            .store(in: &cancellables)

        hub.messages
            .sink { msg in
                hubMessages.append(msg)
                callOrder.append("hub")
            }
            .store(in: &cancellables)

        sut.append("alpha")

        // Local-before-hub ordering (spec/21 §2; COL-001).
        XCTAssertEqual(callOrder, ["local", "hub"])

        // Local event payload.
        XCTAssertEqual(localEvents.count, 1)
        XCTAssertEqual(localEvents[0].action, .add)
        XCTAssertEqual(localEvents[0].newItems, ["alpha"])
        XCTAssertEqual(localEvents[0].index, 0)
        XCTAssertEqual(localEvents[0].oldIndex, -1)
        XCTAssertEqual(localEvents[0].newIndex, 0)

        // Hub message is the same object.
        XCTAssertEqual(hubMessages.count, 1)
        let msg = hubMessages[0] as? CollectionChangedMessage<String>
        XCTAssertNotNil(msg)
        XCTAssertEqual(msg?.action, .add)
        XCTAssertEqual(msg?.newItems, ["alpha"])
        XCTAssertEqual(msg?.index, 0)
        XCTAssertEqual(msg?.oldIndex, -1)
        XCTAssertEqual(msg?.newIndex, 0)
    }

    // ── COL-002 ──────────────────────────────────────────────────────────────

    /// COL-002 — ServicedObservableCollection publishes correct messages on remove and replace.
    func testCOL002RemoveAndReplacePublishCorrectMessages() {
        let hub = MessageHub()
        let sut = ServicedObservableCollection<String>(hub: hub)
        sut.append("a")
        sut.append("b")

        var localEvents: [CollectionChangedMessage<String>] = []
        var hubMessages: [CollectionChangedMessage<String>] = []

        sut.collectionChanged
            .sink { localEvents.append($0) }
            .store(in: &cancellables)

        hub.messages
            .compactMap { $0 as? CollectionChangedMessage<String> }
            .sink { hubMessages.append($0) }
            .store(in: &cancellables)

        // ── Remove ──────────────────────────────────────────────────────────
        sut.removeLast()  // removes "b"

        XCTAssertEqual(localEvents.count, 1)
        XCTAssertEqual(localEvents[0].action, .remove)
        XCTAssertEqual(localEvents[0].oldItems, ["b"])
        XCTAssertEqual(localEvents[0].index, 1)
        XCTAssertEqual(localEvents[0].oldIndex, 1)
        XCTAssertEqual(localEvents[0].newIndex, -1)

        XCTAssertEqual(hubMessages.count, 1)
        XCTAssertEqual(hubMessages[0].action, .remove)
        XCTAssertEqual(hubMessages[0].oldItems, ["b"])
        XCTAssertEqual(hubMessages[0].index, 1)
        XCTAssertEqual(hubMessages[0].oldIndex, 1)
        XCTAssertEqual(hubMessages[0].newIndex, -1)

        localEvents.removeAll()
        hubMessages.removeAll()

        // ── Replace ─────────────────────────────────────────────────────────
        sut.setAt(0, "a_replaced")

        XCTAssertEqual(localEvents.count, 1)
        XCTAssertEqual(localEvents[0].action, .replace)
        XCTAssertEqual(localEvents[0].newItems, ["a_replaced"])
        XCTAssertEqual(localEvents[0].oldItems, ["a"])
        XCTAssertEqual(localEvents[0].index, 0)
        XCTAssertEqual(localEvents[0].oldIndex, 0)
        XCTAssertEqual(localEvents[0].newIndex, 0)

        XCTAssertEqual(hubMessages.count, 1)
        XCTAssertEqual(hubMessages[0].action, .replace)
        XCTAssertEqual(hubMessages[0].newItems, ["a_replaced"])
        XCTAssertEqual(hubMessages[0].oldItems, ["a"])
        XCTAssertEqual(hubMessages[0].index, 0)
        XCTAssertEqual(hubMessages[0].oldIndex, 0)
        XCTAssertEqual(hubMessages[0].newIndex, 0)
    }

    // ── COL-003 ──────────────────────────────────────────────────────────────

    /// COL-003 — Null-hub fallback: no hub means no publication, no error on any mutation.
    func testCOL003NullHubFiresLocalEventsWithoutError() {
        let sut = ServicedObservableCollection<Int>() // no hub

        var localEvents: [CollectionChangedMessage<Int>] = []
        sut.collectionChanged
            .sink { localEvents.append($0) }
            .store(in: &cancellables)

        // All mutations must not trap or error.
        sut.append(1)
        sut.append(2)
        sut.removeLast()   // remove 2
        sut.setAt(0, 99)   // replace 1 with 99
        sut.clear()

        // All five mutations are effective because the collection contains 99 before clear.
        XCTAssertEqual(localEvents.count, 5)
    }

    // ── COL-004 ──────────────────────────────────────────────────────────────

    /// COL-004 — ServicedObservableCollection fires hub message synchronously on the caller thread.
    func testCOL004HubMessageDeliveredSynchronously() {
        let hub = MessageHub()
        let sut = ServicedObservableCollection<Int>(hub: hub)

        var callOrder: [String] = []

        hub.messages
            .sink { _ in callOrder.append("hub") }
            .store(in: &cancellables)

        sut.append(42)
        callOrder.append("after-append")

        // Hub handler must have run BEFORE append() returned (COL-004).
        XCTAssertEqual(callOrder, ["hub", "after-append"])
    }

    /// remove(_:) removes the first occurrence by value, emits a granular remove,
    /// and returns whether it was found (Equatable convenience, spec/21 §2.1).
    func testRemoveByValueEmitsAndReturnsFound() {
        let sut = ServicedObservableCollection<String>(hub: MessageHub())
        sut.append("x")
        sut.append("y")
        sut.append("z")

        var localEvents: [CollectionChangedMessage<String>] = []
        sut.collectionChanged.sink { localEvents.append($0) }.store(in: &cancellables)

        XCTAssertTrue(sut.remove("y"))
        XCTAssertEqual(sut.toArray(), ["x", "z"])
        XCTAssertEqual(localEvents.count, 1)

        XCTAssertFalse(sut.remove("absent")) // not found -> false, no further event
        XCTAssertEqual(localEvents.count, 1)
    }
}
