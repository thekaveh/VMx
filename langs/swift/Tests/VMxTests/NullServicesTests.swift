//
// Null-object service variants — NULL-001..003 (spec/03-messages.md §6,
// spec/11-threading.md §5). Ports langs/typescript/tests/conformance/nullServices.test.ts.
//
import XCTest
import Combine
@testable import VMx

final class NullServicesTests: XCTestCase {

    /// NULL-001 — NullMessageHub.send is a no-op and `messages` is an empty
    /// stream that completes immediately on subscribe, emitting zero values.
    func testNullMessageHubIsInert() {
        let hub = NullMessageHub.INSTANCE
        var values = 0
        var completed = false
        let c = hub.messages.sink(receiveCompletion: { _ in completed = true },
                                  receiveValue: { _ in values += 1 })
        hub.send(PropertyChangedMessage(sender: NSObject(), senderName: "x", propertyName: "y"))
        var bodyRan = false
        XCTAssertNoThrow(try hub.batch {
            bodyRan = true
            hub.send(PropertyChangedMessage(sender: NSObject(), senderName: "x", propertyName: "z"))
        })
        XCTAssertEqual(values, 0)
        XCTAssertTrue(completed, "empty stream completes immediately on subscribe")
        XCTAssertTrue(bodyRan, "a null transaction still executes its body")
        c.cancel()
    }

    /// NULL-002 — NullDispatcher schedules both foreground and background work
    /// synchronously on the calling thread; work runs inline before schedule returns.
    func testNullDispatcherRunsInline() {
        let d = NullDispatcher.INSTANCE
        var order: [String] = []
        d.scheduleForeground { order.append("fg") }
        order.append("after-fg")
        d.scheduleBackground { order.append("bg") }
        order.append("after-bg")
        XCTAssertEqual(order, ["fg", "after-fg", "bg", "after-bg"])
    }

    /// NULL-003 — null variants satisfy their contracts (operations total, never
    /// raise) and are reachable as singletons typed by their protocols.
    func testNullVariantsSatisfyContracts() {
        let hub: any MessageHubProtocol = NullMessageHub.INSTANCE
        let disp: any Dispatcher = NullDispatcher.INSTANCE
        // INSTANCE is a shared singleton: two independent reads are identical.
        XCTAssertTrue(hub as AnyObject === NullMessageHub.INSTANCE)
        XCTAssertTrue(disp as AnyObject === NullDispatcher.INSTANCE)
        hub.send(PropertyChangedMessage(sender: NSObject(), senderName: "a", propertyName: "b"))
        disp.scheduleForeground {}
        disp.scheduleBackground {}
        // reaching here without trap/throw is the contract
    }
}
