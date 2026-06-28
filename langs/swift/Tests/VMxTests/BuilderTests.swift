//
// Builder conformance tests.
//
// Claimed IDs: BLD-001..004 here (BLD-005, additive triggers, lives in
// RelayCommandTests).
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

    /// BLD-002 — missing required field (name) raises
    /// `BuilderValidationError`.
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

    /// BLD-002 — missing required field (services) raises.
    func testBld002MissingServicesThrows() {
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

    /// BLD-002 — CompositeVMBuilder validates `children` at `build()`
    /// (required-field validation, per spec v2.3.0).
    func testBld002CompositeMissingChildrenThrows() {
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

    /// BLD-003 — repeated identical Build calls produce equivalent
    /// (but distinct) VMs.
    func testBld003RepeatedBuildEquivalent() throws {
        let b = ComponentVMBuilder().name("x").hint("h").withNullServices()
        let vm1 = try b.build()
        let vm2 = try b.build()
        XCTAssertFalse(vm1 === vm2)
        XCTAssertEqual(vm1.name, vm2.name)
        XCTAssertEqual(vm1.hint, vm2.hint)
    }

    /// BLD-004 — field defaults applied when not set: `hint` defaults to
    /// empty, lifecycle starts at `.destructed`, and `withNullServices`
    /// wires both null services in one go.
    func testBld004FieldDefaults() throws {
        let vm = try ComponentVMBuilder()
            .name("x")
            .withNullServices()
            .build()
        XCTAssertEqual(vm.hint, "")
        XCTAssertEqual(vm.status, .destructed)
        // Constructing succeeds via the null hub & dispatcher.
        try vm.construct()
        XCTAssertEqual(vm.status, .constructed)
    }
}
