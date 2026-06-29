//
// Forwarding-decorator conformance tests.
//
// Claimed IDs: FWD-001 (transparent delegation of every member to the wrapped
// VM), FWD-002 (selective override replaces a single behavior), FWD-003
// (ForwardingCompositeVM forwards iteration in wrapped order). Mirrors
// langs/typescript/tests/conformance/forwarding.test.ts.
//
// Swift port note (recorded in the Task-10 divergence ADR): the TS FWD-002
// scenario overrides `hint`, but Swift `hint` is a non-overridable `public let`
// on `ComponentVMBase`. `modeledHint` is the closest overridable computed
// analog, so the Swift FWD-002 overrides `modeledHint`. `name`/`hint` never
// diverge because they are immutable and copied from the wrapped at init.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
@testable import VMx

// ── Decorator subclasses under test (file scope, matching the codebase test
//    convention of `private final class` helpers) ─────────────────────────

/// Pass-through decorator: overrides nothing, so every member delegates.
private final class NoopForwardingComponent: ForwardingComponentVM<String> {}

/// Selective override: replaces exactly one behavior (`modeledHint`); every
/// other member keeps delegating.
private final class OverrideModeledHintForwarding: ForwardingComponentVM<String> {
    override var modeledHint: String { "OVERRIDE" }
}

/// Pass-through composite decorator: overrides nothing.
private final class NoopForwardingComposite: ForwardingCompositeVM<ComponentVM> {}

final class ForwardingTests: XCTestCase {

    private func makeInner(
        name: String = "inner",
        hint: String = "inner-hint",
        model: String = "inner-model"
    ) -> ComponentVMOf<String> {
        try! ComponentVMOf<String>.builder()
            .name(name)
            .hint(hint)
            .model(model)
            .withNullServices()
            .build()
    }

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder().name(name).withNullServices().build()
    }

    // ── FWD-001 ─────────────────────────────────────────────────────────

    /// FWD-001 — ForwardingComponentVM delegates every overridable member to
    /// the wrapped instance (transparent decorator). Mirrors forwarding.test.ts
    /// FWD-001.
    func testFWD001DelegatesEveryMemberToWrapped() throws {
        let inner = makeInner()
        let fwd = NoopForwardingComponent(inner)

        // Identity / state / model read-through.
        XCTAssertEqual(fwd.name, inner.name)
        XCTAssertEqual(fwd.hint, inner.hint)
        XCTAssertEqual(fwd.type, inner.type)
        XCTAssertEqual(fwd.status, inner.status)
        XCTAssertEqual(fwd.isConstructed, inner.isConstructed)
        XCTAssertEqual(fwd.isCurrent, inner.isCurrent)
        XCTAssertEqual(fwd.model, inner.model)
        XCTAssertEqual(fwd.modeledHint, inner.modeledHint)

        // Command forwarders delegate to the SAME inner command instances.
        XCTAssertTrue(fwd.selectCommand === inner.selectCommand)
        XCTAssertTrue(fwd.deselectCommand === inner.deselectCommand)
        XCTAssertTrue(fwd.selectNextCommand === inner.selectNextCommand)
        XCTAssertTrue(fwd.selectPreviousCommand === inner.selectPreviousCommand)
        XCTAssertTrue(fwd.reconstructCommand === inner.reconstructCommand)

        // Lifecycle + selection predicates delegate to the wrapped VM.
        XCTAssertEqual(fwd.canConstruct(), inner.canConstruct())
        XCTAssertEqual(fwd.canDestruct(), inner.canDestruct())
        XCTAssertEqual(fwd.canReconstruct(), inner.canReconstruct())
        XCTAssertEqual(fwd.canSelect(), inner.canSelect())
        XCTAssertEqual(fwd.canDeselect(), inner.canDeselect())

        // Lifecycle mutators call through to the wrapped VM, observed via inner
        // state (legal order: construct → reconstruct → destruct → dispose).
        try fwd.construct()
        XCTAssertTrue(inner.isConstructed)
        XCTAssertTrue(fwd.isConstructed)

        try fwd.reconstruct()
        XCTAssertEqual(inner.status, .constructed)

        try fwd.destruct()
        XCTAssertEqual(inner.status, .destructed)

        fwd.dispose()
        XCTAssertEqual(inner.status, .disposed)
    }

    /// FWD-001 — model write-through: setting the decorator's `model` mutates
    /// the wrapped instance (the setter delegates too).
    func testFWD001ModelWriteThrough() throws {
        let inner = makeInner(model: "before")
        let fwd = NoopForwardingComponent(inner)

        fwd.model = "after"
        XCTAssertEqual(inner.model, "after")
        XCTAssertEqual(fwd.model, "after")
    }

    // ── FWD-002 ─────────────────────────────────────────────────────────

    /// FWD-002 — a selective override replaces a single behavior while every
    /// other member keeps delegating to the wrapped VM. The Swift override
    /// targets `modeledHint` (the overridable computed analog of the TS `hint`
    /// override — `hint` is a non-overridable `let` in Swift). Mirrors the
    /// intent of forwarding.test.ts FWD-002.
    func testFWD002SelectiveOverrideReplacesSingleBehavior() throws {
        let inner = try ComponentVMOf<String>.builder()
            .name("inner")
            .hint("inner-hint")
            .model("m")
            .modeledHinter { $0.uppercased() }   // inner.modeledHint == "M"
            .withNullServices()
            .build()

        let fwd = OverrideModeledHintForwarding(inner)

        // Overridden member returns the override value; the wrapped is unchanged.
        XCTAssertEqual(fwd.modeledHint, "OVERRIDE")
        XCTAssertEqual(inner.modeledHint, "M")

        // All other members still delegate to the wrapped VM unchanged.
        XCTAssertEqual(fwd.name, inner.name)
        XCTAssertEqual(fwd.hint, inner.hint)
        XCTAssertEqual(fwd.type, inner.type)
        XCTAssertEqual(fwd.isConstructed, inner.isConstructed)
        XCTAssertEqual(fwd.status, inner.status)
        XCTAssertEqual(fwd.isCurrent, inner.isCurrent)
        XCTAssertEqual(fwd.model, inner.model)

        // Commands still delegate (same instances as the wrapped VM's).
        XCTAssertTrue(fwd.selectCommand === inner.selectCommand)
        XCTAssertTrue(fwd.deselectCommand === inner.deselectCommand)
        XCTAssertTrue(fwd.selectNextCommand === inner.selectNextCommand)
        XCTAssertTrue(fwd.selectPreviousCommand === inner.selectPreviousCommand)
        XCTAssertTrue(fwd.reconstructCommand === inner.reconstructCommand)
    }

    // ── FWD-003 ─────────────────────────────────────────────────────────

    /// FWD-003 — ForwardingCompositeVM forwards iteration: iterating the
    /// decorator yields the wrapped composite's children in order, and
    /// `count`/`at(_:)` forward too. Mirrors forwarding.test.ts FWD-003.
    func testFWD003ForwardsIteration() throws {
        let vm1 = leaf("vm1")
        let vm2 = leaf("vm2")
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [vm1, vm2] }
            .build()
        try composite.construct()

        let fwd = NoopForwardingComposite(composite)

        // Iteration forwards to the wrapped's children in order.
        let items = Array(fwd)
        XCTAssertEqual(items.count, 2)
        XCTAssertTrue(items[0] === vm1)
        XCTAssertTrue(items[1] === vm2)

        // count / at(_:) forward to the wrapped.
        XCTAssertEqual(fwd.count, composite.count)
        XCTAssertTrue(fwd.at(0) === vm1)
        XCTAssertTrue(fwd.at(1) === vm2)
    }
}
