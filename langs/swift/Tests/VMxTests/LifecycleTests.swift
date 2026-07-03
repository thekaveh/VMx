//
// Lifecycle conformance tests.
//
// Claimed IDs: LIFE-001..007, 009, 010, 011, 012, 013, 014 (LIFE-005/006 now
// assert a *catchable throw* — v3 converges Swift to the throwing contract per
// ADR-0053, superseding ADR-0037 §2.5). LIFE-008 (concurrent re-invocation
// raises) is claimed in `LifecycleRaceTests`. LIFE-011 asserts the
// fixture-driven table. LIFE-014 asserts transactional hook-failure rollback.
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

    /// Transition-table positive cases against the fixture-driven table.
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

    /// VMX-103 — drift guard for the fixture-driven transition table. The legal
    /// canConstruct/canDestruct/canReconstruct truth table is asserted across
    /// every externally observable status. LIFE-011 covers the full fixture
    /// round-trip; this test covers the predicate surface.
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

    /// LIFE-013 — dispose on a parent disposes every descendant depth-first:
    /// grandchildren before their parent composite, children before the root.
    ///
    ///     root (CompositeVM)
    ///       ├── child-a (CompositeVM) ── gc-a1, gc-a2 (ComponentVM)
    ///       └── child-b (CompositeVM) ── gc-b1, gc-b2 (ComponentVM)
    ///
    /// The dispose order is observed via ConstructionStatusChangedMessage(.disposed)
    /// on a shared hub — parity with the C#/Python/TypeScript LIFE-013 corpus
    /// (CompositeVMConformanceTests.cs, test_composite_vm.py, lifecycle.test.ts).
    func testLife013DisposeCascadesDepthFirst() throws {
        let hub = MessageHub()
        let disp = ImmediateDispatcher.INSTANCE

        let gcA1 = makeVM(name: "gc-a1", hub: hub)
        let gcA2 = makeVM(name: "gc-a2", hub: hub)
        let gcB1 = makeVM(name: "gc-b1", hub: hub)
        let gcB2 = makeVM(name: "gc-b2", hub: hub)

        let childA = try CompositeVM<ComponentVM>.builder()
            .name("child-a").services(hub: hub, dispatcher: disp)
            .children { [gcA1, gcA2] }.build()
        let childB = try CompositeVM<ComponentVM>.builder()
            .name("child-b").services(hub: hub, dispatcher: disp)
            .children { [gcB1, gcB2] }.build()

        let root = try CompositeVM<CompositeVM<ComponentVM>>.builder()
            .name("root").services(hub: hub, dispatcher: disp)
            .children { [childA, childB] }.build()

        try root.construct()
        XCTAssertEqual(gcA1.status, .constructed)
        XCTAssertEqual(childA.status, .constructed)
        XCTAssertEqual(root.status, .constructed)

        // Record dispose order. Subscribe after construct so only dispose-phase
        // messages are seen; filter defensively on .disposed.
        var disposeOrder: [String] = []
        let cancel = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .sink { if $0.status == .disposed { disposeOrder.append($0.senderName) } }

        root.dispose()

        // Every node reaches .disposed.
        for vm in [gcA1, gcA2, gcB1, gcB2] {
            XCTAssertEqual(vm.status, .disposed)
        }
        XCTAssertEqual(childA.status, .disposed)
        XCTAssertEqual(childB.status, .disposed)
        XCTAssertEqual(root.status, .disposed)

        // Depth-first: grandchildren before their parent composite; children
        // before the root.
        func idx(_ name: String) -> Int {
            guard let i = disposeOrder.firstIndex(of: name) else {
                XCTFail("\(name) must emit a .disposed message"); return .max
            }
            return i
        }
        XCTAssertLessThan(idx("gc-a1"), idx("child-a"), "gc-a1 disposes before child-a")
        XCTAssertLessThan(idx("gc-a2"), idx("child-a"), "gc-a2 disposes before child-a")
        XCTAssertLessThan(idx("gc-b1"), idx("child-b"), "gc-b1 disposes before child-b")
        XCTAssertLessThan(idx("gc-b2"), idx("child-b"), "gc-b2 disposes before child-b")
        XCTAssertLessThan(idx("child-a"), idx("root"), "child-a disposes before root")
        XCTAssertLessThan(idx("child-b"), idx("root"), "child-b disposes before root")

        cancel.cancel()
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

    /// LIFE-011 — the lifecycle state machine matches EVERY row of the canonical
    /// `lifecycle-transitions.json` fixture (all 20): legal rows reach `to_final`;
    /// illegal rows raise a catchable `StatusTransitionError` (ADR-0053). The
    /// mid-transition source rows (`Constructing` / `Destructing`) are reached the
    /// way the catalog's `When` allows — "via a test scheduler or controllable
    /// hook" — by holding a background VM on a deferred dispatcher that parks the
    /// completion, the same device `LifecycleRaceTests` and LIFE-008 use. Parity
    /// with C# `LifecycleConformanceTests.DriveTransition`, which drives all 20.
    func testLife011StateMachineMatchesFixtureTable() throws {
        struct Row: Decodable {
            let from: String, via: String, toFinal: String?, legal: Bool
            enum CodingKeys: String, CodingKey {
                case from, via, legal
                case toFinal = "to_final"
            }
        }
        struct Fixture: Decodable { let transitions: [Row] }

        let url = try XCTUnwrap(
            Bundle.module.url(forResource: "lifecycle-transitions", withExtension: "json")
        )
        let fixture = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))

        // Guard against a filtered/partial sweep silently under-covering the
        // table again (the previous revision exercised only 9 of 20 rows).
        XCTAssertEqual(
            fixture.transitions.count, 20,
            "LIFE-011 must drive every fixture row, including dispose and transient sources"
        )

        for row in fixture.transitions {
            let (error, final) = driveTransition(from: row.from, via: row.via)
            if row.legal {
                XCTAssertNil(
                    error,
                    "\(row.from)/\(row.via) is legal and must not throw (got \(String(describing: error)))"
                )
                XCTAssertEqual(
                    final.name, row.toFinal,
                    "\(row.from)/\(row.via) → expected \(row.toFinal ?? "nil"), got \(final.name)"
                )
            } else {
                XCTAssertTrue(
                    error is StatusTransitionError,
                    "\(row.from)/\(row.via) is illegal and must throw StatusTransitionError (got \(String(describing: error)))"
                )
            }
        }
    }

    /// Drives one fixture row: parks a fresh VM in `from` (transient states via a
    /// deferred/background dispatcher), attempts `via`, and returns any catchable
    /// error plus the settled status. Mirrors C# `DriveTransition`.
    private func driveTransition(from: String, via: String)
        -> (error: Error?, final: ConstructionStatus)
    {
        // Transient sources (`Constructing`/`Destructing`) need a dispatcher that
        // PARKS the background completion so the VM is observably mid-transition;
        // settled sources run inline on `ImmediateDispatcher`.
        let transient = (from == "Constructing" || from == "Destructing")
        let deferred = DeferredLifecycleDispatcher()
        let dispatcher: Dispatcher = transient ? deferred : ImmediateDispatcher.INSTANCE

        let vm = try! ComponentVM.builder()
            .name("life011")
            .services(hub: MessageHub(), dispatcher: dispatcher)
            .background(transient)
            .build()

        // Put the VM into `from`. Transient rows are held parked mid-transition.
        switch from {
        case "Destructed":
            break                                   // freshly built
        case "Constructed":
            try! vm.construct()
        case "Disposed":
            vm.dispose()
        case "Constructing":
            try! vm.construct()                     // emits .constructing; parked
        case "Destructing":
            try! vm.construct(); deferred.flush()   // settle to .constructed
            try! vm.destruct()                      // emits .destructing; parked
        default:
            XCTFail("unhandled from-state \(from)")
        }

        // Attempt `via`, capturing any catchable StatusTransitionError (ADR-0053).
        var captured: Error?
        do {
            switch via {
            case "construct":   try vm.construct()
            case "destruct":    try vm.destruct()
            case "reconstruct": try vm.reconstruct()
            case "dispose":     vm.dispose()
            default: XCTFail("unhandled via \(via)")
            }
        } catch {
            captured = error
        }

        return (captured, vm.status)
    }

    /// Deterministically parks background lifecycle work so a source VM can be
    /// held mid-transition (`.constructing` / `.destructing`). Identical to
    /// `LifecycleRaceTests.DeferredDispatcher` — the proven mechanism LIFE-008
    /// relies on. `flush()` drains the parked work on the calling thread.
    private final class DeferredLifecycleDispatcher: Dispatcher {
        private var pending: [() -> Void] = []
        func scheduleForeground(_ work: @escaping () -> Void) { work() }
        func scheduleBackground(_ work: @escaping () -> Void) { pending.append(work) }
        func flush() {
            let work = pending
            pending = []
            for run in work { run() }
        }
    }

    /// LIFE-014 — a throwing construct/destruct hook is transactional: the
    /// exception propagates AND `status` rolls back to the prior settled state
    /// (Destructed after a failed construct; Constructed after a failed destruct),
    /// so the VM is recoverable rather than wedged in a transient state.
    func testLife014ThrowingHookRollsBackStatus() throws {
        struct HookError: Error {}

        // Failed construct → rolls back to Destructed; then a retry with a
        // non-throwing hook reaches Constructed (recoverable, not wedged).
        var failConstruct = true
        let onC = ComponentVM(
            name: "life014c", hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            onConstruct: { if failConstruct { throw HookError() } }
        )
        XCTAssertThrowsError(try onC.construct()) { XCTAssertTrue($0 is HookError) }
        XCTAssertEqual(onC.status, .destructed, "failed construct must roll back to Destructed")
        failConstruct = false
        try onC.construct()
        XCTAssertEqual(onC.status, .constructed,
            "a retry with a non-throwing construct hook reaches Constructed")

        // Failed destruct → rolls back to Constructed; then a retry reaches Destructed.
        var failDestruct = true
        let onD = ComponentVM(
            name: "life014d", hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            onDestruct: { if failDestruct { throw HookError() } }
        )
        try onD.construct()
        XCTAssertThrowsError(try onD.destruct()) { XCTAssertTrue($0 is HookError) }
        XCTAssertEqual(onD.status, .constructed, "failed destruct must roll back to Constructed")
        failDestruct = false
        try onD.destruct()
        XCTAssertEqual(onD.status, .destructed,
            "a retry with a non-throwing destruct hook reaches Destructed")
    }

    func testReconstructDestructHookFailureRollsBackToConstructed() throws {
        struct HookError: Error {}
        let vm = ComponentVM(
            name: "reconstruct-destruct",
            hub: MessageHub(),
            dispatcher: ImmediateDispatcher.INSTANCE,
            onDestruct: { throw HookError() }
        )
        try vm.construct()

        XCTAssertThrowsError(try vm.reconstruct()) { XCTAssertTrue($0 is HookError) }
        XCTAssertEqual(vm.status, .constructed)
    }

    func testReconstructConstructHookFailureRollsBackToDestructed() throws {
        struct HookError: Error {}
        var shouldThrow = false
        let vm = ComponentVM(
            name: "reconstruct-construct",
            hub: MessageHub(),
            dispatcher: ImmediateDispatcher.INSTANCE,
            onConstruct: {
                if shouldThrow { throw HookError() }
            }
        )
        try vm.construct()
        shouldThrow = true

        XCTAssertThrowsError(try vm.reconstruct()) { XCTAssertTrue($0 is HookError) }
        XCTAssertEqual(vm.status, .destructed)
    }

    func testConcurrentDisposeInvokesOnDisposeAtMostOnce() {
        for _ in 0..<500 {
            let vm = OnDisposeProbeVM()
            let group = DispatchGroup()
            let queue = DispatchQueue.global(qos: .userInitiated)
            let start = DispatchSemaphore(value: 0)

            for _ in 0..<16 {
                group.enter()
                queue.async {
                    start.wait()
                    vm.dispose()
                    group.leave()
                }
            }
            for _ in 0..<16 { start.signal() }

            XCTAssertEqual(group.wait(timeout: .now() + 5), .success)
            XCTAssertEqual(vm.disposeCalls, 1)
        }
    }
}

private final class OnDisposeProbeVM: ComponentVMBase {
    private let lock = NSLock()
    private var _disposeCalls = 0

    init() {
        super.init(
            name: "dispose-probe",
            hub: MessageHub(),
            dispatcher: ImmediateDispatcher.INSTANCE
        )
    }

    override var type: ViewModelType { .component }

    var disposeCalls: Int {
        lock.lock()
        defer { lock.unlock() }
        return _disposeCalls
    }

    override func _onDispose() {
        lock.lock()
        _disposeCalls += 1
        lock.unlock()
    }
}
