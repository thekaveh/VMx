import Combine
import XCTest
@testable import VMx

private struct HubFormModel: Equatable {
    let value: String
}

final class FormVMSetModelHubPublicationTests: XCTestCase {
    /// FORM-030 — unequal assignment publishes one settled model hub message.
    func testForm030_setModelPublishesOneSettledHubMessage() async throws {
        var trace: [String] = []
        let hub = MessageHub()
        let form = FormVM(
            initial: HubFormModel(value: ""),
            persister: { _ in },
            hub: hub,
            strict: true,
            snapshotter: { $0 },
            validators: ["value": { model in
                trace.append("validate")
                return model.value.isEmpty ? "required" : nil
            }]
        )
        trace.removeAll()

        let errorsCancellable = form.errorsChanged.sink { _ in trace.append("errors") }
        let commandCancellable = form.approveCommand.canExecuteChanged.sink {
            trace.append("can_execute")
        }
        var observed: [(String, Bool, Bool)] = []
        var statesAfterNestedReturn: [String] = []
        var reentered = false
        let hubCancellable = hub.messages.sink { message in
            guard let changed = message as? PropertyChangedMessage,
                  changed.sender === form,
                  changed.propertyName == "model" else { return }
            observed.append((form.model.value, form.isValid, form.approveCommand.canExecute()))
            trace.append("model")
            if !reentered {
                reentered = true
                form.setModel(HubFormModel(value: "nested"))
                statesAfterNestedReturn.append(form.model.value)
            }
        }

        form.setModel(HubFormModel(value: "outer"))

        XCTAssertEqual(observed.map(\.0), ["outer", "nested"])
        XCTAssertEqual(observed.map(\.1), [true, true])
        XCTAssertEqual(observed.map(\.2), [true, true])
        XCTAssertEqual(statesAfterNestedReturn, ["nested"])
        XCTAssertEqual(
            trace,
            ["validate", "errors", "can_execute", "model", "validate", "model"]
        )

        let retained = form.model
        let traceBeforeEqual = trace.count
        form.setModel(HubFormModel(value: "nested"))
        XCTAssertEqual(form.model, retained)
        XCTAssertEqual(trace.count, traceBeforeEqual)

        form.dispose()
        let traceAfterDispose = trace.count
        form.setModel(HubFormModel(value: "late"))
        XCTAssertEqual(form.model, retained)
        XCTAssertEqual(trace.count, traceAfterDispose)

        let nullHubForm = FormVM(
            initial: HubFormModel(value: "initial"),
            persister: { _ in },
            snapshotter: { $0 }
        )
        nullHubForm.setModel(HubFormModel(value: "changed"))
        XCTAssertEqual(nullHubForm.model.value, "changed")

        let denyHub = MessageHub()
        var denyMessages: [any Message] = []
        let denyCancellable = denyHub.messages.sink { denyMessages.append($0) }
        let denyForm = FormVM(
            initial: HubFormModel(value: "initial"),
            persister: { _ in },
            hub: denyHub,
            snapshotter: { $0 }
        )
        denyForm.setModel(HubFormModel(value: "changed"))
        denyMessages.removeAll()
        denyForm.denyCommand.execute()
        XCTAssertEqual(denyMessages.count, 2)
        XCTAssertTrue(denyMessages[0] is FormRevertedMessage)
        XCTAssertEqual((denyMessages[1] as? PropertyChangedMessage)?.propertyName, "model")

        let resetHub = MessageHub()
        var resetMessages: [any Message] = []
        let resetCancellable = resetHub.messages.sink { resetMessages.append($0) }
        let resetForm = FormVM(
            initial: HubFormModel(value: "initial"),
            persister: { _ in },
            hub: resetHub,
            snapshotter: { $0 },
            resetOnApproved: { _ in HubFormModel(value: "reset") }
        )
        resetForm.setModel(HubFormModel(value: "saved"))
        resetMessages.removeAll()

        try await resetForm.approveAsync()

        XCTAssertEqual(resetForm.model.value, "reset")
        XCTAssertTrue(resetMessages.compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.propertyName == "model" }.isEmpty)

        withExtendedLifetime([
            errorsCancellable,
            commandCancellable,
            hubCancellable,
            denyCancellable,
            resetCancellable,
        ]) {}
    }
}
