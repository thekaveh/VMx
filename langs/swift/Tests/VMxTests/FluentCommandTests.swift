//
// FluentCommand conformance tests — CMD-008, CMD-009, CMD-010, CMD-011.
//
// See spec/04-commands.md §9 and ADR-0027.
//
// Execution-order assertions use reference-type `Recorder` boxes so that
// entries appended inside @escaping closures are visible at the call site.
// Async paths use XCTestExpectation to drain Swift Tasks deterministically.
//
import XCTest
import Combine
@testable import VMx

final class FluentCommandTests: XCTestCase {

    // MARK: - Helpers

    /// Reference-type execution log — must be a class so appends inside
    /// @escaping closures are observed at the assertion site.
    private final class Recorder { var entries: [String] = [] }

    private func makeCommand(label: String, into recorder: Recorder, enabled: Bool) -> RelayCommand {
        RelayCommand.builder()
            .task { recorder.entries.append(label) }
            .predicate { enabled }
            .build()
    }

    // MARK: - Tests

    /// CMD-008 — `confirm(_:_:)` is equivalent to explicit `ConfirmationDecoratorCommand`.
    func testCmd008ConfirmEquivalentToExplicitConstructor() async throws {
        let rec = Recorder()
        let inner = makeCommand(label: "inner", into: rec, enabled: true)

        // confirm-true path: inner must run
        let yes = confirm(inner, { true })
        XCTAssertTrue(yes.canExecute(), "CMD-008: canExecute must delegate to inner")
        try await yes.executeAsync()
        XCTAssertEqual(rec.entries, ["inner"],
                       "CMD-008: inner must run when confirm resolves true")

        // confirm-false path: inner must be skipped
        rec.entries.removeAll()
        let no = confirm(inner, { false })
        try await no.executeAsync()
        XCTAssertTrue(rec.entries.isEmpty,
                      "CMD-008: inner must NOT run when confirm resolves false")

        // canExecute parity with explicit constructor
        let explicit = ConfirmationDecoratorCommand(inner, confirm: { true })
        XCTAssertEqual(yes.canExecute(), explicit.canExecute(),
                       "CMD-008: canExecute must match the explicit ConfirmationDecoratorCommand")
    }

    /// CMD-009 — `precedeWith(_:_:)` runs `other` before `command`.
    func testCmd009PrecedeWithRunsOtherFirst() {
        let rec = Recorder()
        let cmd   = makeCommand(label: "cmd",   into: rec, enabled: true)
        let other = makeCommand(label: "other", into: rec, enabled: true)

        let result = precedeWith(cmd, other)
        result.execute()
        XCTAssertEqual(rec.entries, ["other", "cmd"],
                       "CMD-009: precedeWith must execute `other` before `cmd`")
    }

    /// CMD-010 — `succeedWith(_:_:)` runs `command` before `other`.
    func testCmd010SucceedWithRunsCmdFirst() {
        let rec = Recorder()
        let cmd   = makeCommand(label: "cmd",   into: rec, enabled: true)
        let other = makeCommand(label: "other", into: rec, enabled: true)

        let result = succeedWith(cmd, other)
        result.execute()
        XCTAssertEqual(rec.entries, ["cmd", "other"],
                       "CMD-010: succeedWith must execute `cmd` before `other`")
    }

    /// CMD-011 — `wrapWith(_:predicate:pre:post:)` is equivalent to explicit `DecoratorCommand`.
    func testCmd011WrapWithEquivalentToDecoratorCommand() {
        let rec = Recorder()
        let inner = makeCommand(label: "inner", into: rec, enabled: true)

        // all-absent → transparent decorator: canExecute and execute pass through
        let transparent = wrapWith(inner)
        XCTAssertTrue(transparent.canExecute(),
                      "CMD-011: transparent wrapWith must pass canExecute through")
        transparent.execute()
        XCTAssertEqual(rec.entries, ["inner"],
                       "CMD-011: transparent wrapWith must execute inner")

        // with pre/post/predicate
        rec.entries.removeAll()
        let decorated = wrapWith(
            inner,
            predicate: { true },
            pre:  { rec.entries.append("pre") },
            post: { rec.entries.append("post") }
        )
        XCTAssertTrue(decorated.canExecute(),
                      "CMD-011: decorated canExecute must be true when predicate returns true")
        decorated.execute()
        XCTAssertEqual(rec.entries, ["pre", "inner", "post"],
                       "CMD-011: wrapWith must run pre → inner → post in order")

        // predicate returning false blocks execution
        rec.entries.removeAll()
        let blocked = wrapWith(inner, predicate: { false })
        XCTAssertFalse(blocked.canExecute(),
                       "CMD-011: canExecute must be false when predicate returns false")
        blocked.execute()
        XCTAssertTrue(rec.entries.isEmpty,
                      "CMD-011: inner must not run when predicate returns false")
    }
}
