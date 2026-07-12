import Combine
import XCTest
@testable import VMx

private final class ServicedEqualItem: Equatable {
    let value: String

    init(_ value: String) {
        self.value = value
    }

    static func == (lhs: ServicedEqualItem, rhs: ServicedEqualItem) -> Bool {
        lhs.value == rhs.value
    }
}

private final class ServicedLifecycleProbe: Equatable {
    var lifecycleCalls = 0

    static func == (lhs: ServicedLifecycleProbe, rhs: ServicedLifecycleProbe) -> Bool {
        lhs === rhs
    }

    func construct() { lifecycleCalls += 1 }
    func dispose() { lifecycleCalls += 1 }
    func reparent() { lifecycleCalls += 1 }
}

final class ServicedObservableCollectionParityTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// COL-048 — value removal targets the first equal item and publishes the stored instance.
    func testCOL048ValueRemovalTargetsFirstEqualStoredItem() {
        let first = ServicedEqualItem("a")
        let middle = ServicedEqualItem("b")
        let second = ServicedEqualItem("a")
        let equalProbe = ServicedEqualItem("a")
        let sut = ServicedObservableCollection<ServicedEqualItem>()
        [first, middle, second].forEach(sut.append)
        var messages: [CollectionChangedMessage<ServicedEqualItem>] = []
        sut.collectionChanged.sink { messages.append($0) }.store(in: &cancellables)

        XCTAssertTrue(sut.remove(equalProbe))

        XCTAssertTrue(sut.at(0) === middle)
        XCTAssertTrue(sut.at(1) === second)
        XCTAssertEqual(messages.count, 1)
        XCTAssertEqual(messages[0].action, .remove)
        XCTAssertTrue(messages[0].oldItems[0] === first)
        XCTAssertEqual(messages[0].index, 0)
        XCTAssertEqual(messages[0].oldIndex, 0)
        XCTAssertEqual(messages[0].newIndex, -1)

        XCTAssertFalse(sut.remove(ServicedEqualItem("missing")))
        XCTAssertEqual(messages.count, 1)
    }

    /// COL-049 — indexed removal publishes the stored item and its pre-removal position.
    func testCOL049IndexedRemovalPublishesStoredItemAndPosition() {
        let a = ServicedEqualItem("a")
        let b = ServicedEqualItem("b")
        let c = ServicedEqualItem("c")
        let sut = ServicedObservableCollection<ServicedEqualItem>()
        [a, b, c].forEach(sut.append)
        var messages: [CollectionChangedMessage<ServicedEqualItem>] = []
        sut.collectionChanged.sink { messages.append($0) }.store(in: &cancellables)

        sut.removeAt(1)

        XCTAssertTrue(sut.at(0) === a && sut.at(1) === c)
        XCTAssertEqual(messages.count, 1)
        XCTAssertEqual(messages[0].action, .remove)
        XCTAssertTrue(messages[0].oldItems[0] === b)
        XCTAssertEqual(messages[0].index, 1)
        XCTAssertEqual(messages[0].oldIndex, 1)
        XCTAssertEqual(messages[0].newIndex, -1)
    }

    /// COL-050 — named replacement always emits once with both items and one position.
    func testCOL050NamedReplacementEmitsForDistinctAndIdenticalItems() {
        let a = ServicedEqualItem("a")
        let b = ServicedEqualItem("b")
        let c = ServicedEqualItem("c")
        let sut = ServicedObservableCollection<ServicedEqualItem>()
        [a, b].forEach(sut.append)
        var messages: [CollectionChangedMessage<ServicedEqualItem>] = []
        sut.collectionChanged.sink { messages.append($0) }.store(in: &cancellables)

        sut.replace(at: 1, with: c)
        sut.replace(at: 1, with: c)

        XCTAssertTrue(sut.at(1) === c)
        XCTAssertEqual(messages.map(\.action), [.replace, .replace])
        XCTAssertTrue(messages[0].oldItems[0] === b && messages[0].newItems[0] === c)
        XCTAssertTrue(messages[1].oldItems[0] === c && messages[1].newItems[0] === c)
        for message in messages {
            XCTAssertEqual(message.index, 1)
            XCTAssertEqual(message.oldIndex, 1)
            XCTAssertEqual(message.newIndex, 1)
        }
    }

    /// COL-051 — whole-list replacement snapshots input and emits one Reset except empty-to-empty.
    func testCOL051ReplaceAllSnapshotsSelfAndHonorsEmptyCases() {
        let sut = ServicedObservableCollection<Int>()
        [1, 2, 3].forEach(sut.append)
        var messages: [CollectionChangedMessage<Int>] = []
        sut.collectionChanged.sink { messages.append($0) }.store(in: &cancellables)

        sut.replaceAll(sut)
        sut.replaceAll([1, 2, 3])

        XCTAssertEqual(sut.toArray(), [1, 2, 3])
        XCTAssertEqual(messages.map(\.action), [.reset, .reset])
        for message in messages {
            XCTAssertEqual(message.newItems, [])
            XCTAssertEqual(message.oldItems, [])
            XCTAssertEqual(message.index, -1)
            XCTAssertEqual(message.oldIndex, -1)
            XCTAssertEqual(message.newIndex, -1)
        }

        let empty = ServicedObservableCollection<Int>()
        var emptyMessages = 0
        empty.collectionChanged.sink { _ in emptyMessages += 1 }.store(in: &cancellables)
        empty.replaceAll([Int]())
        XCTAssertEqual(emptyMessages, 0)
    }

    /// COL-052 — forward and backward moves preserve identity and publish precise positions.
    func testCOL052MovesPreserveIdentityAndPublishPositions() throws {
        let a = ServicedEqualItem("a")
        let b = ServicedEqualItem("b")
        let c = ServicedEqualItem("c")
        let forward = ServicedObservableCollection<ServicedEqualItem>()
        [a, b, c].forEach(forward.append)
        var forwardMessages: [CollectionChangedMessage<ServicedEqualItem>] = []
        forward.collectionChanged.sink { forwardMessages.append($0) }.store(in: &cancellables)

        try forward.move(from: 0, to: 2)

        XCTAssertTrue(forward.at(0) === b && forward.at(1) === c && forward.at(2) === a)
        XCTAssertEqual(forwardMessages.count, 1)
        XCTAssertEqual(forwardMessages[0].action, .move)
        XCTAssertTrue(forwardMessages[0].oldItems[0] === a)
        XCTAssertTrue(forwardMessages[0].newItems[0] === a)
        XCTAssertEqual(forwardMessages[0].index, 2)
        XCTAssertEqual(forwardMessages[0].oldIndex, 0)
        XCTAssertEqual(forwardMessages[0].newIndex, 2)

        let backward = ServicedObservableCollection<ServicedEqualItem>()
        [a, b, c].forEach(backward.append)
        var backwardMessages: [CollectionChangedMessage<ServicedEqualItem>] = []
        backward.collectionChanged.sink { backwardMessages.append($0) }.store(in: &cancellables)

        try backward.move(from: 2, to: 0)

        XCTAssertTrue(backward.at(0) === c && backward.at(1) === a && backward.at(2) === b)
        XCTAssertEqual(backwardMessages.count, 1)
        XCTAssertEqual(backwardMessages[0].oldIndex, 2)
        XCTAssertEqual(backwardMessages[0].newIndex, 0)
    }

    /// COL-053 — same-index move is silent and every invalid bound throws atomically.
    func testCOL053MoveNoOpAndBoundsAreAtomic() throws {
        let hub = MessageHub()
        let sut = ServicedObservableCollection<Int>(hub: hub)
        [1, 2, 3].forEach(sut.append)
        var localMessages: [CollectionChangedMessage<Int>] = []
        var hubMessages: [CollectionChangedMessage<Int>] = []
        sut.collectionChanged.sink { localMessages.append($0) }.store(in: &cancellables)
        hub.messages.compactMap { $0 as? CollectionChangedMessage<Int> }
            .sink { hubMessages.append($0) }.store(in: &cancellables)

        try sut.move(from: 1, to: 1)
        XCTAssertThrowsError(try sut.move(from: -1, to: 0)) {
            XCTAssertEqual($0 as? VMCollectionIndexError, VMCollectionIndexError(index: -1, count: 3))
        }
        XCTAssertThrowsError(try sut.move(from: 0, to: -1))
        XCTAssertThrowsError(try sut.move(from: 3, to: 0))
        XCTAssertThrowsError(try sut.move(from: 0, to: 3))

        XCTAssertEqual(sut.toArray(), [1, 2, 3])
        XCTAssertTrue(localMessages.isEmpty)
        XCTAssertTrue(hubMessages.isEmpty)
    }

    /// COL-054 — every effective mutation delivers final state locally before the hub.
    func testCOL054AllMutationsDeliverLocalBeforeHubWithFinalState() throws {
        let hub = MessageHub()
        let sut = ServicedObservableCollection<Int>(hub: hub)
        var observations: [String] = []
        sut.collectionChanged
            .sink { _ in observations.append("local:\(sut.toArray())") }
            .store(in: &cancellables)
        hub.messages
            .compactMap { $0 as? CollectionChangedMessage<Int> }
            .sink { _ in observations.append("hub:\(sut.toArray())") }
            .store(in: &cancellables)

        sut.append(1)
        sut.replace(at: 0, with: 2)
        sut.replaceAll([3, 4])
        try sut.move(from: 0, to: 1)
        sut.removeAt(0)
        sut.clear()

        XCTAssertEqual(observations, [
            "local:[1]", "hub:[1]",
            "local:[2]", "hub:[2]",
            "local:[3, 4]", "hub:[3, 4]",
            "local:[4, 3]", "hub:[4, 3]",
            "local:[3]", "hub:[3]",
            "local:[]", "hub:[]",
        ])
    }

    /// COL-055 — empty clear is silent and all mutations leave item lifecycle to the caller.
    func testCOL055ClearAndMutationsNeverManageItemLifecycle() throws {
        let a = ServicedLifecycleProbe()
        let b = ServicedLifecycleProbe()
        let c = ServicedLifecycleProbe()
        let d = ServicedLifecycleProbe()
        let e = ServicedLifecycleProbe()
        let sut = ServicedObservableCollection<ServicedLifecycleProbe>()
        var messages: [CollectionChangedMessage<ServicedLifecycleProbe>] = []
        sut.collectionChanged.sink { messages.append($0) }.store(in: &cancellables)

        sut.clear()
        XCTAssertTrue(messages.isEmpty)

        [a, b, c].forEach(sut.append)
        messages.removeAll()
        XCTAssertTrue(sut.remove(a))
        sut.removeAt(0)
        sut.replace(at: 0, with: d)
        sut.replaceAll([d, e])
        try sut.move(from: 0, to: 1)
        sut.clear()

        XCTAssertEqual(messages.map(\.action), [.remove, .remove, .replace, .reset, .move, .reset])
        XCTAssertEqual(messages.last?.index, -1)
        XCTAssertEqual(messages.last?.oldIndex, -1)
        XCTAssertEqual(messages.last?.newIndex, -1)
        XCTAssertTrue([a, b, c, d, e].allSatisfy { $0.lifecycleCalls == 0 })
    }

    func testExistingAliasesAndMessageMemberwiseDefaultsRemainCompatible() {
        let sut = ServicedObservableCollection<Int>()
        sut.append(1)
        sut.setAt(0, 2)
        XCTAssertEqual(sut.removeLast(), 2)

        let message = CollectionChangedMessage<Int>(
            senderObject: sut,
            senderName: "fixture",
            action: .reset,
            newItems: [],
            oldItems: [],
            index: -1
        )
        XCTAssertEqual(message.oldIndex, -1)
        XCTAssertEqual(message.newIndex, -1)
    }
}
