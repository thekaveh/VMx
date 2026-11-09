//
// RelayCommand conformance tests.
//
// Claimed IDs: CMD-001..004, CMD-006, CMD-014..016, CMD-021, plus BLD-005 (additive triggers on
// the command builder). CMD-005 (parameterized RelayCommandOf) and CMD-007
// (truth-table fixture) are covered by RelayCommandOfTests /
// RelayCommandTruthTableTests (Phase 3 Inc 4).
//
import XCTest
import Combine
@testable import VMx

final class RelayCommandTests: XCTestCase {

    func testPredicateDisposalInvalidatesAdmission() {
        var invoked = false
        var command: RelayCommand!
        command = RelayCommand.builder()
            .predicate {
                command.dispose()
                return true
            }
            .task { invoked = true }
            .build()

        XCTAssertFalse(command.canExecute())
        command.execute()
        XCTAssertFalse(invoked)
    }

    /// CMD-001 — execute invokes the configured task.
    func testCmd001ExecuteInvokesTask() {
        var calls = 0
        let cmd = RelayCommand.builder()
            .task { calls += 1 }
            .build()
        cmd.execute()
        XCTAssertEqual(calls, 1)
    }

    /// CMD-002 — `canExecute` with no predicate returns true.
    func testCmd002CanExecuteDefault() {
        let cmd = RelayCommand.builder().task {}.build()
        XCTAssertTrue(cmd.canExecute())
    }

    /// CMD-003 — `canExecute` returns the predicate result.
    func testCmd003CanExecutePredicate() {
        let cmd = RelayCommand.builder()
            .task {}
            .predicate { false }
            .build()
        XCTAssertFalse(cmd.canExecute())
    }

    /// CMD-004 — Trigger emission fires `canExecuteChanged`.
    func testCmd004TriggerFiresCanExecuteChanged() {
        let trigger = PassthroughSubject<Void, Never>()
        let cmd = RelayCommand.builder()
            .triggers(trigger.eraseToAnyPublisher())
            .build()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { _ in fires += 1 }
        trigger.send(())
        XCTAssertEqual(fires, 1)
        cancel.cancel()
    }

    /// CMD-014 — imperative raise emits exactly once without evaluating delegates.
    func testCmd014ImperativeRaiseEmitsOnceWithoutEvaluatingDelegates() {
        var predicateCalls = 0
        var taskCalls = 0
        let cmd = RelayCommand.builder()
            .predicate { predicateCalls += 1; return true }
            .task { taskCalls += 1 }
            .build()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { fires += 1 }

        cmd.raiseCanExecuteChanged()

        XCTAssertEqual(fires, 1)
        XCTAssertEqual(predicateCalls, 0)
        XCTAssertEqual(taskCalls, 0)
        cancel.cancel()
    }

    /// CMD-015 — repeated imperative raises and trigger emissions remain additive.
    func testCmd015RepeatedImperativeAndTriggerNotificationsAreAdditive() {
        let trigger = PassthroughSubject<Void, Never>()
        let cmd = RelayCommand.builder()
            .triggers(trigger.eraseToAnyPublisher())
            .build()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { fires += 1 }

        cmd.raiseCanExecuteChanged()
        cmd.raiseCanExecuteChanged()
        trigger.send(())

        XCTAssertEqual(fires, 3)
        cancel.cancel()
    }

    /// CMD-021 — structural: `canExecuteChanged` has the failure type `Never`
    /// and a Combine sink cannot throw, so no handler can fail. With a trigger
    /// built through an operator, two handlers each see both trigger
    /// notifications and the imperative raise.
    func testCmd021CanExecuteChangedHandlersCannotFailAndAllReceive() {
        let source = PassthroughSubject<Int, Never>()
        let cmd = RelayCommand.builder()
            .triggers(source.map { _ in () }.eraseToAnyPublisher())
            .build()
        XCTAssertTrue(failureType(of: cmd.canExecuteChanged) == Never.self)
        var first = 0
        var second = 0
        let a = cmd.canExecuteChanged.sink { first += 1 }
        let b = cmd.canExecuteChanged.sink { second += 1 }

        source.send(1)
        source.send(2)
        XCTAssertEqual(first, 2)
        XCTAssertEqual(second, 2)

        cmd.raiseCanExecuteChanged()
        XCTAssertEqual(first, 3)
        XCTAssertEqual(second, 3)
        a.cancel()
        b.cancel()
        cmd.dispose()
    }

    private func failureType<P: Publisher>(of _: P) -> Any.Type { P.Failure.self }

    /// CMD-016 — imperative raise after disposal is a no-op.
    func testCmd016ImperativeRaiseAfterDisposalIsNoOp() {
        let cmd = RelayCommand.builder().build()
        // Disposal finishes the change subject, and a finished subject drops
        // later values. So the closed channel alone keeps a later raise from
        // reaching this subscriber, with or without the disposed check.
        // `testRaiseFromFinalDisposalNotificationPublishesNothingMore`
        // observes the check itself.
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { fires += 1 }
        cmd.dispose()
        fires = 0

        cmd.raiseCanExecuteChanged()

        XCTAssertEqual(fires, 0)
        cancel.cancel()
    }

    /// A raise from the final disposal notification publishes nothing more (#1341).
    /// `dispose()` sets the disposed flag, sends one final value, then finishes
    /// the subject. A raise from that value reaches the open subject, so only
    /// the disposed check drops it.
    func testRaiseFromFinalDisposalNotificationPublishesNothingMore() {
        let cmd = RelayCommand.builder().build()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { _ in
            fires += 1
            if fires == 1 { cmd.raiseCanExecuteChanged() }
        }

        cmd.dispose()

        XCTAssertEqual(fires, 1)
        cancel.cancel()
    }

    /// CMD-006 — execute with null task is a no-op.
    func testCmd006ExecuteWithNullTaskIsNoOp() {
        let cmd = RelayCommand.builder().build()
        cmd.execute() // must not crash
        XCTAssertTrue(cmd.canExecute())
    }

    /// Execute is gated on canExecute: skips the task when false
    /// (spec/04 §5; no dedicated catalog ID).
    func testExecuteSkippedWhenPredicateFalse() {
        var calls = 0
        let cmd = RelayCommand.builder()
            .task { calls += 1 }
            .predicate { false }
            .build()
        cmd.execute()
        XCTAssertEqual(calls, 0)
    }

    /// BLD-005 — additive setters: multiple `.triggers(...)` calls retain
    /// prior values.
    func testBld005MultipleTriggersAdditive() {
        let t1 = PassthroughSubject<Void, Never>()
        let t2 = PassthroughSubject<Void, Never>()
        let cmd = RelayCommand.builder()
            .triggers(t1.eraseToAnyPublisher())
            .triggers(t2.eraseToAnyPublisher())
            .build()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { _ in fires += 1 }
        t1.send(()); t2.send(())
        XCTAssertEqual(fires, 2)
        cancel.cancel()
    }

    /// Dispose is idempotent (no dedicated catalog ID).
    func testDisposeIdempotent() {
        let cmd = RelayCommand.builder().task {}.build()
        cmd.dispose()
        cmd.dispose() // must not crash
    }

    /// CMD-013 — disposed RelayCommand instances are inert.
    func testCmd013DisposedRelayCommandIsInert() {
        var calls = 0
        let cmd = RelayCommand.builder()
            .task { calls += 1 }
            .build()

        cmd.dispose()
        cmd.execute()

        XCTAssertFalse(cmd.canExecute())
        XCTAssertEqual(calls, 0)
    }
}
