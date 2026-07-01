import XCTest
import Combine
@testable import VMx

private struct ValidationModel: Equatable {
    var name: String
    var value: Int
}

final class FormVMValidationTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// FORM-016 — field validator populates field error.
    func testFORM016FieldValidatorPopulatesFieldError() {
        let sut = FormVM(
            initial: ValidationModel(name: "", value: 1),
            persister: { _ in },
            validators: ["name": { $0.name.isEmpty ? "required" : nil }]
        )
        XCTAssertEqual(sut.fieldError("name"), "required")
    }

    /// FORM-017 — model validator populates errors.
    func testFORM017ModelValidatorPopulatesErrors() {
        let sut = FormVM(
            initial: ValidationModel(name: "x", value: -1),
            persister: { _ in },
            modelValidator: { _ in ["value": "negative"] }
        )
        XCTAssertEqual(sut.errors["value"], "negative")
    }

    /// FORM-018 — isValid reflects errors.
    func testFORM018IsValidReflectsErrors() {
        let sut = FormVM(
            initial: ValidationModel(name: "", value: 1),
            persister: { _ in },
            validators: ["name": { _ in "required" }]
        )
        XCTAssertFalse(sut.isValid)
    }

    /// FORM-019 — invalid form blocks approval.
    func testFORM019InvalidFormBlocksApproval() async throws {
        var calls = 0
        let sut = FormVM(
            initial: ValidationModel(name: "", value: 1),
            persister: { _ in calls += 1 },
            validators: ["name": { _ in "required" }]
        )
        XCTAssertFalse(sut.approveCommand.canExecute())
        try await sut.approveAsync()
        XCTAssertEqual(calls, 0)
    }

    /// FORM-020 — validation reruns after model mutation.
    func testFORM020ValidationRerunsAfterMutation() {
        let sut = FormVM(
            initial: ValidationModel(name: "", value: 1),
            persister: { _ in },
            validators: ["name": { $0.name.isEmpty ? "required" : nil }]
        )
        sut.setModel(ValidationModel(name: "ok", value: 1))
        XCTAssertTrue(sut.errors.isEmpty)
        XCTAssertTrue(sut.isValid)
    }

    /// FORM-021 — errorsChanged fires only on effective changes.
    func testFORM021ErrorsChangedFiresOnlyOnEffectiveChanges() {
        let sut = FormVM(
            initial: ValidationModel(name: "", value: 1),
            persister: { _ in },
            validators: ["name": { $0.name.isEmpty ? "required" : nil }]
        )
        var seen: [[String: String]] = []
        sut.errorsChanged.sink { seen.append($0) }.store(in: &cancellables)
        sut.setModel(ValidationModel(name: "", value: 2))
        sut.setModel(ValidationModel(name: "ok", value: 2))
        XCTAssertEqual(seen, [[:]])
    }

    /// FORM-022 — builder registers validators immutably.
    func testFORM022BuilderRegistersValidatorsImmutably() throws {
        let base = FormVM<ValidationModel>.builder()
            .initial(ValidationModel(name: "", value: 1))
            .persister { _ in }
        let withValidator = base.validator("name") { _ in "required" }
        let sut = try withValidator.build()
        XCTAssertEqual(sut.fieldError("name"), "required")
    }

    /// FORM-023 — clearing errors enables approval when other gates pass.
    func testFORM023ClearingErrorsEnablesApproval() {
        let sut = FormVM(
            initial: ValidationModel(name: "", value: 1),
            persister: { _ in },
            strict: true,
            validators: ["name": { $0.name.isEmpty ? "required" : nil }]
        )
        sut.setModel(ValidationModel(name: "ok", value: 2))
        XCTAssertTrue(sut.approveCommand.canExecute())
    }
}
