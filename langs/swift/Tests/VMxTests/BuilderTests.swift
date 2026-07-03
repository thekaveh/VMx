//
// Builder conformance tests.
//
// Claimed IDs: BLD-001..004 and BLD-006 here (BLD-005, additive triggers, lives in
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
        // Catalog BLD-003: vmA.Type == vmB.Type.
        XCTAssertEqual(vm1.type, vm2.type)
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
        // Catalog BLD-004: Type is the type derived from the VM class.
        XCTAssertEqual(vm.type, .component)
        XCTAssertEqual(vm.status, .destructed)
        // Constructing succeeds via the null hub & dispatcher.
        try vm.construct()
        XCTAssertEqual(vm.status, .constructed)
    }

    /// BLD-006 — common VM options factories delegate to builder validation
    /// and defaults.
    func testBld006OptionsFactoriesMatchBuilderSemantics() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE

        let component = try ComponentVM.create(ComponentVMOptions(
            name: "component",
            hint: "h",
            hub: hub,
            dispatcher: dispatcher
        ))
        XCTAssertEqual(component.name, "component")
        XCTAssertEqual(component.hint, "h")
        XCTAssertEqual(component.type, .component)

        let modeled = try ComponentVMOf<String>.create(ComponentVMOfOptions(
            name: "modeled",
            model: "m",
            hub: hub,
            dispatcher: dispatcher
        ))
        XCTAssertEqual(modeled.model, "m")

        let child = try ComponentVM.create(ComponentVMOptions(
            name: "child",
            hub: hub,
            dispatcher: dispatcher
        ))
        let composite = try CompositeVM<ComponentVM>.create(CompositeVMOptions(
            name: "composite",
            hub: hub,
            dispatcher: dispatcher,
            children: { [child] }
        ))
        try composite.construct()
        XCTAssertEqual(composite.status, .constructed)
        XCTAssertEqual(composite.count, 1)

        let group = try GroupVM<ComponentVM>.create(GroupVMOptions(
            name: "group",
            hub: hub,
            dispatcher: dispatcher,
            children: { [] }
        ))
        XCTAssertEqual(group.type, .group)

        XCTAssertThrowsError(
            try ComponentVM.create(ComponentVMOptions(hub: hub, dispatcher: dispatcher))
        ) { err in
            guard let e = err as? BuilderValidationError else {
                XCTFail("expected BuilderValidationError, got \(err)")
                return
            }
            XCTAssertEqual(e.missingField, "name")
        }
    }
}
