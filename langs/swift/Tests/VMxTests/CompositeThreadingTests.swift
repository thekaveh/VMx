//
// CompositeThreadingTests.swift — composite foreground-dispatch + async-selection.
//
// Claimed IDs: COMP-006, COMP-009, COMP-010.
//
// Uses the Task-7 `ManualDispatcher` (Sources/VMx/Services/ManualScheduler.swift)
// to assert deferral deterministically: zero deliveries before
// `flushForeground()`, one (or more) after.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
import Combine
import Foundation
@testable import VMx

final class CompositeThreadingTests: XCTestCase {

    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    // ── COMP-006 ─────────────────────────────────────────────────────────────

    /// COMP-006 — IsCurrent change on the previously-Current child dispatches on
    /// foreground: with `ManualDispatcher`, `vmA._setIsCurrent(false)` is
    /// buffered after `selectChild(vmB)` and only delivered once
    /// `flushForeground()` is called. With `ImmediateDispatcher` / `NullDispatcher`
    /// the `scheduleForeground` call is synchronous, so existing tests are unaffected.
    func testCOMP006PreviousChildIsCurrentDispatchedOnForeground() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let vmA = try ComponentVM.builder()
            .name("vmA")
            .services(hub: hub, dispatcher: dispatcher)
            .build()
        let vmB = try ComponentVM.builder()
            .name("vmB")
            .services(hub: hub, dispatcher: dispatcher)
            .build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub, dispatcher: dispatcher)
            .children { [vmA, vmB] }
            .build()
        try composite.construct()

        // Make vmA current. No previous child → no scheduleForeground;
        // vmA._setIsCurrent(true) runs synchronously.
        composite.selectChild(vmA)
        XCTAssertTrue(vmA.isCurrent)

        // Subscribe to vmA's propertyChanged BEFORE triggering the deselection.
        var isCurrentChanges: [Bool] = []
        vmA.propertyChanged.sink { propName in
            if propName == "isCurrent" { isCurrentChanges.append(vmA.isCurrent) }
        }
        .store(in: &cancellables)

        // Change current to vmB — schedules vmA._setIsCurrent(false) on foreground.
        composite.selectChild(vmB)

        // Before flush: buffered (zero deliveries on vmA.propertyChanged).
        XCTAssertEqual(
            isCurrentChanges.count, 0,
            "isCurrent emission on previously-current child must be buffered until foreground flush"
        )
        XCTAssertTrue(vmA.isCurrent, "vmA.isCurrent not yet flipped before flush")
        XCTAssertTrue(composite.current === vmB, "composite.current already points to vmB")

        // Advance the foreground scheduler — delivers vmA._setIsCurrent(false).
        dispatcher.flushForeground()

        XCTAssertEqual(isCurrentChanges.count, 1, "exactly one isCurrent emission after flush")
        XCTAssertEqual(isCurrentChanges.first, false)
        XCTAssertFalse(vmA.isCurrent)
    }

    // ── COMP-009 ─────────────────────────────────────────────────────────────

    /// COMP-009 — Current setter raises when assigned a non-child. In Swift the
    /// catchable path is `setCurrent(_:)` which throws `CompositeMembershipError`
    /// (VMX-026 / ADR-0053); the `current` property setter traps via
    /// `preconditionFailure` because Swift setters cannot be `throws`.
    func testCOMP009SetCurrentThrowsOnNonChild() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let vmA = try ComponentVM.builder()
            .name("vmA")
            .services(hub: hub, dispatcher: dispatcher)
            .build()
        let vmB = try ComponentVM.builder()
            .name("vmB")
            .services(hub: hub, dispatcher: dispatcher)
            .build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub, dispatcher: dispatcher)
            .children { [vmA] }
            .build()
        try composite.construct()

        // vmB is not a child — setCurrent(_:) must throw CompositeMembershipError.
        XCTAssertThrowsError(try composite.setCurrent(vmB)) { error in
            XCTAssertTrue(
                error is CompositeMembershipError,
                "expected CompositeMembershipError, got \(error)"
            )
        }
        // Current slot must remain unchanged.
        XCTAssertNil(composite.current, "a failed setCurrent must not change the current slot")
    }

    // ── COMP-010 ─────────────────────────────────────────────────────────────

    /// COMP-010 — AsyncSelection defers the Current change to the foreground
    /// scheduler: with `asyncSelection(true)` and `ManualDispatcher`,
    /// `selectChild` does NOT change `current` synchronously; only after
    /// `flushForeground()` is called.
    func testCOMP010AsyncSelectionDefersCurrentChange() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let vmA = try ComponentVM.builder()
            .name("vmA")
            .services(hub: hub, dispatcher: dispatcher)
            .build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub, dispatcher: dispatcher)
            .asyncSelection(true)
            .children { [vmA] }
            .build()
        try composite.construct()

        composite.selectChild(vmA)

        // With asyncSelection the current change is deferred — not synchronous.
        XCTAssertNil(
            composite.current,
            "current must not change synchronously with asyncSelection(true)"
        )
        XCTAssertFalse(vmA.isCurrent)

        // Advancing the foreground scheduler completes the deferred dispatch.
        dispatcher.flushForeground()

        XCTAssertTrue(composite.current === vmA, "current must be vmA after foreground flush")
        XCTAssertTrue(vmA.isCurrent)
    }

    /// COMP-010 (TOCTOU) — if the child is removed between `selectChild` and
    /// `flushForeground`, the deferred selection is silently dropped, upholding
    /// the spec/06 §3 invariant that a non-null `current` is always a member.
    func testCOMP010AsyncSelectionDropsRemovedChild() throws {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let vmA = try ComponentVM.builder()
            .name("vmA")
            .services(hub: hub, dispatcher: dispatcher)
            .build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .services(hub: hub, dispatcher: dispatcher)
            .asyncSelection(true)
            .children { [vmA] }
            .build()
        try composite.construct()

        composite.selectChild(vmA)    // deferred onto foreground
        _ = composite.remove(vmA)     // removed before dispatch fires

        dispatcher.flushForeground()  // TOCTOU guard drops the stale selection

        XCTAssertNil(composite.current, "deferred selection must be dropped if child was removed")
        XCTAssertFalse(vmA.isCurrent)
    }

    func testConcurrentCurrentAssignmentsLeaveOneCurrentFlag() throws {
        let hub = MessageHub()
        let first = try ComponentVM.builder().name("first")
            .services(hub: hub, dispatcher: NullDispatcher.INSTANCE).build()
        let second = try ComponentVM.builder().name("second")
            .services(hub: hub, dispatcher: NullDispatcher.INSTANCE).build()
        let composite = try CompositeVM<ComponentVM>.builder().name("composite")
            .services(hub: hub, dispatcher: NullDispatcher.INSTANCE)
            .children { [first, second] }.build()
        let entered = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        let firstDone = DispatchSemaphore(value: 0)
        let secondDone = DispatchSemaphore(value: 0)
        first.propertyChanged.sink { propertyName in
            if propertyName == "isCurrent", first.isCurrent {
                entered.signal()
                release.wait()
            }
        }.store(in: &cancellables)

        DispatchQueue.global().async {
            composite.current = first
            firstDone.signal()
        }
        XCTAssertEqual(entered.wait(timeout: .now() + 2), .success)
        DispatchQueue.global().async {
            composite.current = second
            secondDone.signal()
        }
        XCTAssertEqual(secondDone.wait(timeout: .now() + 0.05), .timedOut)
        release.signal()
        XCTAssertEqual(firstDone.wait(timeout: .now() + 2), .success)
        XCTAssertEqual(secondDone.wait(timeout: .now() + 2), .success)

        XCTAssertTrue(composite.current === second)
        XCTAssertFalse(first.isCurrent)
        XCTAssertTrue(second.isCurrent)
    }

    func testOpposingCurrentCallbacksAcrossCompositesDoNotDeadlock() throws {
        let leftChild = try ComponentVM.builder().name("left-child")
            .withNullServices().build()
        let rightChild = try ComponentVM.builder().name("right-child")
            .withNullServices().build()
        var left: CompositeVM<ComponentVM>!
        var right: CompositeVM<ComponentVM>!
        left = try CompositeVM<ComponentVM>.builder().name("left")
            .withNullServices().children { [leftChild] }
            .onCurrentChanged { _ in right.selectChild(rightChild) }.build()
        right = try CompositeVM<ComponentVM>.builder().name("right")
            .withNullServices().children { [rightChild] }
            .onCurrentChanged { _ in left.selectChild(leftChild) }.build()
        try left.construct()
        try right.construct()

        let start = DispatchSemaphore(value: 0)
        let done = DispatchGroup()
        done.enter()
        DispatchQueue.global().async {
            start.wait()
            left.selectChild(leftChild)
            done.leave()
        }
        done.enter()
        DispatchQueue.global().async {
            start.wait()
            right.selectChild(rightChild)
            done.leave()
        }
        start.signal()
        start.signal()

        XCTAssertEqual(done.wait(timeout: .now() + 2), .success)
        XCTAssertTrue(left.current === leftChild)
        XCTAssertTrue(right.current === rightChild)
    }
}
