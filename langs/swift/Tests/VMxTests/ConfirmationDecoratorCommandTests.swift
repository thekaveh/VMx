//
// ConfirmationDecoratorCommand conformance tests — CMDD-007, CMDD-008,
// CMDD-009, CMDD-010.
//
// See spec/04-commands.md §8.3, ADR-0049.
//
// All async tests use `await fulfillment(of:timeout:)` (available from
// macOS 13 / iOS 16, matching the package's minimum deployment targets) to
// drain fire-and-forget Tasks deterministically before asserting.
//
// Captured mutable state is held in reference-type boxes (`Recorder`,
// `ErrorBox`) — a plain `var` array captured by an @escaping async closure
// is not observed at the call site in Swift and would produce spurious failures.
//
import XCTest
import Combine
@testable import VMx

final class ConfirmationDecoratorCommandTests: XCTestCase {

    // MARK: - Helpers

    /// Reference-type execution log — use instead of a captured `var [String]`
    /// in @escaping / async closures.
    private final class Recorder { var entries: [String] = [] }

    /// Reference-type error collector for the `errors` channel.
    private final class ErrorBox { var errors: [Error] = [] }

    private enum TestError: Error, Equatable { case confirm }

    private func makeCommand(
        label: String,
        into recorder: Recorder,
        enabled: Bool
    ) -> RelayCommand {
        RelayCommand.builder()
            .task { recorder.entries.append(label) }
            .predicate { enabled }
            .build()
    }

    // MARK: - Tests

    /// CMDD-007 — inner runs only when confirm resolves true; confirm=false skips inner.
    func testCmdd007InnerRunsOnlyWhenConfirmed() async throws {
        let rec = Recorder()
        let inner = makeCommand(label: "inner", into: rec, enabled: true)

        // confirm returns true → inner executes exactly once
        let yes = ConfirmationDecoratorCommand(inner, confirm: { true })
        try await yes.executeAsync()
        XCTAssertEqual(rec.entries, ["inner"],
                       "inner must execute once when confirm returns true")

        rec.entries.removeAll()

        // confirm returns false → inner is skipped
        let no = ConfirmationDecoratorCommand(inner, confirm: { false })
        try await no.executeAsync()
        XCTAssertTrue(rec.entries.isEmpty,
                      "inner must NOT execute when confirm returns false")
    }

    /// CMDD-008 — canExecute() delegates verbatim to inner.canExecute().
    func testCmdd008CanExecuteDelegatesToInner() {
        let rec = Recorder()
        let innerTrue  = makeCommand(label: "x", into: rec, enabled: true)
        let innerFalse = makeCommand(label: "x", into: rec, enabled: false)

        let confTrue  = ConfirmationDecoratorCommand(innerTrue,  confirm: { true })
        let confFalse = ConfirmationDecoratorCommand(innerFalse, confirm: { true })

        XCTAssertTrue(confTrue.canExecute(),
                      "canExecute() must be true when inner.canExecute() is true")
        XCTAssertFalse(confFalse.canExecute(),
                       "canExecute() must be false when inner.canExecute() is false")
    }

    /// CMDD-009 — decorators compose: DecoratorCommand(ConfirmationDecoratorCommand(relay)).
    func testCmdd009DecoratorsCompose() async throws {
        let rec = Recorder()
        let exp = expectation(description: "CMDD-009: relay ran via the composed chain")
        // Relay fulfils the expectation so the fire-and-forget Task launched by
        // the inner ConfirmationDecorator can be drained deterministically.
        let relay = RelayCommand.builder()
            .task { rec.entries.append("relay"); exp.fulfill() }
            .predicate { true }
            .build()
        let conf = ConfirmationDecoratorCommand(relay, confirm: { true })
        let dec  = DecoratorCommand(conf)

        XCTAssertTrue(dec.canExecute(),
                      "composed canExecute() must propagate through both decorators")

        // Execute through the OUTER decorator so the full chain runs:
        // dec.execute() → conf.execute() (fire-and-forget Task) → relay.
        dec.execute()
        await fulfillment(of: [exp], timeout: 2.0)
        XCTAssertEqual(rec.entries, ["relay"],
                       "relay must execute exactly once via the composed decorators")
    }

    /// CMDD-010 — a throwing confirm surfaces the error on `errors`; inner has no side effect.
    func testCmdd010ThrowingConfirmSurfacesOnErrors() async {
        let box = ErrorBox()
        let rec = Recorder()
        let inner = makeCommand(label: "inner", into: rec, enabled: true)

        var cancellables: Set<AnyCancellable> = []
        let exp = expectation(description: "CMDD-010: error received on errors channel")

        let cmd = ConfirmationDecoratorCommand(inner, confirm: {
            throw TestError.confirm
        })
        cmd.errors.sink { error in
            box.errors.append(error)
            exp.fulfill()
        }.store(in: &cancellables)

        cmd.execute()   // fire-and-forget; the Task catches the thrown confirm error
        await fulfillment(of: [exp], timeout: 2.0)

        XCTAssertEqual(box.errors.count, 1,
                       "exactly one error must appear on the errors channel")
        XCTAssertEqual(box.errors.first as? TestError, .confirm,
                       "the error must be the confirm error that was thrown")
        XCTAssertTrue(rec.entries.isEmpty,
                      "inner must NOT execute when confirm throws")
    }
}
