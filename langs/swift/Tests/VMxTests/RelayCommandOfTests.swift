//
// RelayCommandOf<T> conformance tests.
//
// Claimed IDs: CMD-005 (parameterized variant passes parameter).
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
}
