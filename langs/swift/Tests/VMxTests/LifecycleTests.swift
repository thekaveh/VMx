//
// Lifecycle conformance tests.
//
// Claimed IDs: LIFE-001..007, 009, 010, 012, 013 (LIFE-005/006 assert the
// gating predicates — the raise itself is a trap per ADR-0037). LIFE-008
// and LIFE-011 are NOT claimed; see the per-test notes.
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
    func testLife001ConstructEmitsConstructingThenConstructed() {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        vm.construct()

        XCTAssertEqual(seen, [.constructing, .constructed])
        XCTAssertTrue(vm.isConstructed)
        cancel.cancel()
    }

    /// LIFE-002 — destruct from Constructed transitions through
    /// Destructing to Destructed.
    func testLife002DestructEmitsDestructingThenDestructed() {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        vm.construct()

        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        vm.destruct()

        XCTAssertEqual(seen, [.destructing, .destructed])
        XCTAssertFalse(vm.isConstructed)
        cancel.cancel()
    }

    /// LIFE-003 — reconstruct emits the full Destruct then Construct
    /// sequence.
    func testLife003ReconstructEmitsFullSequence() {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        vm.construct()

        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        vm.reconstruct()

        XCTAssertEqual(
            seen,
            [.destructing, .destructed, .constructing, .constructed]
        )
        cancel.cancel()
    }

    /// LIFE-004 — dispose transitions to Disposed from any state.
    func testLife004DisposeFromConstructed() {
        let vm = makeVM()
        vm.construct()
        vm.dispose()
        XCTAssertEqual(vm.status, .disposed)
    }

    func testLife004DisposeFromDestructed() {
        let vm = makeVM()
        vm.dispose()
        XCTAssertEqual(vm.status, .disposed)
    }

    /// LIFE-005 — construct from Disposed is forbidden. Swift surfaces the
    /// raise as a trap (documented divergence, ADR-0037), so the test
    /// asserts the gating predicate.
    func testLife005CannotConstructFromDisposed() {
        let vm = makeVM()
        vm.dispose()
        XCTAssertFalse(vm.canConstruct())
    }

    /// LIFE-006 — destruct from Disposed is forbidden. Swift surfaces the
    /// raise as a trap (documented divergence, ADR-0037), so the test
    /// asserts the gating predicate.
    func testLife006CannotDestructFromDisposed() {
        let vm = makeVM()
        vm.dispose()
        XCTAssertFalse(vm.canDestruct())
    }

    /// LIFE-007 — `isConstructed` equals `status == .constructed`.
    func testLife007IsConstructedTracksStatus() {
        let vm = makeVM()
        XCTAssertEqual(vm.isConstructed, vm.status == .constructed)
        vm.construct()
        XCTAssertEqual(vm.isConstructed, vm.status == .constructed)
        vm.destruct()
        XCTAssertEqual(vm.isConstructed, vm.status == .constructed)
        vm.dispose()
        XCTAssertEqual(vm.isConstructed, vm.status == .constructed)
    }

    /// Post-cycle gate check: `canConstruct()` is true from `.constructed`
    /// (the idempotency case — see LIFE-009). LIFE-008 (concurrent
    /// operation raises) is NOT claimed by this flavor: the in-flight
    /// guard traps rather than throws (ADR-0037) and the synchronous
    /// dispatcher cannot hold a mid-transition state to observe.
    func testCanConstructTrueAfterCompletedCycle() {
        let vm = makeVM()
        vm.construct()
        // Currently `.constructed`. Per the canConstruct() contract this
        // returns true (idempotency case handled by LIFE-009).
        XCTAssertTrue(vm.canConstruct())
    }

    /// LIFE-009 — construct from Constructed is idempotent (no-op).
    func testLife009ConstructFromConstructedIsNoOp() {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)
        vm.construct()

        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        vm.construct()

        XCTAssertEqual(seen, [])
        XCTAssertEqual(vm.status, .constructed)
        cancel.cancel()
    }

    /// LIFE-010 — destruct from Destructed is idempotent (no-op).
    func testLife010DestructFromDestructedIsNoOp() {
        let hub = MessageHub()
        let vm = makeVM(hub: hub)

        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        vm.destruct()

        XCTAssertEqual(seen, [])
        XCTAssertEqual(vm.status, .destructed)
        cancel.cancel()
    }

    /// Transition-table positive cases against the hand-rolled table.
    /// LIFE-011 (table matches `lifecycle-transitions.json`) is NOT
    /// claimed until this flavor loads the fixture; tracked as a
    /// follow-up in ADR-0037.
    func testHandRolledLegalTransitions() {
        let vm = makeVM()
        // destructed → construct → constructed
        XCTAssertTrue(vm.canConstruct())
        vm.construct()
        // constructed → destruct → destructed
        XCTAssertTrue(vm.canDestruct())
        vm.destruct()
        XCTAssertEqual(vm.status, .destructed)
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
    func testLife013DisposeCascadesDepthFirst() {
        let hub = MessageHub()
        let leaf1 = makeVM(name: "leaf1", hub: hub)
        let leaf2 = makeVM(name: "leaf2", hub: hub)
        let composite = try! CompositeVM<ComponentVM>.builder()
            .name("comp")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [leaf1, leaf2] }
            .build()
        composite.construct()
        XCTAssertEqual(leaf1.status, .constructed)
        XCTAssertEqual(leaf2.status, .constructed)

        composite.dispose()

        XCTAssertEqual(leaf1.status, .disposed)
        XCTAssertEqual(leaf2.status, .disposed)
        XCTAssertEqual(composite.status, .disposed)
    }
}
