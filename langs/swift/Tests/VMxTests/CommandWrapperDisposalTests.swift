//
// CommandWrapperDisposalTests — conformance tests CMDD-011, CMDD-012, CMDD-013.
//
// Disposed CompositeCommand, DecoratorCommand, and ConfirmationDecoratorCommand
// are inert, and disposal during execution or a pending confirmation admits no
// later inner work (spec/04-commands.md §8.4, ADR-0134).
//
// Swift commands cannot throw from `execute()`, so the admitted-pair rethrow case
// of CMDD-013 is covered by `DecoratorCommand`'s `defer` (ADR-0062 §2.5).
//
import XCTest
import Combine
@testable import VMx

final class CommandWrapperDisposalTests: XCTestCase {

    // MARK: - Helpers

    private final class Recorder { var entries: [String] = [] }

    private enum TestError: Error { case confirm }

    /// A confirmation that stays pending until the test resolves it.
    private final class PendingConfirmation: @unchecked Sendable {
        let parked: XCTestExpectation
        private let lock = NSLock()
        private var continuation: CheckedContinuation<Bool, Error>?
        private var outcome: Result<Bool, Error>?

        init(_ parked: XCTestExpectation) { self.parked = parked }

        func wait() async throws -> Bool {
            try await withCheckedThrowingContinuation { continuation in
                lock.lock()
                if let outcome {
                    lock.unlock()
                    continuation.resume(with: outcome)
                    return
                }
                self.continuation = continuation
                lock.unlock()
                parked.fulfill()
            }
        }

        func resolve(_ result: Result<Bool, Error>) {
            lock.lock()
            let continuation = self.continuation
            self.continuation = nil
            if continuation == nil { outcome = result }
            lock.unlock()
            continuation?.resume(with: result)
        }
    }

    private let signalTimeout: TimeInterval = 30

    private func makeCommand(label: String, into recorder: Recorder) -> RelayCommand {
        RelayCommand.builder()
            .task { recorder.entries.append(label) }
            .predicate { true }
            .build()
    }

    // MARK: - CMDD-011

    /// CMDD-011 — disposed composite and decorator commands are inert and leave their inner commands usable.
    func testCmdd011DisposedCompositeAndDecoratorAreInert() {
        let recorder = Recorder()
        let a = makeCommand(label: "a", into: recorder)
        let composite = CompositeCommand(a, makeCommand(label: "b", into: recorder))
        composite.dispose()
        composite.dispose()

        XCTAssertFalse(composite.canExecute())
        composite.execute()
        XCTAssertEqual(recorder.entries, [])

        let inner = makeCommand(label: "inner", into: recorder)
        let decorator = DecoratorCommand(
            inner,
            preExecute: { recorder.entries.append("pre") },
            postExecute: { recorder.entries.append("post") },
            extraPredicate: {
                recorder.entries.append("predicate")
                return true
            }
        )
        decorator.dispose()
        decorator.dispose()

        XCTAssertFalse(decorator.canExecute())
        decorator.execute()
        XCTAssertEqual(recorder.entries, [])

        // The inner commands were not disposed.
        a.execute()
        inner.execute()
        XCTAssertEqual(recorder.entries, ["a", "inner"])
    }

    // MARK: - CMDD-012

    /// CMDD-012 — a disposed confirmation decorator never consults its confirm delegate.
    func testCmdd012DisposedConfirmationNeverConsultsConfirm() async throws {
        let recorder = Recorder()
        let confirms = Recorder()
        let command = ConfirmationDecoratorCommand(makeCommand(label: "inner", into: recorder)) {
            confirms.entries.append("confirm")
            return true
        }
        command.dispose()
        command.dispose()

        XCTAssertFalse(command.canExecute())
        try await command.executeAsync()

        XCTAssertEqual(confirms.entries, [])
        XCTAssertEqual(recorder.entries, [])
    }

    /// CMDD-012 — a confirmation resolving true, false, or faulted after disposal runs nothing and emits nothing.
    func testCmdd012ConfirmationResolvingAfterDisposalRunsNothing() async throws {
        let outcomes: [(String, Result<Bool, Error>)] = [
            ("true", .success(true)),
            ("false", .success(false)),
            ("faulted", .failure(TestError.confirm)),
        ]
        for (label, outcome) in outcomes {
            let recorder = Recorder()
            let inner = makeCommand(label: "inner", into: recorder)
            let pending = PendingConfirmation(expectation(description: "confirm parked (\(label))"))
            let command = ConfirmationDecoratorCommand(inner) { try await pending.wait() }
            let errors = Recorder()
            let completed = expectation(description: "errors completed (\(label))")
            let subscription = command.errors.sink(
                receiveCompletion: { _ in completed.fulfill() },
                receiveValue: { errors.entries.append(String(describing: $0)) }
            )

            let awaited = Task { try await command.executeAsync() }
            await fulfillment(of: [pending.parked], timeout: signalTimeout)
            command.dispose()
            await fulfillment(of: [completed], timeout: signalTimeout)
            pending.resolve(outcome)
            let result = await awaited.result

            switch (outcome, result) {
            case (.failure, .failure), (.success, .success):
                break
            default:
                XCTFail("the awaited path must propagate exactly the confirmation's outcome (\(label))")
            }
            XCTAssertEqual(recorder.entries, [], label)
            XCTAssertEqual(errors.entries, [], label)
            inner.execute()
            XCTAssertEqual(recorder.entries, ["inner"], label)
            subscription.cancel()
        }
    }

    // MARK: - CMDD-013

    /// CMDD-013 — a composite runs no later child after an earlier child disposes it.
    func testCmdd013CompositeRunsNoChildAfterDisposalByAnEarlierChild() {
        let recorder = Recorder()
        var composite: CompositeCommand?
        let first = RelayCommand.builder()
            .task {
                recorder.entries.append("first")
                composite?.dispose()
            }
            .build()
        composite = CompositeCommand(first, makeCommand(label: "second", into: recorder))

        composite?.execute()

        XCTAssertEqual(recorder.entries, ["first"])
    }

    /// CMDD-013 — a decorator disposed by its extra predicate runs neither hook nor inner command.
    func testCmdd013DecoratorDisposedByItsPredicateRunsNothing() {
        let recorder = Recorder()
        var decorator: DecoratorCommand?
        decorator = DecoratorCommand(
            makeCommand(label: "inner", into: recorder),
            preExecute: { recorder.entries.append("pre") },
            postExecute: { recorder.entries.append("post") },
            extraPredicate: {
                decorator?.dispose()
                return true
            }
        )

        decorator?.execute()

        XCTAssertEqual(recorder.entries, [])
    }

    /// CMDD-013 — a decorator disposed by its pre-action skips the inner command but still runs post once.
    func testCmdd013DecoratorDisposedByItsPreActionStillRunsPostOnce() {
        let recorder = Recorder()
        var decorator: DecoratorCommand?
        decorator = DecoratorCommand(
            makeCommand(label: "inner", into: recorder),
            preExecute: {
                recorder.entries.append("pre")
                decorator?.dispose()
            },
            postExecute: { recorder.entries.append("post") }
        )

        decorator?.execute()
        decorator?.execute()

        XCTAssertEqual(recorder.entries, ["pre", "post"])
    }
}
