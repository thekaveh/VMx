//
// FormApproveNotificationTests.swift — FORM-043 conformance.
//
// An update raises `approveCommand.canExecuteChanged` exactly once when it
// changes `isValid`, or `isDirty` in strict mode, also while an approval is
// in flight. See spec/20-form-vm.md §5.2 and ADR-0196.
//

import Combine
import Foundation
import XCTest
@testable import VMx

/// Thread-safe counter for `canExecuteChanged` notifications.
private final class NotificationCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var storage = 0

    func increment() {
        lock.lock()
        storage += 1
        lock.unlock()
    }

    var value: Int {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }
}

/// Late-bound form reference and the counts the persister read.
private final class PersisterProbe: @unchecked Sendable {
    weak var form: FormVM<String>?
    private let lock = NSLock()
    private var reads: (entry: Int, afterUpdate: Int)?

    func record(entry: Int, afterUpdate: Int) {
        lock.lock()
        reads = (entry, afterUpdate)
        lock.unlock()
    }

    var recorded: (entry: Int, afterUpdate: Int)? {
        lock.lock()
        defer { lock.unlock() }
        return reads
    }
}

private let rejectsBad: [String: (String) -> String?] = [
    "model": { $0 == "bad" ? "bad model" : nil }
]

final class FormApproveNotificationTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// FORM-043 — in strict mode an update raises the approve notification
    /// exactly once when it changes validity or dirty state, and not otherwise.
    func testForm043StrictUpdateRaisesOnceWhenTheGatesChange() {
        let form = FormVM(
            initial: "pristine",
            persister: { _ in },
            strict: true,
            validators: rejectsBad
        )
        form.setModel("bad")
        XCTAssertTrue(form.isDirty)
        XCTAssertFalse(form.isValid)
        let counter = NotificationCounter()
        form.approveCommand.canExecuteChanged
            .sink { counter.increment() }
            .store(in: &cancellables)

        form.setModel("pristine")
        XCTAssertEqual(counter.value, 1, "FORM-043: valid and clean raises once")
        XCTAssertFalse(form.approveCommand.canExecute())

        form.setModel("a")
        XCTAssertEqual(counter.value, 2, "FORM-043: valid and dirty raises once")
        XCTAssertTrue(form.approveCommand.canExecute())

        form.setModel("b")
        XCTAssertEqual(counter.value, 2, "FORM-043: unchanged gates raise nothing")
        form.dispose()
    }

    /// FORM-043 — an update inside the persister raises the approve
    /// notification once although an approval is in flight.
    func testForm043UpdateDuringAnApprovalRaisesOnce() async throws {
        let counter = NotificationCounter()
        let probe = PersisterProbe()
        let form = FormVM(
            initial: "pristine",
            persister: { _ in
                let entry = counter.value
                probe.form?.setModel("bad")
                probe.record(entry: entry, afterUpdate: counter.value)
            },
            validators: rejectsBad
        )
        probe.form = form
        XCTAssertTrue(form.isValid)
        form.approveCommand.canExecuteChanged
            .sink { counter.increment() }
            .store(in: &cancellables)

        try await form.approveAsync()

        let reads = try XCTUnwrap(probe.recorded, "FORM-043: the persister ran")
        XCTAssertEqual(reads.entry, 1, "FORM-043: admission raised once")
        XCTAssertEqual(reads.afterUpdate, reads.entry + 1,
                       "FORM-043: the update raised once during the approval")
        XCTAssertEqual(counter.value, reads.afterUpdate + 1,
                       "FORM-043: settlement raised once more")
        form.dispose()
    }
}
