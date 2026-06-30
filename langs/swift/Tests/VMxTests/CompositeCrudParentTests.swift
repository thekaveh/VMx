//
// CompositeCrudParentTests.swift
//
// Conformance IDs: COMP-019, COMP-020, COMP-021, COMP-022, COMP-023,
//                  COMP-024, COMP-027.
// See spec/06-composite-vm.md §7 (Modeled CRUD + parent reference) and ADR-0016.
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
@testable import VMx

// ── Private test helpers ──────────────────────────────────────────────────────

/// Minimal `AnyObject` type used as the `VM` parameter in COMP-019..024.
private final class TestVM {}

/// Reference-type call recorder for `() -> Void` closures.
/// A class (not struct) avoids the "@escaping capture of 'var'" restriction
/// when the closure is stored as an @escaping parameter (HIER-014 pattern).
private final class VoidRecorder {
    var callCount = 0
    func record() { callCount += 1 }
}

/// Reference-type call recorder for closures that pass a `TestVM`.
private final class VMRecorder {
    var calls: [TestVM] = []
    func record(_ vm: TestVM) { calls.append(vm) }
}

/// Reference holder for a mutable `current` value captured by @escaping closures.
private final class CurrentHolder {
    var value: TestVM?
    init(_ v: TestVM? = nil) { value = v }
}

// ── Test class ────────────────────────────────────────────────────────────────

final class CompositeCrudParentTests: XCTestCase {

    // MARK: — Modeled CRUD (COMP-019..024)

    /// COMP-019 — CreateNewCommand invokes createNew action exactly once.
    func testCOMP019CreateNewCommandInvokesCreateNew() {
        let recorder = VoidRecorder()
        let crud = ModeledCrudCommands<TestVM>(
            current: { nil },
            createNew: { recorder.record() },
            updateCurrent: { _ in },
            deleteCurrent: { _ in }
        )
        crud.createNewCommand.execute()
        XCTAssertEqual(recorder.callCount, 1,
            "createNewCommand.execute() must invoke createNew exactly once")
        crud.dispose()
    }

    /// COMP-020 — UpdateCurrentCommand invokes updateCurrent with the current VM.
    func testCOMP020UpdateCurrentCommandInvokesUpdateWithCurrentVM() {
        let vm = TestVM()
        let holder = CurrentHolder(vm)
        let recorder = VMRecorder()
        let crud = ModeledCrudCommands<TestVM>(
            current: { holder.value },
            createNew: { },
            updateCurrent: { recorder.record($0) },
            deleteCurrent: { _ in }
        )
        crud.updateCurrentCommand.execute()
        XCTAssertEqual(recorder.calls.count, 1,
            "updateCurrent must be invoked exactly once")
        XCTAssertTrue(recorder.calls.first === vm,
            "updateCurrent must receive the current() VM")
        crud.dispose()
    }

    /// COMP-021 — UpdateCurrentCommand.canExecute() is false when current() returns nil.
    func testCOMP021UpdateCurrentCommandCanExecuteFalseWhenCurrentNil() {
        let crud = ModeledCrudCommands<TestVM>(
            current: { nil },
            createNew: { },
            updateCurrent: { _ in },
            deleteCurrent: { _ in }
        )
        XCTAssertFalse(crud.updateCurrentCommand.canExecute(),
            "updateCurrentCommand.canExecute() must be false when current() == nil")
        crud.dispose()
    }

    /// COMP-022 — DeleteCurrentCommand invokes deleteCurrent with the current VM.
    func testCOMP022DeleteCurrentCommandInvokesDeleteWithCurrentVM() {
        let vm = TestVM()
        let holder = CurrentHolder(vm)
        let recorder = VMRecorder()
        let crud = ModeledCrudCommands<TestVM>(
            current: { holder.value },
            createNew: { },
            updateCurrent: { _ in },
            deleteCurrent: { recorder.record($0) }
        )
        crud.deleteCurrentCommand.execute()
        XCTAssertEqual(recorder.calls.count, 1,
            "deleteCurrent must be invoked exactly once")
        XCTAssertTrue(recorder.calls.first === vm,
            "deleteCurrent must receive the current() VM")
        crud.dispose()
    }

    /// COMP-023 — DeleteCurrentCommand.canExecute() is false when current() returns nil.
    func testCOMP023DeleteCurrentCommandCanExecuteFalseWhenCurrentNil() {
        let crud = ModeledCrudCommands<TestVM>(
            current: { nil },
            createNew: { },
            updateCurrent: { _ in },
            deleteCurrent: { _ in }
        )
        XCTAssertFalse(crud.deleteCurrentCommand.canExecute(),
            "deleteCurrentCommand.canExecute() must be false when current() == nil")
        crud.dispose()
    }

    /// COMP-024 — DeleteCurrentCommand with confirmDelete is a ConfirmationDecoratorCommand:
    /// confirm→false records nothing; confirm→true records the VM.
    func testCOMP024DeleteCommandConfirmGate() async throws {
        let vm = TestVM()

        // confirm→false: action must NOT be invoked.
        let recorderNo = VMRecorder()
        let crudNo = ModeledCrudCommands<TestVM>(
            current: { vm },
            createNew: { },
            updateCurrent: { _ in },
            deleteCurrent: { recorderNo.record($0) },
            confirmDelete: { false }
        )
        XCTAssertTrue(crudNo.deleteCurrentCommand is ConfirmationDecoratorCommand,
            "deleteCurrentCommand must be a ConfirmationDecoratorCommand when confirmDelete is supplied")
        let decoratorNo = crudNo.deleteCurrentCommand as! ConfirmationDecoratorCommand
        try await decoratorNo.executeAsync()
        XCTAssertEqual(recorderNo.calls.count, 0,
            "confirm→false: deleteCurrent must NOT be invoked")
        crudNo.dispose()

        // confirm→true: action IS invoked with the current VM.
        let recorderYes = VMRecorder()
        let crudYes = ModeledCrudCommands<TestVM>(
            current: { vm },
            createNew: { },
            updateCurrent: { _ in },
            deleteCurrent: { recorderYes.record($0) },
            confirmDelete: { true }
        )
        let decoratorYes = crudYes.deleteCurrentCommand as! ConfirmationDecoratorCommand
        try await decoratorYes.executeAsync()
        XCTAssertEqual(recorderYes.calls.count, 1,
            "confirm→true: deleteCurrent must be invoked exactly once")
        XCTAssertTrue(recorderYes.calls.first === vm,
            "confirm→true: deleteCurrent must receive the current() VM")
        crudYes.dispose()
    }

    // MARK: — Parent reference (COMP-027)

    /// COMP-027 — Adding a child sets its parent (canSelect true + select delegates to composite);
    /// removing the child clears its parent (canSelect false, select is a no-op).
    func testCOMP027AddSetsParentRemoveClearsParent() throws {
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite")
            .withNullServices()
            .children { [] }
            .build()
        try composite.construct()

        let child = try ComponentVM.builder()
            .name("c")
            .withNullServices()
            .build()
        try child.construct()

        // Before add: no parent → not selectable.
        XCTAssertFalse(child.canSelect(),
            "child.canSelect() must be false before add (no parent)")

        // add() wires parent → selectable; select() delegates through parent.
        composite.add(child)
        XCTAssertTrue(child.canSelect(),
            "child.canSelect() must be true after add (parent set)")
        child.select()
        XCTAssertTrue(composite.current === child,
            "composite.current must be child after child.select()")
        XCTAssertTrue(child.isCurrent,
            "child.isCurrent must be true after select()")

        // Deselect first, then remove: parent cleared → not selectable; select() is a no-op.
        child.deselect()
        XCTAssertNil(composite.current,
            "composite.current must be nil after child.deselect()")

        let removed = composite.remove(child)
        XCTAssertTrue(removed,
            "composite.remove(child) must return true")
        XCTAssertFalse(child.canSelect(),
            "child.canSelect() must be false after remove (parent cleared)")
        child.select() // no-op: _parent is nil
        XCTAssertNil(composite.current,
            "composite.current must remain nil after select() with no parent")
    }
}
