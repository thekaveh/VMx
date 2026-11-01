//
// FormFailureAtomicUpdateTests.swift — FORM-035..038 conformance tests.
//
// `setModel` and `denyCommand` prepare before they commit: the equality,
// snapshotter, and validator callbacks run against the committed form state,
// and only a completed preparation that is still current is committed, in one
// step, and then published. See spec/20-form-vm.md §5.2 and §5.4, and
// ADR-0144.
//
// Swift field validators (`(Model) -> String?`), the model validator
// (`(Model) -> [String: String?]`), the injected `equals`
// (`(Model, Model) -> Bool`), and the snapshotter (`(Model) -> Model`) are
// non-throwing, so the failure-propagation clauses of FORM-035 and FORM-036
// cannot occur in this flavor (§5.4, Swift flavor note). Those tests assert
// what applies instead: callbacks run before anything is committed and see
// the unchanged form, and every observer reads the committed result as one
// consistent state. FORM-037 and FORM-038 (re-entrancy and disposal on the
// preparing thread) apply to Swift as written. Updates stay serialized per
// form, so another thread's update waits instead of making one stale; a
// flavor-local test at the end covers that.
//

import Combine
import Foundation
import XCTest
@testable import VMx

/// The observable state of a form, read through its public surface.
private struct AtomicFormState: Equatable {
    let model: String
    let snapshot: String
    let errors: [String: String]
    let isDirty: Bool
    let isValid: Bool
    let canExecute: Bool
}

extension AtomicFormState {
    init(_ form: FormVM<String>) {
        self.init(
            model: form.model,
            snapshot: form.snapshot,
            errors: form.errors,
            isDirty: form.isDirty,
            isValid: form.isValid,
            canExecute: form.approveCommand.canExecute()
        )
    }
}

/// One notification, with the form state its observer read when it arrived.
private struct AtomicNotice: Equatable {
    let channel: String
    let state: AtomicFormState
}

/// Records, in order, every notification a form publishes: `errorsChanged`,
/// the approve command's `canExecuteChanged`, and the form's hub messages.
private final class AtomicNotificationLog {
    private(set) var notices: [AtomicNotice] = []
    private var cancellables: Set<AnyCancellable> = []

    init(_ form: FormVM<String>, hub: MessageHub) {
        form.errorsChanged
            .sink { [weak self, weak form] _ in
                guard let self, let form else { return }
                self.record("errorsChanged", form)
            }
            .store(in: &cancellables)
        form.approveCommand.canExecuteChanged
            .sink { [weak self, weak form] _ in
                guard let self, let form else { return }
                self.record("canExecuteChanged", form)
            }
            .store(in: &cancellables)
        hub.messages
            .sink { [weak self, weak form] message in
                guard let self, let form, message.senderObject === form else { return }
                if message is FormRevertedMessage {
                    self.record("FormRevertedMessage", form)
                } else if let changed = message as? PropertyChangedMessage {
                    self.record("PropertyChanged(\(changed.propertyName))", form)
                } else {
                    self.record("\(type(of: message))", form)
                }
            }
            .store(in: &cancellables)
    }

    /// Appends a notice that reads the form's current state.
    func record(_ channel: String, _ form: FormVM<String>) {
        notices.append(AtomicNotice(channel: channel, state: AtomicFormState(form)))
    }

    func clear() {
        notices.removeAll()
    }
}

/// The expected notices for `channels`, each observing `state`.
private func expectedNotices(_ state: AtomicFormState, _ channels: String...) -> [AtomicNotice] {
    channels.map { AtomicNotice(channel: $0, state: state) }
}

/// The notifications that disposing an idle form publishes on its own (§10).
private func channelsOfPlainDisposal() -> [String] {
    let hub = MessageHub()
    let form = FormVM(initial: "initial", persister: { (_: String) in }, hub: hub)
    let log = AtomicNotificationLog(form, hub: hub)
    form.dispose()
    return log.notices.map(\.channel)
}

final class FormFailureAtomicUpdateTests: XCTestCase {

    // ── FORM-035 ──────────────────────────────────────────────────────────────

    /// FORM-035 — a rejecting field validator leaves a settled, consistent form: the
    /// candidate is committed with its own errors, never a new model with old errors,
    /// and a later accepted edit settles normally.
    func testForm035_fieldValidatorRejectionSettlesConsistently() {
        // The validator cannot throw (it returns `String?`), so FORM-035's failure
        // cannot occur in Swift; a rejection is an ordinary validation error.
        let hub = MessageHub()
        var form: FormVM<String>!
        var seenByValidator: [AtomicFormState] = []
        form = FormVM(
            initial: "first",
            persister: { _ in },
            hub: hub,
            strict: true,
            validators: ["name": { candidate in
                if let form { seenByValidator.append(AtomicFormState(form)) }
                return candidate.hasPrefix("bad") ? "rejected" : nil
            }]
        )
        let initial = AtomicFormState(
            model: "first", snapshot: "first", errors: [:],
            isDirty: false, isValid: true, canExecute: false
        )
        XCTAssertEqual(AtomicFormState(form), initial)
        let log = AtomicNotificationLog(form, hub: hub)

        // The validator's first run after construction.
        form.setModel("bad-1")

        let rejectedFirst = AtomicFormState(
            model: "bad-1", snapshot: "first", errors: ["name": "rejected"],
            isDirty: true, isValid: false, canExecute: false
        )
        XCTAssertEqual(seenByValidator, [initial], "the validator runs before anything is committed")
        XCTAssertEqual(AtomicFormState(form), rejectedFirst)
        XCTAssertEqual(
            log.notices,
            expectedNotices(rejectedFirst, "errorsChanged", "canExecuteChanged", "PropertyChanged(model)"),
            "every observer reads the candidate together with its errors"
        )

        // Again, after earlier successful assignments.
        form.setModel("good-1")
        form.setModel("good-2")
        let accepted = AtomicFormState(
            model: "good-2", snapshot: "first", errors: [:],
            isDirty: true, isValid: true, canExecute: true
        )
        XCTAssertEqual(AtomicFormState(form), accepted)
        seenByValidator.removeAll()
        log.clear()

        form.setModel("bad-2")

        let rejectedAgain = AtomicFormState(
            model: "bad-2", snapshot: "first", errors: ["name": "rejected"],
            isDirty: true, isValid: false, canExecute: false
        )
        XCTAssertEqual(seenByValidator, [accepted], "the validator runs before anything is committed")
        XCTAssertEqual(AtomicFormState(form), rejectedAgain)
        XCTAssertEqual(
            log.notices,
            expectedNotices(rejectedAgain, "errorsChanged", "canExecuteChanged", "PropertyChanged(model)")
        )

        // A later edit the validator accepts settles and publishes as FORM-030 requires.
        log.clear()
        form.setModel("good-3")

        let settled = AtomicFormState(
            model: "good-3", snapshot: "first", errors: [:],
            isDirty: true, isValid: true, canExecute: true
        )
        XCTAssertEqual(AtomicFormState(form), settled)
        XCTAssertEqual(
            log.notices,
            expectedNotices(settled, "errorsChanged", "canExecuteChanged", "PropertyChanged(model)")
        )
    }

    // ── FORM-036 ──────────────────────────────────────────────────────────────

    /// FORM-036 — the model validator, the injected equality, and deny's snapshotter and
    /// validator all run before the commit, so each update commits a consistent result.
    func testForm036_modelValidatorEqualityAndDenyArePreparedBeforeCommit() {
        // The model validator, `equals`, and the snapshotter cannot throw in Swift, so
        // FORM-036's failure clauses cannot occur; the preparation order still applies.

        // A rejecting model validator sees the unchanged form; the candidate and its
        // errors are committed together.
        let hub = MessageHub()
        var form: FormVM<String>!
        var seenByModelValidator: [AtomicFormState] = []
        form = FormVM(
            initial: "first",
            persister: { _ in },
            hub: hub,
            modelValidator: { candidate in
                if let form { seenByModelValidator.append(AtomicFormState(form)) }
                let error: String? = candidate.hasPrefix("bad") ? "model-rejected" : nil
                return ["name": error]
            }
        )
        let initial = AtomicFormState(
            model: "first", snapshot: "first", errors: [:],
            isDirty: false, isValid: true, canExecute: true
        )
        XCTAssertEqual(AtomicFormState(form), initial)
        let log = AtomicNotificationLog(form, hub: hub)

        form.setModel("bad")

        let rejected = AtomicFormState(
            model: "bad", snapshot: "first", errors: ["name": "model-rejected"],
            isDirty: true, isValid: false, canExecute: false
        )
        XCTAssertEqual(seenByModelValidator, [initial])
        XCTAssertEqual(AtomicFormState(form), rejected)
        XCTAssertEqual(
            log.notices,
            expectedNotices(rejected, "errorsChanged", "canExecuteChanged", "PropertyChanged(model)")
        )

        // The injected equality compares the candidate with the live model first, and
        // every comparison made while setModel prepares sees the unchanged model.
        var equalityForm: FormVM<String>!
        var seenByEquals: [String] = []
        equalityForm = FormVM(
            initial: "first",
            persister: { _ in },
            equals: { lhs, rhs in
                if let equalityForm {
                    seenByEquals.append("\(lhs)/\(rhs) live=\(equalityForm.model)")
                }
                return lhs == rhs
            }
        )

        equalityForm.setModel("next")

        XCTAssertEqual(seenByEquals.first, "first/next live=first")
        XCTAssertTrue(
            seenByEquals.allSatisfy { $0.hasSuffix("live=first") },
            "no comparison saw the candidate installed: \(seenByEquals)"
        )
        XCTAssertEqual(equalityForm.model, "next")
        XCTAssertTrue(equalityForm.isDirty)

        // Deny on a dirty form whose validator rejects the snapshot value: the
        // snapshotter and validator see the edited form, then the revert and its
        // errors are committed together before any deny message is published.
        let denyHub = MessageHub()
        var denyForm: FormVM<String>!
        var recording = false
        var seenBySnapshotter: [AtomicFormState] = []
        var seenByValidator: [AtomicFormState] = []
        denyForm = FormVM(
            initial: "saved",
            persister: { _ in },
            hub: denyHub,
            strict: true,
            snapshotter: { value in
                if recording, let denyForm { seenBySnapshotter.append(AtomicFormState(denyForm)) }
                return value
            },
            validators: ["name": { candidate in
                if recording, let denyForm { seenByValidator.append(AtomicFormState(denyForm)) }
                return candidate == "saved" ? "stale" : nil
            }]
        )
        denyForm.setModel("edited")
        let edited = AtomicFormState(
            model: "edited", snapshot: "saved", errors: [:],
            isDirty: true, isValid: true, canExecute: true
        )
        XCTAssertEqual(AtomicFormState(denyForm), edited)
        let denyLog = AtomicNotificationLog(denyForm, hub: denyHub)
        recording = true

        denyForm.denyCommand.execute()
        recording = false

        let reverted = AtomicFormState(
            model: "saved", snapshot: "saved", errors: ["name": "stale"],
            isDirty: false, isValid: false, canExecute: false
        )
        XCTAssertEqual(seenBySnapshotter, [edited], "the snapshotter runs before the revert is committed")
        XCTAssertEqual(seenByValidator, [edited], "the validator runs before the revert is committed")
        XCTAssertEqual(AtomicFormState(denyForm), reverted)
        XCTAssertEqual(
            denyLog.notices,
            expectedNotices(
                reverted,
                "errorsChanged",
                "FormRevertedMessage",
                "PropertyChanged(model)",
                "canExecuteChanged"
            ),
            "every deny notification reads the committed revert"
        )
    }

    // ── FORM-037 ──────────────────────────────────────────────────────────────

    /// FORM-037 — a validator that calls setModel(b) while setModel(a) prepares: the nested
    /// assignment commits and publishes one model message, and the outer call commits and
    /// publishes nothing after it. The nested notifications are delivered once the outer
    /// call releases the form's state lock (#1057).
    func testForm037_nestedAssignmentFromAValidatorWins() {
        let hub = MessageHub()
        var form: FormVM<String>!
        var log: AtomicNotificationLog!
        var reenter = true
        form = FormVM(
            initial: "initial",
            persister: { _ in },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "a", reenter, let form {
                    reenter = false
                    form.setModel("b")
                    log.record("nested setModel returned", form)
                }
                return candidate == "initial" ? nil : "\(candidate)-error"
            }]
        )
        log = AtomicNotificationLog(form, hub: hub)

        form.setModel("a")

        let nested = AtomicFormState(
            model: "b", snapshot: "initial", errors: ["name": "b-error"],
            isDirty: true, isValid: false, canExecute: false
        )
        XCTAssertFalse(reenter, "the validator re-entered setModel")
        XCTAssertEqual(AtomicFormState(form), nested, "Model, Errors, and IsDirty describe b")
        XCTAssertEqual(
            log.notices,
            expectedNotices(
                nested,
                "nested setModel returned",
                "errorsChanged",
                "canExecuteChanged",
                "PropertyChanged(model)"
            ),
            "the nested commit publishes once, and the outer call publishes nothing of its own"
        )

        // The abandoned outer call leaves the form usable.
        log.clear()
        form.setModel("c")

        let later = AtomicFormState(
            model: "c", snapshot: "initial", errors: ["name": "c-error"],
            isDirty: true, isValid: false, canExecute: false
        )
        XCTAssertEqual(AtomicFormState(form), later)
        XCTAssertEqual(log.notices, expectedNotices(later, "errorsChanged", "PropertyChanged(model)"))
    }

    /// FORM-037 — an assignment nested in deny's preparation wins over the revert, which
    /// commits and publishes nothing.
    func testForm037_nestedAssignmentDuringDenyPreparationWins() {
        let hub = MessageHub()
        var form: FormVM<String>!
        var reenterOnRevert = false
        form = FormVM(
            initial: "saved",
            persister: { _ in },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "saved", reenterOnRevert, let form {
                    reenterOnRevert = false
                    form.setModel("nested")
                }
                return nil
            }]
        )
        form.setModel("edited")
        let log = AtomicNotificationLog(form, hub: hub)
        reenterOnRevert = true

        form.denyCommand.execute()

        let nested = AtomicFormState(
            model: "nested", snapshot: "saved", errors: [:],
            isDirty: true, isValid: true, canExecute: true
        )
        XCTAssertFalse(reenterOnRevert, "the validator re-entered setModel")
        XCTAssertEqual(AtomicFormState(form), nested)
        XCTAssertEqual(
            log.notices,
            expectedNotices(nested, "PropertyChanged(model)"),
            "no FormRevertedMessage and no second model message"
        )
    }

    // ── FORM-038 ──────────────────────────────────────────────────────────────

    /// FORM-038 — a validator that disposes the form while setModel prepares: the call
    /// commits and publishes nothing, and the disposed form is inert.
    func testForm038_disposalDuringSetModelPreparationCommitsNothing() async throws {
        let hub = MessageHub()
        var form: FormVM<String>!
        var disposedByValidator = false
        var persisted = 0
        form = FormVM(
            initial: "initial",
            persister: { _ in persisted += 1 },
            hub: hub,
            strict: true,
            validators: ["name": { candidate in
                if candidate == "dispose-me", let form {
                    disposedByValidator = true
                    form.dispose()
                }
                // A commit would change the errors, validity, and dirty state.
                return candidate == "initial" ? nil : "rejected"
            }]
        )
        let log = AtomicNotificationLog(form, hub: hub)

        form.setModel("dispose-me")

        XCTAssertTrue(disposedByValidator)
        // Disposal's own effects still occur (§10); the abandoned update adds no
        // notification of its own, and no observer ever saw the candidate.
        XCTAssertEqual(
            log.notices.map(\.channel), channelsOfPlainDisposal(),
            "only the disposal's own notifications: \(log.notices)"
        )
        XCTAssertTrue(log.notices.allSatisfy { $0.state.model == "initial" && $0.state.errors.isEmpty })
        XCTAssertEqual(form.model, "initial")
        XCTAssertEqual(form.snapshot, "initial")
        XCTAssertEqual(form.errors, [:])
        XCTAssertFalse(form.isDirty)
        XCTAssertTrue(form.isValid)

        // The disposed form is inert (FORM-014).
        let disposed = AtomicFormState(form)
        let noticesAfterSetModel = log.notices
        form.setModel("late")
        form.denyCommand.execute()
        try await form.approveAsync()
        form.approveCommand.execute()
        XCTAssertEqual(AtomicFormState(form), disposed)
        XCTAssertEqual(persisted, 0, "a disposed form never invokes the persister")
        XCTAssertEqual(log.notices, noticesAfterSetModel)
    }

    /// FORM-038 — a validator that disposes the form while denyCommand prepares its revert:
    /// the model is not reverted and no deny message is published.
    func testForm038_disposalDuringDenyPreparationCommitsNothing() {
        let hub = MessageHub()
        var form: FormVM<String>!
        var disposeOnRevert = false
        form = FormVM(
            initial: "saved",
            persister: { _ in },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "saved", disposeOnRevert, let form {
                    disposeOnRevert = false
                    form.dispose()
                }
                return nil
            }]
        )
        form.setModel("edited")
        let log = AtomicNotificationLog(form, hub: hub)
        disposeOnRevert = true

        form.denyCommand.execute()

        XCTAssertFalse(disposeOnRevert, "the validator disposed the form")
        XCTAssertEqual(form.model, "edited", "the model is not reverted")
        XCTAssertEqual(form.snapshot, "saved")
        XCTAssertTrue(form.isDirty)
        // Disposal's own effects still occur (§10); the abandoned revert adds no
        // FormRevertedMessage, model message, or errorsChanged of its own.
        XCTAssertEqual(
            log.notices.map(\.channel), channelsOfPlainDisposal(),
            "only the disposal's own notifications: \(log.notices)"
        )
        XCTAssertTrue(log.notices.allSatisfy { $0.state.model == "edited" })

        // The disposed form is inert (FORM-014).
        let noticesAfterDisposal = log.notices
        form.denyCommand.execute()
        form.setModel("late")
        XCTAssertEqual(form.model, "edited")
        XCTAssertEqual(log.notices, noticesAfterDisposal)
    }

    // ── Serialization ─────────────────────────────────────────────────────────

    // Updates are serialized per form (§5.4): another thread's setModel waits
    // while an admitted update prepares, then commits after it, so neither
    // edit is dropped. Staleness comes only from re-entry on the preparing
    // thread (FORM-037, FORM-038).
    func testAnotherThreadsSetModelWaitsForAPreparingUpdate() {
        let validatorEntered = DispatchSemaphore(value: 0)
        let releaseValidator = DispatchSemaphore(value: 0)
        let hub = MessageHub()
        let form = FormVM(
            initial: "initial",
            persister: { (_: String) in },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "first" {
                    validatorEntered.signal()
                    _ = releaseValidator.wait(timeout: .now() + 10)
                }
                return nil
            }]
        )
        let countLock = NSLock()
        var published = 0
        let subscription = hub.messages.sink { message in
            guard (message as? PropertyChangedMessage)?.propertyName == "model" else { return }
            countLock.lock()
            published += 1
            countLock.unlock()
        }
        defer { subscription.cancel() }

        let boxedForm = UncheckedSendableBox(form)
        let firstDone = DispatchSemaphore(value: 0)
        let secondDone = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            boxedForm.value.setModel("first")
            firstDone.signal()
        }
        XCTAssertEqual(validatorEntered.wait(timeout: .now() + 10), .success)
        DispatchQueue.global().async {
            boxedForm.value.setModel("second")
            secondDone.signal()
        }
        XCTAssertEqual(
            secondDone.wait(timeout: .now() + 0.2), .timedOut,
            "the second update waits for the first one's preparation"
        )
        releaseValidator.signal()

        XCTAssertEqual(firstDone.wait(timeout: .now() + 10), .success)
        XCTAssertEqual(secondDone.wait(timeout: .now() + 10), .success)
        XCTAssertEqual(form.model, "second")
        countLock.lock()
        let publishedCount = published
        countLock.unlock()
        XCTAssertEqual(publishedCount, 2, "each edit commits and publishes once")
    }
}
