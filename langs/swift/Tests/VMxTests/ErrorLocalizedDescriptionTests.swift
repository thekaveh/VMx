//
// Error `localizedDescription` tests (#1596).
//
// Foundation fills `localizedDescription` from `LocalizedError.errorDescription`
// only. Each public Swift error type that has a `description` therefore also
// conforms to `LocalizedError`, so the text that users see matches `description`.
//
// The BLD-002 test checks the message clause: the standard message names the
// missing builder field.
//
import XCTest
@testable import VMx

final class ErrorLocalizedDescriptionTests: XCTestCase {

    /// BLD-002 — the missing-field error's `localizedDescription` names the
    /// missing field. `description` and `missingField` keep their values.
    func testBld002LocalizedDescriptionNamesMissingField() {
        XCTAssertThrowsError(
            try ComponentVMBuilder()
                .withNullServices()
                .build()
        ) { err in
            guard let e = err as? BuilderValidationError else {
                XCTFail("expected BuilderValidationError, got \(err)")
                return
            }
            XCTAssertEqual(e.missingField, "name")
            XCTAssertEqual(
                e.description,
                "Required field 'name' was not set on the builder."
            )
            XCTAssertEqual(err.localizedDescription, e.description)
            XCTAssertTrue(
                err.localizedDescription.contains("'name'"),
                "localizedDescription was: \(err.localizedDescription)"
            )
        }
    }

    func testStatusTransitionErrorLocalizedDescriptionMatchesDescription() {
        assertLocalizedDescriptionMatchesDescription(
            StatusTransitionError(currentStatus: .destructed, attemptedOperation: "construct")
        )
    }

    func testCompositeMembershipErrorLocalizedDescriptionMatchesDescription() {
        assertLocalizedDescriptionMatchesDescription(
            CompositeMembershipError(memberName: "a", compositeName: "c")
        )
    }

    func testContainerRollbackErrorLocalizedDescriptionMatchesDescription() {
        assertLocalizedDescriptionMatchesDescription(
            ContainerRollbackError(
                originalError: BuilderValidationError(missingField: "x"),
                compensationError: BuilderValidationError(missingField: "y")
            )
        )
    }

    func testChildTransitionErrorLocalizedDescriptionMatchesDescription() {
        assertLocalizedDescriptionMatchesDescription(
            ChildTransitionError(childName: "child", reason: "did not reach Constructed")
        )
    }

    func testMessageHubOverflowErrorLocalizedDescriptionMatchesDescription() {
        assertLocalizedDescriptionMatchesDescription(
            MessageHubOverflowError(limit: 3, messageTypes: ["A", "B"])
        )
    }

    func testObservableDictionaryErrorLocalizedDescriptionMatchesDescription() {
        assertLocalizedDescriptionMatchesDescription(
            ObservableDictionaryError.duplicateKey(key1: "a", key2: "b")
        )
    }

    private func assertLocalizedDescriptionMatchesDescription<E: Error & CustomStringConvertible>(
        _ error: E,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let wrapped: Error = error
        XCTAssertEqual(
            wrapped.localizedDescription,
            error.description,
            file: file,
            line: line
        )
    }
}
