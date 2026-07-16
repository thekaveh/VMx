//
// DialogReentrancyTests — DIA-006, DIA-007, DIA-008: reentrancy/cancellation/command integration.
//
// See spec/19-dialogs.md §6/§7/§8 and ADR-0056.
// Ports langs/typescript/tests/conformance/dia-001-to-008-dialog-service.test.ts (DIA-006..008).
//
// DIA-006 and DIA-007 helpers are test-only DialogService implementations.
// Mutable state captured across async Tasks is held in reference-type boxes.
// Async Tasks are drained via XCTestExpectation + fulfillment(of:timeout:).
//
import Foundation
import XCTest
@testable import VMx

// MARK: - DIA-006 helper: QueuingDialogService
// Serialises concurrent confirm calls via a CheckedContinuation queue; both eventually resolve.

private final class QueuingDialogService: DialogService {
    private var queue: [CheckedContinuation<Bool, Never>] = []
    private let lock = NSLock()
    /// Called synchronously (before suspension) each time a confirm call is enqueued.
    var onEnqueued: (() -> Void)?

    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? { nil }
    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? { nil }
    func notify(_ message: String, title: String?, severity: NotificationSeverity) async {}

    func confirm(_ message: String, title: String?) async -> Bool {
        await withCheckedContinuation { continuation in
            lock.lock()
            queue.append(continuation)
            lock.unlock()
            onEnqueued?()
        }
    }

    /// Resolves the oldest pending confirm with `result`.
    func completeNext(_ result: Bool) {
        lock.lock()
        guard !queue.isEmpty else { lock.unlock(); return }
        let cont = queue.removeFirst()
        lock.unlock()
        cont.resume(returning: result)
    }
}

// MARK: - DIA-006 helper: RejectingDialogService
// When a confirm is already active, a reentrant call returns false immediately without suspending.

private final class RejectingDialogService: DialogService {
    private var activeContinuation: CheckedContinuation<Bool, Never>? = nil
    private let lock = NSLock()
    /// Called synchronously (before suspension) when the first confirm becomes active.
    var onActivated: (() -> Void)?

    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? { nil }
    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? { nil }
    func notify(_ message: String, title: String?, severity: NotificationSeverity) async {}

    func confirm(_ message: String, title: String?) async -> Bool {
        let hasActive = lock.withLock { activeContinuation != nil }
        if hasActive {
            // Reentrant call — reject immediately without suspending.
            return false
        }
        return await withCheckedContinuation { continuation in
            lock.lock()
            activeContinuation = continuation
            lock.unlock()
            onActivated?()
        }
    }

    /// Resolves the active (first) confirm with `result`.
    func completeActive(_ result: Bool) {
        lock.lock()
        let cont = activeContinuation
        activeContinuation = nil
        lock.unlock()
        cont?.resume(returning: result)
    }
}

// MARK: - DIA-007 helper: CancellationAwareDialogService
// Returns safe defaults (nil / false) when cancelled, without throwing.

private final class CancellationAwareDialogService: DialogService {
    var cancelled = false

    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? {
        cancelled ? nil : "/some/path"
    }

    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? {
        nil
    }

    func confirm(_ message: String, title: String?) async -> Bool {
        cancelled ? false : true
    }

    func notify(_ message: String, title: String?, severity: NotificationSeverity) async {}
}

// MARK: - DIA-008 helper: ControllableDialogService
// Returns nextResult for every confirm call; used to drive command-integration assertions.

private final class ControllableDialogService: DialogService {
    var nextResult = false

    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? { nil }
    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? { nil }
    func notify(_ message: String, title: String?, severity: NotificationSeverity) async {}

    func confirm(_ message: String, title: String?) async -> Bool { nextResult }
}

// MARK: - Reference-type result boxes

/// Optional bool holder — distinguishes "not yet set" from a false result.
private final class OptBoolBox { var value: Bool? = nil }

/// Bool holder — initial value false; set to true when inner command executes.
private final class BoolBox { var value = false }

// MARK: - Tests

final class DialogReentrancyTests: XCTestCase {

    // MARK: - DIA-006 (queuing implementation)

    /// DIA-006 — Queueing implementation: both concurrent confirm calls resolve with valid values.
    func testDia006QueuingBothCallsResolveWithValidValues() async {
        let dialog = QueuingDialogService()
        let bothEnqueued = expectation(description: "DIA-006 queuing: both confirms enqueued")
        bothEnqueued.expectedFulfillmentCount = 2
        dialog.onEnqueued = { bothEnqueued.fulfill() }

        let r1 = OptBoolBox()
        let r2 = OptBoolBox()
        let bothResolved = expectation(description: "DIA-006 queuing: both confirms resolved")
        bothResolved.expectedFulfillmentCount = 2

        Task { r1.value = await dialog.confirm("first", title: nil); bothResolved.fulfill() }
        Task { r2.value = await dialog.confirm("second", title: nil); bothResolved.fulfill() }

        await fulfillment(of: [bothEnqueued], timeout: 1.0)
        dialog.completeNext(true)
        dialog.completeNext(false)

        await fulfillment(of: [bothResolved], timeout: 1.0)
        // The queueing impl drains continuations in ENQUEUE order, which is not
        // contractually tied to which Task starts first — so assert the
        // outcome set (both resolved; one true, one false) rather than pinning a
        // fixed r1/r2 assignment, which would flake on scheduler reordering.
        XCTAssertNotNil(r1.value, "DIA-006 queuing: first confirm must resolve")
        XCTAssertNotNil(r2.value, "DIA-006 queuing: second confirm must resolve")
        XCTAssertNotEqual(r1.value, r2.value,
                          "DIA-006 queuing: the two queued confirms resolve to different booleans")
    }

    // MARK: - DIA-006 (rejecting implementation)

    /// DIA-006 — Rejecting implementation: reentrant confirm call resolves immediately with false.
    func testDia006RejectingReentrantCallReturnsFalseImmediately() async {
        let dialog = RejectingDialogService()
        let firstActivated = expectation(description: "DIA-006 rejecting: first confirm active")
        dialog.onActivated = { firstActivated.fulfill() }

        let rA = OptBoolBox()
        let rB = OptBoolBox()
        let aResolved = expectation(description: "DIA-006 rejecting: first confirm resolved")
        let bResolved = expectation(description: "DIA-006 rejecting: reentrant confirm resolved")

        Task { rA.value = await dialog.confirm("active", title: nil); aResolved.fulfill() }

        // Wait until the first confirm has enqueued its continuation (active state set).
        await fulfillment(of: [firstActivated], timeout: 1.0)

        // Second call while first is active — must return false immediately.
        Task { rB.value = await dialog.confirm("reentrant", title: nil); bResolved.fulfill() }
        await fulfillment(of: [bResolved], timeout: 1.0)
        XCTAssertEqual(rB.value, false,
                       "DIA-006 rejecting: reentrant confirm must resolve false without suspending")

        // Complete the first confirm — no exception path (non-throwing protocol).
        dialog.completeActive(true)
        await fulfillment(of: [aResolved], timeout: 1.0)
        XCTAssertEqual(rA.value, true,
                       "DIA-006 rejecting: active confirm must resolve true after completeActive")
    }

    // MARK: - DIA-007

    /// DIA-007 — Cancelled pickFileToOpen returns nil without throwing.
    func testDia007CancelledPickFileToOpenReturnsNil() async {
        let svc = CancellationAwareDialogService()
        svc.cancelled = true
        // DialogService.pickFileToOpen is async (non-throwing) — cancellation cannot throw.
        let path = await svc.pickFileToOpen()
        XCTAssertNil(path,
                     "DIA-007: cancelled pickFileToOpen must return nil without throwing")
    }

    /// DIA-007 — Cancelled confirm returns false without throwing.
    func testDia007CancelledConfirmReturnsFalse() async {
        let svc = CancellationAwareDialogService()
        svc.cancelled = true
        // DialogService.confirm is async (non-throwing) — cancellation cannot throw.
        let confirmed = await svc.confirm("msg")
        XCTAssertFalse(confirmed,
                       "DIA-007: cancelled confirm must return false without throwing")
    }

    // MARK: - DIA-008

    /// DIA-008 — ConfirmationDecoratorCommand with dialogService.confirm gates inner on result.
    ///
    /// Asserts both the bare `confirm(_:_:)` lambda form AND `confirmWithDialogService`.
    func testDia008ConfirmationDecoratorCommandIntegration() async throws {
        let dialog = ControllableDialogService()
        let innerRan = BoolBox()

        let inner = RelayCommand.builder()
            .task { innerRan.value = true }
            .build()

        // ── Lambda form: confirm(inner, { await dialog.confirm(...) }) ──────────

        let safeCmd = confirm(inner, { await dialog.confirm("Proceed?", title: nil) })
        XCTAssertTrue(safeCmd.canExecute(),
                      "DIA-008: canExecute must delegate to inner (lambda form)")

        // dialog returns false → inner must NOT execute
        dialog.nextResult = false
        try await safeCmd.executeAsync()
        XCTAssertFalse(innerRan.value,
                       "DIA-008 lambda: inner must not run when confirm returns false")

        // dialog returns true → inner MUST execute
        dialog.nextResult = true
        try await safeCmd.executeAsync()
        XCTAssertTrue(innerRan.value,
                      "DIA-008 lambda: inner must run when confirm returns true")

        // ── confirmWithDialogService overload ────────────────────────────────

        let inner2Ran = BoolBox()
        let inner2 = RelayCommand.builder()
            .task { inner2Ran.value = true }
            .build()

        let overloadCmd = confirmWithDialogService(inner2, dialog, "Proceed?")
        XCTAssertTrue(overloadCmd.canExecute(),
                      "DIA-008: canExecute must delegate to inner (overload form)")

        // The overload always constructs a ConfirmationDecoratorCommand; downcast is safe.
        let overload = overloadCmd as! ConfirmationDecoratorCommand

        dialog.nextResult = false
        try await overload.executeAsync()
        XCTAssertFalse(inner2Ran.value,
                       "DIA-008 overload: inner must not run when confirm returns false")

        dialog.nextResult = true
        try await overload.executeAsync()
        XCTAssertTrue(inner2Ran.value,
                      "DIA-008 overload: inner must run when confirm returns true")
    }
}
