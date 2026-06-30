//
// FormVMBuilderTests.swift — FORM-009/010/011/012/013/014 conformance tests.
//
// FORM-009: strict canExecute gating + canExecuteChanged on dirty transition.
// FORM-010: confirm-guarded deny via ConfirmationDecoratorCommand.
// FORM-011: builder validation — missing initial / persister throw BuilderValidationError.
// FORM-012: repeated build() → distinct but equivalent FormVM instances.
// FORM-013: builder defaults — NullMessageHub, strict false, identity snapshotter.
// FORM-014: disposed form is inert — approve never invokes persister, deny does not revert.
//
// See spec/20-form-vm.md §8-9, spec/10-builders.md §3, and ADR-0035 §2 FV1/FV2.
//

import Combine
import XCTest
@testable import VMx

// MARK: - Shared model

private struct TestModel: Equatable {
    var name: String
    var value: Int
}

// MARK: - Reference-type recorder (required for @escaping / async capture)

private final class PersistRecorder {
    var calls: [TestModel] = []
    func persister(_ model: TestModel) async throws {
        calls.append(model)
    }
}

// MARK: - Test cases

final class FormVMBuilderTests: XCTestCase {

    // ── FORM-009 ──────────────────────────────────────────────────────────────

    /// FORM-009 — strict mode: approveCommand.canExecute is false when isDirty == false,
    /// true when dirty; canExecuteChanged fires on the isDirty transition.
    func testForm009_strictModeCanExecuteGating() {
        let initial = TestModel(name: "Alice", value: 1)

        // Strict form: canExecute false when clean.
        let sut = FormVM(initial: initial, persister: { (_: TestModel) in }, strict: true)
        XCTAssertFalse(sut.isDirty, "form should be clean at construction")
        XCTAssertFalse(sut.approveCommand.canExecute(),
                       "strict form: canExecute must be false when isDirty == false")

        // Subscribe to canExecuteChanged before mutating.
        var changed = 0
        var cancellables = Set<AnyCancellable>()
        sut.approveCommand.canExecuteChanged
            .sink { changed += 1 }
            .store(in: &cancellables)

        sut.setModel(TestModel(name: "Bob", value: 2))
        XCTAssertTrue(sut.isDirty, "form should be dirty after setModel")
        XCTAssertTrue(sut.approveCommand.canExecute(),
                      "strict form: canExecute must be true when isDirty == true")
        XCTAssertEqual(changed, 1, "canExecuteChanged must fire exactly once on the clean→dirty transition")

        // Non-strict (default): approveCommand.canExecute is always true.
        let nonStrict = FormVM(initial: initial, persister: { (_: TestModel) in })
        XCTAssertTrue(nonStrict.approveCommand.canExecute(),
                      "non-strict form: canExecute must be true even when not dirty")

        cancellables.removeAll()
        sut.dispose()
        nonStrict.dispose()
    }

    // ── FORM-010 ──────────────────────────────────────────────────────────────

    /// FORM-010 — confirm-guarded deny: ConfirmationDecoratorCommand over denyCommand
    /// blocks revert when confirm returns false; allows revert when confirm returns true.
    func testForm010_confirmGuardedDenyBlocksOnFalse() async throws {
        let initial = TestModel(name: "Alice", value: 1)
        let sut = FormVM(initial: initial, persister: { (_: TestModel) in })
        sut.setModel(TestModel(name: "Bob", value: 2))
        XCTAssertTrue(sut.isDirty, "form should be dirty after setModel")

        // Confirm returns false → revert is blocked.
        let guardedDeny = ConfirmationDecoratorCommand(sut.denyCommand) {
            return false
        }
        try await guardedDeny.executeAsync()

        XCTAssertTrue(sut.isDirty,
                      "form must remain dirty when confirm returns false")
        XCTAssertEqual(sut.model, TestModel(name: "Bob", value: 2),
                       "model must not revert when confirm returns false")

        // Confirm returns true → revert proceeds.
        let confirmingDeny = ConfirmationDecoratorCommand(sut.denyCommand) {
            return true
        }
        try await confirmingDeny.executeAsync()

        XCTAssertFalse(sut.isDirty,
                       "form must be clean after confirm-guarded deny with true")
        XCTAssertEqual(sut.model, initial,
                       "model must revert to snapshot after confirm-guarded deny with true")

        sut.dispose()
    }

    // ── FORM-011 ──────────────────────────────────────────────────────────────

    /// FORM-011 — builder validation: missing initial or persister throws
    /// BuilderValidationError naming the missing field in order (initial → persister).
    func testForm011_builderValidationRequiredFields() {
        let noopPersister: (TestModel) async throws -> Void = { _ in }
        let initial = TestModel(name: "Alice", value: 1)

        // Missing initial → BuilderValidationError("initial").
        let missingInitial = FormVM<TestModel>.builder().persister(noopPersister)
        XCTAssertThrowsError(try missingInitial.build()) { error in
            guard let bve = error as? BuilderValidationError else {
                return XCTFail("expected BuilderValidationError, got \(type(of: error))")
            }
            XCTAssertEqual(bve.missingField, "initial",
                           "BuilderValidationError must name 'initial' when initial is missing")
        }

        // Missing persister → BuilderValidationError("persister").
        let missingPersister = FormVM<TestModel>.builder().initial(initial)
        XCTAssertThrowsError(try missingPersister.build()) { error in
            guard let bve = error as? BuilderValidationError else {
                return XCTFail("expected BuilderValidationError, got \(type(of: error))")
            }
            XCTAssertEqual(bve.missingField, "persister",
                           "BuilderValidationError must name 'persister' when persister is missing")
        }

        // Both set → build succeeds.
        XCTAssertNoThrow(
            try FormVM<TestModel>.builder().initial(initial).persister(noopPersister).build(),
            "build() must succeed when both required fields are set"
        )

        // Setters are immutable (BLD-001): deriving b2/b3 from b1 must not mutate b1.
        // FormVMBuilder is a value type (struct), so each setter returns a copy.
        // Observable proof: b1 still throws after b2/b3 are derived from it.
        let b1 = FormVM<TestModel>.builder()
        let b2 = b1.initial(initial)
        let b3 = b2.persister(noopPersister)
        XCTAssertNil(try? b1.build(),
                     "b1 must still fail (no fields set) after b2/b3 were derived")
        XCTAssertNil(try? b2.build(),
                     "b2 must still fail (no persister) after b3 was derived")
        XCTAssertNotNil(try? b3.build(),
                        "b3 must succeed once both required fields are set")
    }

    // ── FORM-012 ──────────────────────────────────────────────────────────────

    /// FORM-012 — repeated build() calls on the same builder produce distinct
    /// (non-identical) but equivalent (same initial model/snapshot, both clean) FormVMs.
    func testForm012_repeatedBuildProducesDistinctEquivalentForms() throws {
        let initial = TestModel(name: "Alice", value: 1)
        let builder = FormVM<TestModel>.builder()
            .initial(initial)
            .persister({ (_: TestModel) in })

        let vmA = try builder.build()
        let vmB = try builder.build()

        // Distinct reference identities.
        XCTAssertFalse(vmA === vmB, "repeated build() must return distinct FormVM instances")

        // Equivalent state.
        XCTAssertEqual(vmA.model, vmB.model, "both forms must have equal model values")
        XCTAssertEqual(vmA.snapshot, vmB.snapshot, "both forms must have equal snapshot values")
        XCTAssertFalse(vmA.isDirty, "vmA must be clean immediately after build")
        XCTAssertFalse(vmB.isDirty, "vmB must be clean immediately after build")

        vmA.dispose()
        vmB.dispose()
    }

    // ── FORM-013 ──────────────────────────────────────────────────────────────

    /// FORM-013 — builder defaults: hub is NullMessageHub (no-op, does not throw);
    /// strict defaults to false (approveCommand.canExecute true when not dirty).
    func testForm013_builderDefaults() throws {
        let initial = TestModel(name: "Alice", value: 1)
        let vm = try FormVM<TestModel>.builder()
            .initial(initial)
            .persister({ (_: TestModel) in })
            .build()

        // hub default is NullMessageHub: a deny round-trip must not throw.
        vm.setModel(TestModel(name: "Bob", value: 2))
        XCTAssertTrue(vm.isDirty, "form should be dirty after setModel")
        vm.denyCommand.execute()
        XCTAssertFalse(vm.isDirty,
                       "hub default (NullMessageHub) must allow deny without crashing")

        // strict default is false: canExecute true when not dirty.
        XCTAssertTrue(vm.approveCommand.canExecute(),
                      "strict defaults to false: approveCommand.canExecute must be true when not dirty")

        // Explicit strict(true) overrides the default.
        let strictVm = try FormVM<TestModel>.builder()
            .initial(initial)
            .persister({ (_: TestModel) in })
            .strict(true)
            .build()
        XCTAssertFalse(strictVm.approveCommand.canExecute(),
                       "explicit strict(true) must gate canExecute on isDirty")

        vm.dispose()
        strictVm.dispose()
    }

    // ── FORM-014 ──────────────────────────────────────────────────────────────

    /// FORM-014 — a disposed form is inert: approveAsync never invokes the persister;
    /// denyCommand.execute does not revert the model.
    func testForm014_disposedFormIsInert() async {
        let recorder = PersistRecorder()
        let initial = TestModel(name: "Alice", value: 1)
        let sut = FormVM(initial: initial, persister: recorder.persister)

        sut.setModel(TestModel(name: "Bob", value: 2))
        XCTAssertTrue(sut.isDirty, "form should be dirty after setModel")

        sut.dispose()

        // approveAsync must be a no-op — persister must not be invoked.
        await (try? sut.approveAsync())
        XCTAssertEqual(recorder.calls.count, 0,
                       "persister must not be invoked after dispose")

        // denyCommand.execute must not revert the model.
        sut.denyCommand.execute()
        XCTAssertEqual(sut.model, TestModel(name: "Bob", value: 2),
                       "denyCommand must not revert model after dispose")

        // Dispose is idempotent.
        sut.dispose()
    }
}
