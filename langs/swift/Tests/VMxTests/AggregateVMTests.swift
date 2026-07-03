//
// AggregateVM conformance tests.
//
// Claimed IDs: AGG-001..006. Arity-3 and arity-4 cascades have no
// dedicated catalog IDs; they remain as plain unit tests.
//
import XCTest
import Combine
@testable import VMx

final class AggregateVMTests: XCTestCase {

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder().name(name).withNullServices().build()
    }

    /// AGG-001 — arity-1 factory invoked on construct; component1 populated.
    func testAgg001Arity1() throws {
        let a = try AggregateVM1<ComponentVM>.builder()
            .name("a1")
            .withNullServices()
            .component1 { self.leaf("c1") }
            .build()
        try a.construct()
        XCTAssertNotNil(a.component1)
        XCTAssertEqual(a.component1?.status, .constructed)
        XCTAssertEqual(a.type, .aggregate)
    }

    /// AGG-002 — arity-2 populates both slots.
    func testAgg002Arity2() throws {
        let a = try AggregateVM2<ComponentVM, ComponentVM>.builder()
            .name("a2").withNullServices()
            .component1 { self.leaf("c1") }
            .component2 { self.leaf("c2") }
            .build()
        try a.construct()
        XCTAssertEqual(a.component1?.status, .constructed)
        XCTAssertEqual(a.component2?.status, .constructed)
    }

    /// AGG-004 — Arity-3: constructing an AggregateVM3 emits exactly three
    /// PropertyChangedMessage events on the hub, one per component slot
    /// (propertyName ∈ {component1, component2, component3}, camelCase per the
    /// Swift idiom), each with `sender === agg`. Parity with C#/Python/TS, which
    /// filter on the aggregate as sender and assert exactly three slot changes.
    func testAgg004ComponentPropertyChangeFires() throws {
        let hub = MessageHub()
        let a = try AggregateVM3<ComponentVM, ComponentVM, ComponentVM>.builder()
            .name("agg3")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .component1 { self.leaf("c1") }
            .component2 { self.leaf("c2") }
            .component3 { self.leaf("c3") }
            .build()

        // Scope to PropertyChangedMessages sent BY the aggregate itself for the
        // three component slots.
        var slotChanges: [String] = []
        let cancel = hub.messages
            .compactMap { msg -> String? in
                guard let pcm = msg as? PropertyChangedMessage,
                      pcm.sender === a,
                      ["component1", "component2", "component3"].contains(pcm.propertyName)
                else { return nil }
                return pcm.propertyName
            }
            .sink { slotChanges.append($0) }

        try a.construct()

        XCTAssertTrue(slotChanges.contains("component1"),
            "PropertyChangedMessage(component1) must be emitted on construct")
        XCTAssertTrue(slotChanges.contains("component2"),
            "PropertyChangedMessage(component2) must be emitted on construct")
        XCTAssertTrue(slotChanges.contains("component3"),
            "PropertyChangedMessage(component3) must be emitted on construct")
        XCTAssertEqual(slotChanges.count, 3,
            "exactly three slot PropertyChangedMessages are observed on construct")
        cancel.cancel()
    }

    /// Arity-3 cascade (no dedicated catalog ID).
    func testArity3() throws {
        let a = try AggregateVM3<ComponentVM, ComponentVM, ComponentVM>.builder()
            .name("a3").withNullServices()
            .component1 { self.leaf("c1") }
            .component2 { self.leaf("c2") }
            .component3 { self.leaf("c3") }
            .build()
        try a.construct()
        XCTAssertEqual(a.component1?.status, .constructed)
        XCTAssertEqual(a.component2?.status, .constructed)
        XCTAssertEqual(a.component3?.status, .constructed)
    }

    /// Arity-4 cascade (no dedicated catalog ID).
    func testArity4() throws {
        let a = try AggregateVM4<ComponentVM, ComponentVM, ComponentVM, ComponentVM>.builder()
            .name("a4").withNullServices()
            .component1 { self.leaf("c1") }
            .component2 { self.leaf("c2") }
            .component3 { self.leaf("c3") }
            .component4 { self.leaf("c4") }
            .build()
        try a.construct()
        XCTAssertEqual(a.component4?.status, .constructed)
    }

    /// AGG-003 — arity-5: the aggregate's own Constructed message is observed
    /// ONLY AFTER every ComponentI.Status has reached Constructed. A subscriber
    /// filtered on ConstructionStatusChangedMessage where sender === agg snapshots
    /// all five child statuses at the instant the aggregate's Constructed fires.
    /// AGG-005 — destruction cascades to (waits for) all five components before
    /// the aggregate itself is Destructed.
    func testAgg003And005Arity5Lifecycle() throws {
        let hub = MessageHub()
        let a = try AggregateVM5<ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM>.builder()
            .name("a5")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .component1 { self.leaf("c1") }
            .component2 { self.leaf("c2") }
            .component3 { self.leaf("c3") }
            .component4 { self.leaf("c4") }
            .component5 { self.leaf("c5") }
            .build()

        // AGG-003 — snapshot every child's status at the instant the aggregate
        // emits its own Constructed message.
        var childStatusesAtAggConstructed: [ConstructionStatus]?
        let cancel = hub.messages.sink { msg in
            guard let csm = msg as? ConstructionStatusChangedMessage,
                  csm.sender === a,
                  csm.status == .constructed else { return }
            childStatusesAtAggConstructed = [
                a.component1, a.component2, a.component3, a.component4, a.component5,
            ].compactMap { $0?.status }
        }

        try a.construct()

        let snapshot = try XCTUnwrap(childStatusesAtAggConstructed,
            "aggregate must have emitted a Constructed message")
        XCTAssertEqual(snapshot.count, 5,
            "all five child statuses must be captured when the aggregate emits Constructed")
        for status in snapshot {
            XCTAssertEqual(status, .constructed,
                "every child must be Constructed before the aggregate emits Constructed")
        }

        // AGG-005 — destruction cascades to all five children.
        try a.destruct()
        XCTAssertEqual(a.component1?.status, .destructed)
        XCTAssertEqual(a.component2?.status, .destructed)
        XCTAssertEqual(a.component3?.status, .destructed)
        XCTAssertEqual(a.component4?.status, .destructed)
        XCTAssertEqual(a.component5?.status, .destructed)
        XCTAssertEqual(a.status, .destructed)
        cancel.cancel()
    }

    /// AGG-006 — arity-6 (added in spec v2.2): on construct every ComponentI
    /// (I ∈ {1..6}) and the aggregate itself reach Constructed; on destruct every
    /// ComponentI and the aggregate itself reach Destructed.
    func testAgg006Arity6() throws {
        let a = try AggregateVM6<
            ComponentVM, ComponentVM, ComponentVM,
            ComponentVM, ComponentVM, ComponentVM
        >.builder()
            .name("a6").withNullServices()
            .component1 { self.leaf("c1") }
            .component2 { self.leaf("c2") }
            .component3 { self.leaf("c3") }
            .component4 { self.leaf("c4") }
            .component5 { self.leaf("c5") }
            .component6 { self.leaf("c6") }
            .build()

        try a.construct()
        XCTAssertEqual(a.component1?.status, .constructed)
        XCTAssertEqual(a.component2?.status, .constructed)
        XCTAssertEqual(a.component3?.status, .constructed)
        XCTAssertEqual(a.component4?.status, .constructed)
        XCTAssertEqual(a.component5?.status, .constructed)
        XCTAssertEqual(a.component6?.status, .constructed)
        XCTAssertEqual(a.status, .constructed, "aggregate itself must be Constructed")

        try a.destruct()
        XCTAssertEqual(a.component1?.status, .destructed)
        XCTAssertEqual(a.component2?.status, .destructed)
        XCTAssertEqual(a.component3?.status, .destructed)
        XCTAssertEqual(a.component4?.status, .destructed)
        XCTAssertEqual(a.component5?.status, .destructed)
        XCTAssertEqual(a.component6?.status, .destructed)
        XCTAssertEqual(a.status, .destructed, "aggregate itself must be Destructed")
    }
}
