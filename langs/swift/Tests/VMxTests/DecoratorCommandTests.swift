//
// DecoratorCommand conformance tests — CMDD-004, CMDD-005, CMDD-006.
//
// See spec/04-commands.md §8.2 and ADR-0012.
//
import XCTest
@testable import VMx

final class DecoratorCommandTests: XCTestCase {

    // MARK: - Helpers

    /// Reference-type log box — a plain `var [String]` cannot be observed
    /// across @escaping closures captured by the builder's task/predicate.
    private final class Recorder { var entries: [String] = [] }

    private func makeCommand(label: String, into recorder: Recorder, enabled: Bool) -> RelayCommand {
        RelayCommand.builder()
            .task { recorder.entries.append(label) }
            .predicate { enabled }
            .build()
    }

    // MARK: - Tests

    /// CMDD-004 — canExecute() is inner.canExecute() AND extraPredicate.
    func testCmdd004CanExecuteIsInnerAndExtraPredicate() {
        let rec = Recorder()

        // inner=true, extra=false → false
        let innerTrue = makeCommand(label: "x", into: rec, enabled: true)
        let decExtraFalse = DecoratorCommand(innerTrue, extraPredicate: { false })
        XCTAssertFalse(decExtraFalse.canExecute(), "inner=true AND extra=false must be false")

        // inner=true, extra=true → true
        let decExtraTrue = DecoratorCommand(innerTrue, extraPredicate: { true })
        XCTAssertTrue(decExtraTrue.canExecute(), "inner=true AND extra=true must be true")

        // inner=false, extra=true → false
        let innerFalse = makeCommand(label: "y", into: rec, enabled: false)
        let decInnerFalse = DecoratorCommand(innerFalse, extraPredicate: { true })
        XCTAssertFalse(decInnerFalse.canExecute(), "inner=false AND extra=true must be false")

        // no extra predicate + inner=true → true (defaults to true)
        let decNoExtra = DecoratorCommand(innerTrue)
        XCTAssertTrue(decNoExtra.canExecute(), "no extraPredicate + inner=true must be true")
    }

    /// CMDD-005 — execute() invokes pre, inner, post in that exact order.
    func testCmdd005ExecuteRunsPreInnerPostInOrder() {
        let rec = Recorder()
        let inner = makeCommand(label: "inner", into: rec, enabled: true)
        let dec = DecoratorCommand(
            inner,
            preExecute:  { rec.entries.append("pre") },
            postExecute: { rec.entries.append("post") }
        )
        dec.execute()
        XCTAssertEqual(rec.entries, ["pre", "inner", "post"],
                       "execute() must invoke pre → inner → post in order")
    }

    /// CMDD-006 — execute() is a complete no-op (pre/inner/post all skipped)
    /// when canExecute() is false.
    func testCmdd006ExecuteIsNoOpWhenCanExecuteFalse() {
        let rec = Recorder()
        let inner = makeCommand(label: "inner", into: rec, enabled: true)
        let dec = DecoratorCommand(
            inner,
            preExecute:  { rec.entries.append("pre") },
            postExecute: { rec.entries.append("post") },
            extraPredicate: { false }
        )
        dec.execute()
        XCTAssertTrue(rec.entries.isEmpty,
                      "execute() must be a no-op when canExecute() is false")
    }
}
