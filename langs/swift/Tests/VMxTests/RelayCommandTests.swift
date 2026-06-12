//
// RelayCommand conformance tests.
//
// Claimed IDs: CMD-001..004, CMD-006, plus BLD-005 (additive triggers on
// the command builder). CMD-005 (parameterized variant) and CMD-007
// (truth-table fixture) are NOT implemented by this flavor (ADR-0037).
//
import XCTest
import Combine
@testable import VMx

final class RelayCommandTests: XCTestCase {

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
}
