//
// CompositeCommand conformance tests — CMDD-001, CMDD-002, CMDD-003.
//
// See spec/04-commands.md §8.1 and ADR-0012.
//
import XCTest
import Combine
@testable import VMx

final class CompositeCommandTests: XCTestCase {

    // MARK: - Helpers

    /// Reference-type log box — a plain `[String]` cannot be captured by the
    /// builder's `@escaping` task closure (Swift forbids capturing an `inout`).
    private final class Log { var entries: [String] = [] }

    private func makeCommand(label: String, into log: Log, enabled: Bool) -> RelayCommand {
        RelayCommand.builder()
            .task { log.entries.append(label) }
            .predicate { enabled }
            .build()
    }

    // MARK: - Tests

    /// CMDD-001 — canExecute is OR over inner commands.
    func testCmdd001CanExecuteIsOR() {
        let log = Log()
        let c1 = makeCommand(label: "c1", into: log, enabled: false)
        let c2 = makeCommand(label: "c2", into: log, enabled: true)
        let composite = CompositeCommand(c1, c2)
        XCTAssertTrue(composite.canExecute(), "OR: at least one enabled → true")

        let c3 = makeCommand(label: "c3", into: log, enabled: false)
        let c4 = makeCommand(label: "c4", into: log, enabled: false)
        let compositeFalse = CompositeCommand(c3, c4)
        XCTAssertFalse(compositeFalse.canExecute(), "OR: all disabled → false")
    }

    /// CMDD-002 — execute invokes only the currently-enabled inner commands.
    func testCmdd002ExecuteSkipsDisabledInners() {
        let log = Log()
        let c1 = makeCommand(label: "c1", into: log, enabled: true)
        let c2 = makeCommand(label: "c2", into: log, enabled: false)
        let c3 = makeCommand(label: "c3", into: log, enabled: true)
        let composite = CompositeCommand(c1, c2, c3)
        composite.execute()
        XCTAssertEqual(log.entries, ["c1", "c3"], "disabled inner must not be invoked")
    }

    /// CMDD-003 — canExecuteChanged fires when any inner's canExecuteChanged fires.
    func testCmdd003CanExecuteChangedMergesInners() {
        let trigger = PassthroughSubject<Void, Never>()
        let c1 = RelayCommand.builder()
            .task {}
            .triggers(trigger.eraseToAnyPublisher())
            .build()
        let composite = CompositeCommand(c1)
        var fired = 0
        let cancel = composite.canExecuteChanged.sink { _ in fired += 1 }
        trigger.send(())
        XCTAssertEqual(fired, 1, "composite canExecuteChanged must forward inner emissions")
        cancel.cancel()
    }
}
