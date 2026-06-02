//
// Builder conformance subset (BLD-001..BLD-005).
//
import XCTest
@testable import VMx

final class BuilderTests: XCTestCase {

    /// BLD-001 — every setter returns a new builder instance; the
    /// original is untouched.
    func testBld001BuilderImmutability() {
        let b1 = ComponentVMBuilder().name("a")
        let b2 = b1.name("b")
        // The originals are value types (struct); copies don't share
        // storage. The contract is satisfied by Swift's `struct` copy
        // semantics. We assert by re-building from each: if mutation
        // had leaked, `b1` would build with name "b".
        XCTAssertNoThrow(try b1.withNullServices().build())
        XCTAssertNoThrow(try b2.withNullServices().build())
        let vm1 = try! b1.withNullServices().build()
        let vm2 = try! b2.withNullServices().build()
        XCTAssertEqual(vm1.name, "a")
        XCTAssertEqual(vm2.name, "b")
    }

    /// BLD-002 — missing required field raises `BuilderValidationError`.
    func testBld002MissingNameThrows() {
        XCTAssertThrowsError(
            try ComponentVMBuilder()
                .withNullServices()
                .build()
        ) { err in
            guard let e = err as? BuilderValidationError else {
                XCTFail("expected BuilderValidationError, got \(err)")
                return
            }
            XCTAssertEqual(e.missingField, "name")
        }
    }

    /// BLD-003 — missing services raises.
    func testBld003MissingServicesThrows() {
        XCTAssertThrowsError(
            try ComponentVMBuilder().name("x").build()
        ) { err in
            guard let e = err as? BuilderValidationError else {
                XCTFail("expected BuilderValidationError, got \(err)")
                return
            }
            XCTAssertEqual(e.missingField, "services")
        }
    }

    /// BLD-004 — `withNullServices` wires both null services in one go.
    func testBld004WithNullServices() throws {
        let vm = try ComponentVMBuilder()
            .name("x")
            .withNullServices()
            .build()
        // Constructing succeeds via the null hub & dispatcher.
        vm.construct()
        XCTAssertEqual(vm.status, .constructed)
    }

    /// BLD-005 — CompositeVMBuilder validates `children` at `build()`
    /// (per spec v2.3.0).
    func testBld005CompositeMissingChildrenThrows() {
        XCTAssertThrowsError(
            try CompositeVM<ComponentVM>.builder()
                .name("c")
                .withNullServices()
                .build()
        ) { err in
            guard let e = err as? BuilderValidationError else {
                XCTFail("expected BuilderValidationError, got \(err)")
                return
            }
            XCTAssertEqual(e.missingField, "children")
        }
    }
}
