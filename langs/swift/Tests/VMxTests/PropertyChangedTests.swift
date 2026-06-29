//
// PropertyChanged conformance tests.
//
// Claimed IDs: PROP-001..004 — base property-change notifications for the
// modeled ComponentVMOf<Model>. Setting `model` to a different value
// publishes exactly one PropertyChangedMessage on the "model" channel;
// setting it to an equal value publishes none.
//
import XCTest
import Combine
@testable import VMx

private struct Item: Equatable {
    let id: Int
    let label: String
}

final class PropertyChangedTests: XCTestCase {

    // MARK: - helpers

    private func makeVM(hub: MessageHub, initial: Item) throws -> ComponentVMOf<Item> {
        try ComponentVMOf<Item>.builder()
            .name("vm1")
            .model(initial)
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()   // Equatable overload — defaults modelEquals to ==
    }

    // MARK: - tests

    /// PROP-001 — Setting model to a different value publishes exactly one PropertyChangedMessage for "model".
    func testProp001DifferentValuePublishesExactlyOne() throws {
        let hub = MessageHub()
        let vm  = try makeVM(hub: hub, initial: Item(id: 1, label: "Alice"))

        var modelMsgs: [PropertyChangedMessage] = []
        let cancel = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.propertyName == "model" }
            .sink { modelMsgs.append($0) }

        vm.model = Item(id: 2, label: "Bob")

        XCTAssertEqual(modelMsgs.count, 1,
                       "exactly one PropertyChangedMessage for 'model' must be emitted")
        cancel.cancel()
    }

    /// PROP-002 — Setting model to the same value publishes zero PropertyChangedMessages.
    func testProp002SameValuePublishesNothing() throws {
        let hub     = MessageHub()
        let initial = Item(id: 1, label: "Alice")
        let vm      = try makeVM(hub: hub, initial: initial)

        var modelMsgs: [PropertyChangedMessage] = []
        let cancel = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.propertyName == "model" }
            .sink { modelMsgs.append($0) }

        vm.model = initial   // equal value — modelEquals(==) returns true → no emit

        XCTAssertEqual(modelMsgs.count, 0,
                       "equal value must not publish a PropertyChangedMessage")
        cancel.cancel()
    }

    /// PROP-003 — message.sender is identity-equal (===) to the emitting VM instance.
    func testProp003SenderIdentityEqualsVM() throws {
        let hub = MessageHub()
        let vm  = try makeVM(hub: hub, initial: Item(id: 1, label: "Alice"))

        var captured: AnyObject?
        let cancel = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.propertyName == "model" }
            .sink { captured = $0.sender }

        vm.model = Item(id: 2, label: "Bob")

        XCTAssertTrue(captured === vm,
                      "sender must be the same object as the emitting VM (identity equality)")
        cancel.cancel()
    }

    /// PROP-004 — propertyName equals "model" (camelCase per ADR-0006) and senderName equals vm.name.
    func testProp004PropertyNameAndSenderName() throws {
        let hub = MessageHub()
        let vm  = try makeVM(hub: hub, initial: Item(id: 1, label: "Alice"))

        var propertyName: String?
        var senderName: String?
        let cancel = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.propertyName == "model" }
            .sink {
                propertyName = $0.propertyName
                senderName   = $0.senderName
            }

        vm.model = Item(id: 2, label: "Bob")

        XCTAssertEqual(propertyName, "model",
                       "propertyName must be \"model\" (camelCase)")
        XCTAssertEqual(senderName, "vm1",
                       "senderName must equal the VM's name")
        cancel.cancel()
    }
}
