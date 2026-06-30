//
// HierarchicalVMBuilder conformance tests.
//
// Claimed IDs: HIER-015 (required-field validation — missing model,
// childrenFactory, services, vmFactory), HIER-016 (repeated build() produces
// distinct-but-equivalent nodes), HIER-017 (field defaults: hint == "",
// name == concrete type name, eagerChildren == false / lazy).
//
// Ported from TypeScript tests/conformance/hierarchicalVMBuilder.test.ts
// (HIER-015..017 blocks).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
@testable import VMx

// ── Concrete CRTP node for builder tests ─────────────────────────────────────
//
// Uses the inherited HierarchicalVM<String, TestNode> init directly — no
// custom init needed. Named "TestNode" so HIER-017 can assert
// `node.name == "TestNode"` (the default-name resolution path in
// HierarchicalVM.init: `name.isEmpty ? String(describing: TVM.self) : name`).

private final class TestNode: HierarchicalVM<String, TestNode> {}

// ── Helpers ───────────────────────────────────────────────────────────────────

private func makeVMFactory() -> (String, @escaping (TestNode) -> [TestNode], MessageHubProtocol, Dispatcher, String, String, Bool) -> TestNode {
    { model, cf, hub, disp, name, hint, eager in
        TestNode(
            model: model,
            childrenFactory: cf,
            hub: hub,
            dispatcher: disp,
            name: name,
            hint: hint,
            eagerChildren: eager
        )
    }
}

private func emptyFactory() -> (TestNode) -> [TestNode] { { _ in [] } }

private func baseBuilder() -> HierarchicalVMBuilder<String, TestNode> {
    HierarchicalVMBuilder<String, TestNode>()
}

// ── Test class ────────────────────────────────────────────────────────────────

final class HierarchicalVMBuilderTests: XCTestCase {

    // ── HIER-015 — required-field validation ─────────────────────────────

    /// HIER-015 — missing model → BuilderValidationError("model").
    func testHier015MissingModel() {
        XCTAssertThrowsError(
            try baseBuilder()
                .childrenFactory(emptyFactory())
                .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
                .vmFactory(makeVMFactory())
                .build()
        ) { err in
            guard let e = err as? BuilderValidationError else {
                XCTFail("expected BuilderValidationError, got \(err)"); return
            }
            XCTAssertEqual(e.missingField, "model")
        }
    }

    /// HIER-015 — missing childrenFactory → BuilderValidationError("childrenFactory").
    func testHier015MissingChildrenFactory() {
        XCTAssertThrowsError(
            try baseBuilder()
                .model("root")
                .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
                .vmFactory(makeVMFactory())
                .build()
        ) { err in
            guard let e = err as? BuilderValidationError else {
                XCTFail("expected BuilderValidationError, got \(err)"); return
            }
            XCTAssertEqual(e.missingField, "childrenFactory")
        }
    }

    /// HIER-015 — missing services → BuilderValidationError("services").
    func testHier015MissingServices() {
        XCTAssertThrowsError(
            try baseBuilder()
                .model("root")
                .childrenFactory(emptyFactory())
                .vmFactory(makeVMFactory())
                .build()
        ) { err in
            guard let e = err as? BuilderValidationError else {
                XCTFail("expected BuilderValidationError, got \(err)"); return
            }
            XCTAssertEqual(e.missingField, "services")
        }
    }

    /// HIER-015 — missing vmFactory → BuilderValidationError("vmFactory").
    func testHier015MissingVMFactory() {
        XCTAssertThrowsError(
            try baseBuilder()
                .model("root")
                .childrenFactory(emptyFactory())
                .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
                .build()
        ) { err in
            guard let e = err as? BuilderValidationError else {
                XCTFail("expected BuilderValidationError, got \(err)"); return
            }
            XCTAssertEqual(e.missingField, "vmFactory")
        }
    }

    // ── HIER-016 — repeated build() produces distinct-but-equivalent nodes ──

    /// HIER-016 — repeated build() calls produce distinct-but-equivalent nodes.
    func testHier016RepeatedBuildDistinctEquivalent() throws {
        let b = baseBuilder()
            .model("root")
            .childrenFactory(emptyFactory())
            .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            .hint("h")
            .eagerChildren(true)
            .vmFactory(makeVMFactory())

        let n1 = try b.build()
        let n2 = try b.build()

        // Independent instances (reference inequality).
        XCTAssertFalse(n1 === n2)
        // Equivalent observable state.
        XCTAssertEqual(n1.model, "root")
        XCTAssertEqual(n2.model, "root")
        XCTAssertEqual(n1.model, n2.model)
        XCTAssertEqual(n1.hint, "h")
        XCTAssertEqual(n2.hint, "h")
        XCTAssertEqual(n1.hint, n2.hint)
    }

    // ── HIER-017 — field defaults ─────────────────────────────────────────

    /// HIER-017 — hint, name, and eagerChildren defaults applied when not set.
    func testHier017FieldDefaults() throws {
        var materialized = false
        let node = try baseBuilder()
            .model("root")
            .childrenFactory({ _ in
                materialized = true
                return []
            })
            .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            .vmFactory(makeVMFactory())
            .build()

        // hint defaults to "".
        XCTAssertEqual(node.hint, "")
        // name defaults to the concrete VM type name.
        XCTAssertEqual(node.name, "TestNode")
        // eagerChildren defaults to false — factory NOT called at build time.
        XCTAssertFalse(materialized)
        // construct() without eagerChildren also does not materialize children.
        try node.construct()
        XCTAssertFalse(materialized)
        // Accessing children lazily materializes them.
        _ = node.children
        XCTAssertTrue(materialized)
    }
}
