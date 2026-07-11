import Combine
import XCTest
@testable import VMx

private struct DisposedComponentModel: Equatable {
    let value: Int
}

private struct DisposedFormModel: Equatable {
    let name: String
}

final class PostDisposeModeledAssignmentConformanceTests: XCTestCase {
    /// DISP-014 — Modeled assignment after disposal is inert.
    func testDISP014ModeledAssignmentAfterDisposalIsInert() throws {
        let componentHub = MessageHub()
        var equalityCalls = 0
        var hinterCalls = 0
        var callbackCalls = 0
        let initial = DisposedComponentModel(value: 1)
        let component = try ComponentVMOf<DisposedComponentModel>.builder()
            .name("component")
            .model(initial)
            .modelEquals { left, right in
                equalityCalls += 1
                return left == right
            }
            .modeledHinter { model in
                hinterCalls += 1
                return "hint:\(model.value)"
            }
            .onModelChanged { _ in callbackCalls += 1 }
            .services(hub: componentHub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        var localChanges: [String] = []
        var componentHubChanges: [String] = []
        let localCancel = component.propertyChanged.sink { localChanges.append($0) }
        let hubCancel = componentHub.messages
            .compactMap { ($0 as? PropertyChangedMessage)?.propertyName }
            .sink { componentHubChanges.append($0) }

        component.dispose()
        equalityCalls = 0
        hinterCalls = 0
        callbackCalls = 0
        localChanges.removeAll()
        componentHubChanges.removeAll()
        let lateComponentCompletion = {
            component.model = DisposedComponentModel(value: 2)
        }

        lateComponentCompletion()

        XCTAssertEqual(component.model, initial)
        XCTAssertEqual(component.modeledHint, "hint:1")
        XCTAssertEqual(equalityCalls, 0)
        XCTAssertEqual(hinterCalls, 0)
        XCTAssertEqual(callbackCalls, 0)
        XCTAssertEqual(localChanges, [])
        XCTAssertEqual(componentHubChanges, [])
        localCancel.cancel()
        hubCancel.cancel()

        let formHub = MessageHub()
        var equalityCallsForForm = 0
        var validatorCalls = 0
        let form = FormVM(
            initial: DisposedFormModel(name: "valid"),
            persister: { _ in },
            hub: formHub,
            strict: true,
            validators: ["name": { model in
                validatorCalls += 1
                return model.name.isEmpty ? "required" : nil
            }],
            equals: { left, right in
                equalityCallsForForm += 1
                return left == right
            }
        )
        let initialFormModel = form.model
        let initialSnapshot = form.snapshot
        let initialErrors = form.errors
        let initialDirty = form.isDirty
        let initialValid = form.isValid
        var errorSignals: [[String: String]] = []
        var commandSignals = 0
        var formHubSignals = 0
        let errorsCancel = form.errorsChanged.sink { errorSignals.append($0) }
        let commandCancel = form.approveCommand.canExecuteChanged.sink { commandSignals += 1 }
        let formHubCancel = formHub.messages.sink { _ in formHubSignals += 1 }

        form.dispose()
        equalityCallsForForm = 0
        validatorCalls = 0
        errorSignals.removeAll()
        commandSignals = 0
        formHubSignals = 0
        let lateFormCompletion = {
            form.setModel(DisposedFormModel(name: ""))
        }

        lateFormCompletion()

        XCTAssertEqual(form.model, initialFormModel)
        XCTAssertEqual(form.snapshot, initialSnapshot)
        XCTAssertEqual(form.errors, initialErrors)
        XCTAssertEqual(equalityCallsForForm, 0)
        XCTAssertEqual(validatorCalls, 0)
        XCTAssertEqual(errorSignals, [])
        XCTAssertEqual(commandSignals, 0)
        XCTAssertEqual(formHubSignals, 0)
        XCTAssertEqual(form.isDirty, initialDirty)
        XCTAssertEqual(form.isValid, initialValid)
        errorsCancel.cancel()
        commandCancel.cancel()
        formHubCancel.cancel()
    }
}
