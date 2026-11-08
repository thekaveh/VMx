//
// CompositeSelectionTests.swift
//
// Conformance IDs: COMP-008, COMP-011 — throwing component selection.
// Phase 3 Increment 6 (swift-parity-inc6). Also the Constructed check at the
// selection commit (#1220).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
@testable import VMx

/// A leaf whose next `status` read, once armed, destructs it and still
/// returns the status it read first. It puts a destruct between a selection
/// path's entry check and its commit, as another thread could (#1220).
private final class DestructAfterStatusRead: ComponentVM {
    private let lock = NSLock()
    private var armed = false

    init(_ name: String) {
        super.init(name: name, hub: NullMessageHub.INSTANCE, dispatcher: NullDispatcher.INSTANCE)
    }

    func arm() { lock.withLock { armed = true } }

    override var status: ConstructionStatus {
        let value = super.status
        let fire = lock.withLock { () -> Bool in
            defer { armed = false }
            return armed
        }
        if fire { try? destruct() }
        return value
    }
}

final class CompositeSelectionTests: XCTestCase {

    private func leaf(_ name: String) -> ComponentVM {
        try! ComponentVM.builder()
            .name(name)
            .withNullServices()
            .build()
    }

    /// COMP-008 — canSelectComponent returns false for non-children, and
    /// selectComponent throws CompositeMembershipError on a non-member.
    func testComp008CanSelectComponentReturnsFalseForNonChild() throws {
        let vmA = leaf("vmA")
        let vmB = leaf("vmB")
        let composite = try! CompositeVM<ComponentVM>.builder()
            .name("c")
            .withNullServices()
            .children { [vmA] }
            .build()
        try composite.construct()

        XCTAssertFalse(composite.canSelectComponent(vmB))
        XCTAssertThrowsError(try composite.selectComponent(vmB)) { error in
            XCTAssertTrue(
                error is CompositeMembershipError,
                "expected CompositeMembershipError, got \(error)"
            )
        }
    }

    /// COMP-011 — deselectComponent throws CompositeMembershipError when the
    /// argument is not the current selection; current remains unchanged.
    func testComp011DeselectComponentThrowsWhenNotCurrent() throws {
        let vmA = leaf("vmA")
        let vmB = leaf("vmB")
        let composite = try! CompositeVM<ComponentVM>.builder()
            .name("c")
            .withNullServices()
            .children { [vmA, vmB] }
            .build()
        try composite.construct()
        try composite.selectComponent(vmA)

        XCTAssertThrowsError(try composite.deselectComponent(vmB)) { error in
            XCTAssertTrue(
                error is CompositeMembershipError,
                "expected CompositeMembershipError, got \(error)"
            )
        }
        XCTAssertTrue(composite.current === vmA, "current must remain vmA")
    }

    /// A Constructed composite holding the Constructed `vm`, armed so that it
    /// reaches Destructed after the next status read.
    private func armedScenario() throws -> (CompositeVM<DestructAfterStatusRead>, DestructAfterStatusRead) {
        let vm = DestructAfterStatusRead("vm")
        let composite = try CompositeVM<DestructAfterStatusRead>.builder()
            .name("c")
            .withNullServices()
            .children { [vm] }
            .build()
        try composite.construct()
        XCTAssertEqual(vm.status, .constructed)
        vm.arm()
        return (composite, vm)
    }

    /// #1220 — `selectComponent` checks Constructed again at its commit: a
    /// destruct after the entry check makes the call throw and change nothing.
    func testSelectComponentRefusesAChildDestructedAfterTheEntryCheck() throws {
        let (composite, vm) = try armedScenario()

        XCTAssertThrowsError(try composite.selectComponent(vm)) { error in
            XCTAssertTrue(
                error is CompositeMembershipError,
                "expected CompositeMembershipError, got \(error)"
            )
        }

        XCTAssertEqual(vm.status, .destructed, "the seam destructed vm before the commit")
        XCTAssertNil(composite.current)
        XCTAssertFalse(vm.isCurrent)
    }

    /// #1220 — `selectChild` (the child `select` path) checks Constructed
    /// again at its commit, and stays a silent no-op.
    func testSelectChildIgnoresAChildDestructedAfterTheEntryCheck() throws {
        let (composite, vm) = try armedScenario()

        composite.selectChild(vm)

        XCTAssertEqual(vm.status, .destructed, "the seam destructed vm before the commit")
        XCTAssertNil(composite.current)
        XCTAssertFalse(vm.isCurrent)
    }

    /// #1220 — the commit's Constructed check does not refuse a valid
    /// selection.
    func testSelectComponentSelectsAConstructedMember() throws {
        let vm = DestructAfterStatusRead("vm")
        let composite = try CompositeVM<DestructAfterStatusRead>.builder()
            .name("c")
            .withNullServices()
            .children { [vm] }
            .build()
        try composite.construct()

        try composite.selectComponent(vm)

        XCTAssertTrue(composite.current === vm)
        XCTAssertTrue(vm.isCurrent)
        XCTAssertEqual(vm.status, .constructed)
    }

    /// #1220 — an `asyncSelection` delivery of `selectComponent` checks
    /// Constructed again at its commit. A child destructed after the call and
    /// before the delivery is not selected, and the delivery does nothing.
    func testAsyncSelectComponentDeliveryDropsAChildDestructedAfterTheCall() throws {
        let dispatcher = ManualDispatcher()
        let vm = try ComponentVM.builder()
            .name("vm")
            .services(hub: NullMessageHub.INSTANCE, dispatcher: dispatcher)
            .build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("c")
            .services(hub: NullMessageHub.INSTANCE, dispatcher: dispatcher)
            .asyncSelection(true)
            .children { [vm] }
            .build()
        try composite.construct()
        dispatcher.flushForeground()

        try composite.selectComponent(vm)
        XCTAssertNil(composite.current, "the selection waits for the delivery")
        try vm.destruct()
        dispatcher.flushForeground()

        XCTAssertEqual(vm.status, .destructed)
        XCTAssertNil(composite.current, "the delivery checks Constructed again")
        XCTAssertFalse(vm.isCurrent)
    }
}
