//
// FormStrictOnlyDirtyComparisonTests.swift — FORM-045 conformance tests.
//
// An update runs its dirty comparisons against `snapshot` only in strict
// mode. A strict `setModel` runs three equality comparisons and a strict deny
// two. A non-strict `setModel` runs one and a non-strict deny none. See
// spec/20-form-vm.md §5.2 and ADR-0216.
//
// Swift equality cannot fail, so these tests check the call counts only.
//

import Foundation
import XCTest
@testable import VMx

/// Counts the calls of a form's injected `equals`.
private final class EqualityCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    func record() {
        lock.lock()
        count += 1
        lock.unlock()
    }

    /// Returns the calls since the last take, and resets the count.
    func take() -> Int {
        lock.lock()
        defer { lock.unlock() }
        let calls = count
        count = 0
        return calls
    }
}

final class FormStrictOnlyDirtyComparisonTests: XCTestCase {

    private func makeForm(strict: Bool, counter: EqualityCounter) -> FormVM<String> {
        FormVM(
            initial: "x",
            persister: { _ in },
            strict: strict,
            equals: { lhs, rhs in
                counter.record()
                return lhs == rhs
            }
        )
    }

    /// FORM-045 — a strict setModel runs three equality comparisons and a strict deny two.
    func testForm045_strictUpdatesRunTheDirtyComparisons() {
        let counter = EqualityCounter()
        let form = makeForm(strict: true, counter: counter)
        _ = counter.take()

        form.setModel("y")
        XCTAssertEqual(counter.take(), 3, "candidate vs model, model vs snapshot, candidate vs snapshot")

        form.denyCommand.execute()
        XCTAssertEqual(counter.take(), 2, "model vs snapshot, reverted model vs snapshot")
        XCTAssertEqual(form.model, "x")
    }

    /// FORM-045 — a non-strict setModel runs one equality comparison and a non-strict deny none.
    func testForm045_nonStrictUpdatesSkipTheDirtyComparisons() {
        let counter = EqualityCounter()
        let form = makeForm(strict: false, counter: counter)
        _ = counter.take()

        form.setModel("y")
        XCTAssertEqual(counter.take(), 1, "only the candidate vs the live model")
        XCTAssertEqual(form.model, "y")

        form.denyCommand.execute()
        XCTAssertEqual(counter.take(), 0, "a non-strict deny compares nothing")
        XCTAssertEqual(form.model, "x")
    }
}
