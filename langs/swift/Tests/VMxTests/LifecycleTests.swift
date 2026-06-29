//
// Lifecycle conformance tests.
//
// Claimed IDs: LIFE-001..007, 009, 010, 012, 013 (LIFE-005/006 now assert a
// *catchable throw* — v3 converges Swift to the throwing contract per ADR-0053,
// superseding ADR-0037 §2.5). LIFE-008 (concurrent re-invocation raises) is
// claimed in `LifecycleRaceTests`. LIFE-011 is NOT claimed; see the per-test note.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
@testable import VMx

final class LifecycleTests: XCTestCase {

    private func makeVM(
        name: String = "vm",
        hub: MessageHubProtocol? = nil
    ) -> ComponentVM {
        let h = hub ?? MessageHub()
        return try! ComponentVM.builder()
            .name(name)
            .services(hub: h, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
    }

    /// LIFE-001 — construct from Destructed transitions through
    /// Constructing to Constructed.
    func testLife001ConstructEmitsConstructingThenConstructed() throws {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        try vm.construct()

        XCTAssertEqual(seen, [.constructing, .constructed])
        XCTAssertTrue(vm.isConstructed)
        cancel.cancel()
    }

    /// LIFE-002 — destruct from Constructed transitions through
    /// Destructing to Destructed.
    func testLife002DestructEmitsDestructingThenDestructed() throws {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        try vm.construct()

        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        try vm.destruct()

        XCTAssertEqual(seen, [.destructing, .destructed])
        XCTAssertFalse(vm.isConstructed)
        cancel.cancel()
    }

    /// LIFE-003 — reconstruct emits the full Destruct then Construct
    /// sequence.
    func testLife003ReconstructEmitsFullSequence() throws {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        try vm.construct()

        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        try vm.reconstruct()

        XCTAssertEqual(
            seen,
            [.destructing, .destructed, .constructing, .constructed]
        )
        cancel.cancel()
    }

    /// LIFE-004 — dispose transitions to Disposed from any state.
    func testLife004DisposeFromConstructed() throws {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        try vm.construct()

        // Subscribe after construct so only the dispose-phase messages are seen.
        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        vm.dispose()

        XCTAssertEqual(vm.status, .disposed)
        // Spec LIFE-004: a ConstructionStatusChangedMessage with Status = Disposed
        // is observed on the hub (parity with Python/C#/TS).
        XCTAssertTrue(
            seen.contains(.disposed),
            "a ConstructionStatusChangedMessage with .disposed must be observed"
        )
        cancel.cancel()
    }

    func testLife004DisposeFromDestructed() {
        let vm = makeVM()
        vm.dispose()
        XCTAssertEqual(vm.status, .disposed)
    }

    /// LIFE-005 — construct from Disposed raises. v3 (ADR-0053) converges Swift
    /// to the throwing contract: the illegal transition surfaces a *catchable*
    /// `StatusTransitionError` (was a `preconditionFailure` trap under
    /// ADR-0037 §2.5). The exception message contains the current state and the
    /// attempted operation (spec/12 LIFE-005). The gating predicate
    /// `canConstruct()` remains available as a pre-flight check.
    func testLife005ConstructFromDisposedThrows() {
        let vm = makeVM()
        vm.dispose()
        XCTAssertThrowsError(try vm.construct()) { error in
            guard let e = error as? StatusTransitionError else {
                return XCTFail("expected StatusTransitionError, got \(error)")
            }
            XCTAssertEqual(e.currentStatus, .disposed)
            XCTAssertEqual(e.attemptedOperation, "construct")
            XCTAssertTrue(e.description.contains("Disposed"))
            XCTAssertTrue(e.description.contains("construct"))
        }
        XCTAssertFalse(vm.canConstruct())
    }

    /// LIFE-006 — destruct from Disposed raises (catchable throw — ADR-0053).
    func testLife006DestructFromDisposedThrows() {
        let vm = makeVM()
        vm.dispose()
        XCTAssertThrowsError(try vm.destruct()) { error in
            guard let e = error as? StatusTransitionError else {
                return XCTFail("expected StatusTransitionError, got \(error)")
            }
            XCTAssertEqual(e.currentStatus, .disposed)
            XCTAssertEqual(e.attemptedOperation, "destruct")
            XCTAssertTrue(e.description.contains("Disposed"))
            XCTAssertTrue(e.description.contains("destruct"))
        }
        XCTAssertFalse(vm.canDestruct())
    }

    /// reconstruct from Disposed also raises a catchable error (ADR-0053).
    func testReconstructFromDisposedThrows() {
        let vm = makeVM()
        vm.dispose()
        XCTAssertThrowsError(try vm.reconstruct()) { error in
            XCTAssertTrue(error is StatusTransitionError)
        }
    }

    /// LIFE-007 — `isConstructed` equals `status == .constructed`.
    func testLife007IsConstructedTracksStatus() throws {
        let vm = makeVM()
        XCTAssertEqual(vm.isConstructed, vm.status == .constructed)
        try vm.construct()
        XCTAssertEqual(vm.isConstructed, vm.status == .constructed)
        try vm.destruct()
        XCTAssertEqual(vm.isConstructed, vm.status == .constructed)
        vm.dispose()
        XCTAssertEqual(vm.isConstructed, vm.status == .constructed)
    }

    /// Post-cycle gate check: `canConstruct()` is true from `.constructed`
    /// (the idempotency case — see LIFE-009). The concurrent-re-invocation
    /// raise (LIFE-008) is now a catchable throw and is claimed in
    /// `LifecycleRaceTests` (ADR-0053, superseding ADR-0037 §2.5).
    func testCanConstructTrueAfterCompletedCycle() throws {
        let vm = makeVM()
        try vm.construct()
        // Currently `.constructed`. Per the canConstruct() contract this
        // returns true (idempotency case handled by LIFE-009).
        XCTAssertTrue(vm.canConstruct())
    }

    /// LIFE-009 — construct from Constructed is idempotent (no-op).
    func testLife009ConstructFromConstructedIsNoOp() throws {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        try vm.construct()

        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        try vm.construct()

        XCTAssertEqual(seen, [])
        XCTAssertEqual(vm.status, .constructed)
        cancel.cancel()
    }

    /// LIFE-010 — destruct from Destructed is idempotent (no-op).
    func testLife010DestructFromDestructedIsNoOp() throws {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)

        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        try vm.destruct()

        XCTAssertEqual(seen, [])
        XCTAssertEqual(vm.status, .destructed)
        cancel.cancel()
    }

    /// Transition-table positive cases against the hand-rolled table.
    /// LIFE-011 (table matches `lifecycle-transitions.json`) is NOT
    /// claimed until this flavor loads the fixture; tracked as a
    /// follow-up in ADR-0037.
    func testHandRolledLegalTransitions() throws {
        let vm = makeVM()
        // destructed → construct → constructed
        XCTAssertTrue(vm.canConstruct())
        try vm.construct()
        // constructed → destruct → destructed
        XCTAssertTrue(vm.canDestruct())
        try vm.destruct()
        XCTAssertEqual(vm.status, .destructed)
    }

    /// VMX-103 — drift guard for the hand-rolled transition table. The legal
    /// canConstruct/canDestruct/canReconstruct truth table (which mirrors the
    /// `_isLegalTransition` table) is asserted across every externally
    /// observable status, so a future edit to either encoding that drifts from
    /// the `lifecycle-transitions.json` legal set fails here. LIFE-011 (loading
    /// the shared JSON fixture and asserting equality) remains a tracked
    /// follow-up — it needs the fixture bundled as a SwiftPM resource; this
    /// test is the in-tree partial guard until then (ADR-0037).
    func testTransitionTablePredicateDriftGuard() throws {
        // .destructed
        let d = makeVM()
        XCTAssertEqual(d.status, .destructed)
        XCTAssertTrue(d.canConstruct())       // destructed → construct    ✅
        XCTAssertTrue(d.canDestruct())        // destructed → destruct     ✅ (idempotent)
        XCTAssertFalse(d.canReconstruct())    // destructed → reconstruct  ❌

        // .constructed
        let c = makeVM(); try c.construct()
        XCTAssertEqual(c.status, .constructed)
        XCTAssertTrue(c.canConstruct())       // constructed → construct   ✅ (idempotent)
        XCTAssertTrue(c.canDestruct())        // constructed → destruct    ✅
        XCTAssertTrue(c.canReconstruct())     // constructed → reconstruct ✅

        // .disposed (terminal)
        let x = makeVM(); x.dispose()
        XCTAssertEqual(x.status, .disposed)
        XCTAssertFalse(x.canConstruct())      // disposed → construct      ❌
        XCTAssertFalse(x.canDestruct())       // disposed → destruct       ❌
        XCTAssertFalse(x.canReconstruct())    // disposed → reconstruct    ❌
    }

    /// LIFE-012 — dispose from Disposed emits no message.
    func testLife012DisposeFromDisposedIsNoOp() {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        vm.dispose()

        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        vm.dispose()

        XCTAssertEqual(seen, [])
        XCTAssertEqual(vm.status, .disposed)
        cancel.cancel()
    }

    /// LIFE-013 — dispose on a parent disposes every child depth-first.
    func testLife013DisposeCascadesDepthFirst() throws {
        let hub = MessageHub()
        let leaf1 = makeVM(name: "leaf1", hub: hub)
        let leaf2 = makeVM(name: "leaf2", hub: hub)
        let composite = try! CompositeVM<ComponentVM>.builder()
            .name("comp")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [leaf1, leaf2] }
            .build()
        try composite.construct()
        XCTAssertEqual(leaf1.status, .constructed)
        XCTAssertEqual(leaf2.status, .constructed)

        composite.dispose()

        XCTAssertEqual(leaf1.status, .disposed)
        XCTAssertEqual(leaf2.status, .disposed)
        XCTAssertEqual(composite.status, .disposed)
    }

    /// Background lifecycle on the synchronous ImmediateDispatcher runs the
    /// scheduled work inline: Constructing then Constructed (the background
    /// branches were previously wholly unexercised in this flavor).
    func testBackgroundConstructWithImmediateDispatcherCompletes() throws {
        let hub = MessageHub()
        let vm = try ComponentVM.builder()
            .name("bg")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .background(true)
            .build()
        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        try vm.construct()

        XCTAssertEqual(seen, [.constructing, .constructed])
        XCTAssertTrue(vm.isConstructed)

        try vm.destruct()
        XCTAssertEqual(vm.status, .destructed)
        cancel.cancel()
    }
}
