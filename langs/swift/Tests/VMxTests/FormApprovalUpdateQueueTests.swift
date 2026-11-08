//
// FormApprovalUpdateQueueTests.swift — FORM-039..040 conformance tests.
//
// `FormVM` queues a `setModel` or deny that the approving thread makes during
// the pre-publication window and replays it after `onApproved`. See
// spec/20-form-vm.md §5.1, §5.3 and §5.4, and ADR-0174.
//
// PLACEHOLDER: the spec change for ADR-0174 adds these IDs before the Swift
// implementation lands. The implementation PR replaces each skipped test with
// the behavioral test. Swift callbacks cannot fail, so the FORM-040 test covers
// only the call-time equality and replay-order clauses. The conformance
// execution check counts a skipped ID as not passing, so CI stays red until
// then.
//

import XCTest

final class FormApprovalUpdateQueueTests: XCTestCase {
    /// FORM-039 — updates during approval publication replay after `onApproved`.
    func testUpdatesDuringPublicationReplayAfterOnApproved() throws {
        throw XCTSkip("ADR-0174 placeholder: replaced by the Swift FormVM implementation")
    }

    /// FORM-040 — a queued update prepares at call time and replays in order.
    func testQueuedUpdatePreparesAtCallTimeAndReplaysInOrder() throws {
        throw XCTSkip("ADR-0174 placeholder: replaced by the Swift FormVM implementation")
    }
}
