//
// TokenPagedCommandRaceTests.swift — `TokenPagedComposition` command reads
// racing `dispose()` (#1922).
//
// `loadMoreCommand` and `refreshCommand` were `lazy var` properties. Swift does
// not synchronize the first read of a lazy property, so a read on one thread
// and `dispose()` on another could each create a command, and the stored one
// could differ from the one a caller holds. The commands are now created in
// `init`. The cases check that the reads and `dispose()` never race, that each
// property returns one instance, and that a command held across `dispose()`
// stays inert.
//

import Foundation
import XCTest
@testable import VMx

final class TokenPagedCommandRaceTests: XCTestCase {
    private let rounds = 2_000

    /// Holds a value that one racing thread writes and the test reads after the race.
    private final class Box<T> {
        var value: T?
    }

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

    /// A new composition exposes the live command chains, not the placeholders
    /// that `init` assigns before it builds them.
    func testCommandsAreLiveBeforeDispose() {
        let sut = TokenPagedComposition<Int, String>(fetchNext: { _ in ([], nil) })

        XCTAssertTrue(sut.loadMoreCommand.canExecute())
        XCTAssertTrue(sut.refreshCommand.canExecute())
    }

    /// One thread reads both commands twice while another thread disposes the
    /// composition. Each property returns one instance on every read, and the
    /// instances the reader holds are inert after `dispose()`.
    func testReadingCommandsDoesNotRaceDispose() {
        for _ in 0..<rounds {
            let sut = TokenPagedComposition<Int, String>(fetchNext: { _ in ([], nil) })
            let loads = Box<[AsyncRelayCommand]>()
            let refreshes = Box<[AsyncRelayCommand]>()
            race({
                loads.value = [sut.loadMoreCommand, sut.loadMoreCommand]
                refreshes.value = [sut.refreshCommand, sut.refreshCommand]
            }, { sut.dispose() })

            guard let heldLoads = loads.value, let heldRefreshes = refreshes.value else {
                XCTFail("the reading thread did not finish")
                return
            }
            XCTAssertTrue(heldLoads[0] === heldLoads[1], "loadMoreCommand changed between reads")
            XCTAssertTrue(heldRefreshes[0] === heldRefreshes[1], "refreshCommand changed between reads")
            XCTAssertTrue(heldLoads[0] === sut.loadMoreCommand)
            XCTAssertTrue(heldRefreshes[0] === sut.refreshCommand)
            XCTAssertFalse(heldLoads[0].canExecute())
            XCTAssertFalse(heldRefreshes[0].canExecute())
        }
    }
}
