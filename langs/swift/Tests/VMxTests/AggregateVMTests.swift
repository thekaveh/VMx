//
// AggregateVM conformance subset (AGG-001..AGG-006).
//
// Parametric over arity 1..6. Each test exercises the construct cascade
// and component-slot population.
//
import XCTest
@testable import VMx

final class AggregateVMTests: XCTestCase {

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder().name(name).withNullServices().build()
    }

    /// AGG-001 — arity-1 populates component1 on construct.
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

    /// AGG-003 — arity-3 populates all three slots.
    func testAgg003Arity3() throws {
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

    /// AGG-004 — arity-4.
    func testAgg004Arity4() throws {
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

    /// AGG-005 — arity-5.
    func testAgg005Arity5() throws {
        let a = try AggregateVM5<ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM>.builder()
            .name("a5").withNullServices()
            .component1 { self.leaf("c1") }
            .component2 { self.leaf("c2") }
            .component3 { self.leaf("c3") }
            .component4 { self.leaf("c4") }
            .component5 { self.leaf("c5") }
            .build()
        a.construct()
        XCTAssertEqual(a.component5?.status, .constructed)
    }

    /// AGG-006 — arity-6 (added in spec v2.2). Destruct cascades to all
    /// six slots.
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
