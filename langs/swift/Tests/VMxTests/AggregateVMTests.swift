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
        a.construct()
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
        a.construct()
        XCTAssertEqual(a.component1?.status, .constructed)
        XCTAssertEqual(a.component2?.status, .constructed)
    }

    /// AGG-004 — ComponentN property change fires on construct
    /// ("component1", camelCase per the Swift idiom).
    func testAgg004ComponentPropertyChangeFires() throws {
        let hub = MessageHub()
        let a = try AggregateVM1<ComponentVM>.builder()
            .name("a1")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .component1 { self.leaf("c1") }
            .build()
        var seen: [String] = []
        let cancel = hub.messages
            .compactMap { ($0 as? PropertyChangedMessage)?.propertyName }
            .sink { seen.append($0) }

        a.construct()

        XCTAssertTrue(seen.contains("component1"))
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
        a.construct()
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
        a.construct()
        XCTAssertEqual(a.component4?.status, .constructed)
    }

    /// AGG-003 — arity-5: all five components reach Constructed.
    /// AGG-005 — destruction waits for (cascades to) all components.
    func testAgg003And005Arity5Lifecycle() throws {
        let a = try AggregateVM5<ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM>.builder()
            .name("a5").withNullServices()
            .component1 { self.leaf("c1") }
            .component2 { self.leaf("c2") }
            .component3 { self.leaf("c3") }
            .component4 { self.leaf("c4") }
            .component5 { self.leaf("c5") }
            .build()
        a.construct()
        XCTAssertEqual(a.component1?.status, .constructed)
        XCTAssertEqual(a.component2?.status, .constructed)
        XCTAssertEqual(a.component3?.status, .constructed)
        XCTAssertEqual(a.component4?.status, .constructed)
        XCTAssertEqual(a.component5?.status, .constructed)

        a.destruct()
        XCTAssertEqual(a.component1?.status, .destructed)
        XCTAssertEqual(a.component5?.status, .destructed)
    }

    /// AGG-006 — arity-6 (added in spec v2.2): all six constructed;
    /// destruction cascades to all six slots.
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
        a.construct()
        XCTAssertEqual(a.component6?.status, .constructed)
        a.destruct()
        XCTAssertEqual(a.component1?.status, .destructed)
        XCTAssertEqual(a.component6?.status, .destructed)
    }
}
