//
// FormVMTests.swift — FORM-001/002/003 conformance tests for FormVM<Model>.
//
// See spec/20-form-vm.md §1-4 and ADR-0048.
//

import XCTest
@testable import VMx

// MARK: - Test model

private struct TestModel: Equatable {
    var name: String
    var value: Int
}

// MARK: - Test cases

final class FormVMTests: XCTestCase {

    // ── FORM-001 ──────────────────────────────────────────────────────────────

    /// FORM-001 — Snapshot captured at construct; model == snapshot; isDirty == false.
    func testForm001_snapshotCapturedAtConstruct() {
        let initial = TestModel(name: "Alice", value: 1)
        let sut = FormVM(
            initial: initial,
            persister: { _ in }
        )

        XCTAssertEqual(sut.model, initial, "model should equal initial at construction")
        XCTAssertEqual(sut.snapshot, initial, "snapshot should equal initial at construction")
        XCTAssertFalse(sut.isDirty, "isDirty should be false at construction")
    }

    // ── FORM-002 ──────────────────────────────────────────────────────────────

    /// FORM-002 — Model mutation reflected in isDirty; snapshot unchanged.
    func testForm002_setModelMakesFormDirty() {
        let initial = TestModel(name: "Alice", value: 1)
        let sut = FormVM(
            initial: initial,
            persister: { _ in }
        )

        sut.setModel(TestModel(name: "Bob", value: 2))

        XCTAssertTrue(sut.isDirty, "isDirty should be true after setModel with a different value")
        XCTAssertEqual(sut.snapshot, initial, "snapshot should remain unchanged after setModel")
        XCTAssertEqual(sut.model, TestModel(name: "Bob", value: 2), "model should reflect the new value")
    }

    // ── FORM-003 ──────────────────────────────────────────────────────────────

    /// FORM-003 — Structural (in)equality drives isDirty: value-equal → clean; different → dirty.
    func testForm003_structuralInequalityDrivesIsDirty() {
        let initial = TestModel(name: "Alice", value: 1)
        let sut = FormVM(
            initial: initial,
            persister: { _ in }
        )

        // Setting a value-equal model leaves isDirty == false.
        sut.setModel(TestModel(name: "Alice", value: 1))
        XCTAssertFalse(sut.isDirty, "isDirty should be false when model is value-equal to snapshot")

        // Setting a structurally different model → isDirty == true.
        sut.setModel(TestModel(name: "Alice", value: 99))
        XCTAssertTrue(sut.isDirty, "isDirty should be true when model differs from snapshot")
    }
}
