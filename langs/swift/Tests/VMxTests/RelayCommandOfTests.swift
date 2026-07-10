//
// RelayCommandOf<T> conformance tests.
//
// Claimed IDs: CMD-005, CMD-016, CMD-017.
//
import XCTest
import Combine
@testable import VMx

final class RelayCommandOfTests: XCTestCase {

    /// CMD-005 — Parameterized variant passes parameter to the task; predicate gates on parameter.
    func testCmd005ParameterizedVariantPassesParameter() {
        var recorder: [Int] = []
        let cmd = RelayCommandOf<Int>.builder()
            .task { p in recorder.append(p) }
            .build()

        cmd.execute(42)

        XCTAssertEqual(recorder, [42])
    }

    /// CMD-017 — parameterized imperative raise emits exactly once.
    func testCmd017ParameterizedImperativeRaiseEmitsOnce() {
        let cmd = RelayCommandOf<Int>.builder().build()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { fires += 1 }

        cmd.raiseCanExecuteChanged()

        XCTAssertEqual(fires, 1)
        cancel.cancel()
    }

    /// CMD-016 — parameterized imperative raise after disposal is a no-op.
    func testCmd016ParameterizedImperativeRaiseAfterDisposalIsNoOp() {
        let cmd = RelayCommandOf<Int>.builder().build()
        cmd.dispose()
        var fires = 0
        let cancel = cmd.canExecuteChanged.sink { fires += 1 }

        cmd.raiseCanExecuteChanged()

        XCTAssertEqual(fires, 0)
        cancel.cancel()
    }

    /// CMD-005 (predicate sub-case) — predicate receives the parameter and gates execution.
    func testCmd005PredicateGatesOnParameter() {
        var recorder: [Int] = []
        let cmd = RelayCommandOf<Int>.builder()
            .task { p in recorder.append(p) }
            .predicate { p in p > 0 }
            .build()

        cmd.execute(-1)  // blocked by predicate
        cmd.execute(10)  // allowed

        XCTAssertEqual(recorder, [10])
    }

    /// CMD-013 — disposed RelayCommandOf instances are inert.
    func testCmd013DisposedRelayCommandOfIsInert() {
        var recorder: [Int] = []
        let cmd = RelayCommandOf<Int>.builder()
            .task { p in recorder.append(p) }
            .build()

        cmd.dispose()
        cmd.execute(42)

        XCTAssertFalse(cmd.canExecute(42))
        XCTAssertEqual(recorder, [])
    }

    /// Disposing emits one terminal `canExecuteChanged` value before completion —
    /// parity with `RelayCommand` + the C#/Python/TypeScript relay commands (7 of 8
    /// sync relay dispose paths emit this; this variant was the lone omission).
    func testDisposeEmitsTerminalCanExecuteChanged() {
        let cmd = RelayCommandOf<Int>.builder()
            .task { _ in }
            .build()

        var emissions = 0
        let c = cmd.canExecuteChanged.sink { emissions += 1 }

        cmd.dispose()

        XCTAssertEqual(emissions, 1, "dispose must emit one terminal canExecuteChanged")
        c.cancel()
    }
}
