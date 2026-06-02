//
// RelayCommand conformance subset (CMD-001..CMD-007).
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

    /// CMD-005 — execute gated on canExecute: skips task when false.
    func testCmd005ExecuteSkippedWhenPredicateFalse() {
        var calls = 0
        let cmd = RelayCommand.builder()
            .task { calls += 1 }
            .predicate { false }
            .build()
        cmd.execute()
        XCTAssertEqual(calls, 0)
    }

    /// CMD-006 — multiple `.triggers(...)` calls combine additively.
    func testCmd006MultipleTriggers() {
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

    /// CMD-007 — dispose is idempotent.
    func testCmd007DisposeIdempotent() {
        let cmd = RelayCommand.builder().task {}.build()
        cmd.dispose()
        cmd.dispose() // must not crash
    }
}
