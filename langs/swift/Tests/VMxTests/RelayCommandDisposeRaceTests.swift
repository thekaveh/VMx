//
// RelayCommandDisposeRaceTests.swift — #1567 regression tests.
//
// `dispose()` on one thread writes a command's disposal flag while
// `canExecute()` on another thread reads it. Before the fix the flag had no
// lock, and the Swift `thread sanitizer` job reported a data race on it. The
// cases check that the reads and the write never race, and that a command
// disposed during a racing read stays inert.
//

import Foundation
import XCTest
@testable import VMx

final class RelayCommandDisposeRaceTests: XCTestCase {
    private let rounds = 2_000

    /// Runs `first` and `second` on two new threads that start together, and
    /// waits for both.
    private func race(_ first: @escaping () -> Void, _ second: @escaping () -> Void) {
        let start = DispatchGroup()
        start.enter()
        let done = DispatchGroup()
        for body in [first, second] {
            done.enter()
            Thread.detachNewThread {
                start.wait()
                body()
                done.leave()
            }
        }
        start.leave()
        XCTAssertEqual(done.wait(timeout: .now() + hangGuard), .success, "a racing thread hung")
    }

    func testRelayCommandCanExecuteDoesNotRaceDispose() {
        for _ in 0..<rounds {
            let command = RelayCommand.builder().task { }.predicate { true }.build()
            race({ _ = command.canExecute() }, { command.dispose() })
            XCTAssertFalse(command.canExecute())
        }
    }

    func testRelayCommandOfCanExecuteDoesNotRaceDispose() {
        for _ in 0..<rounds {
            let command = RelayCommandOf<Int>(task: { _ in }, predicate: { _ in true }, triggers: [])
            race({ _ = command.canExecute(1) }, { command.dispose() })
            XCTAssertFalse(command.canExecute(1))
        }
    }

    func testConcurrentDisposeOfRelayCommandIsIdempotent() {
        for _ in 0..<rounds {
            let command = RelayCommand.builder().task { }.build()
            race({ command.dispose() }, { command.dispose() })
            XCTAssertFalse(command.canExecute())
        }
    }
}
