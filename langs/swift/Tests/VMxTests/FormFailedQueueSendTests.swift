//
// FormFailedQueueSendTests.swift — FORM-044 conformance tests.
//
// When a send of the outermost update's queue fails, the later sends stop,
// and a nested approval whose persister has not started is released. See
// spec/20-form-vm.md §5.4 rule 7 and ADR-0216.
//
// Swift sinks and hubs cannot fail, so rule 7 cannot occur in this flavor.
// The test runs the FORM-044 setup with a hub that does not fail: both model
// messages arrive, and the persister of the nested approval runs once, after
// them.
//

import Combine
import Foundation
import XCTest
@testable import VMx

/// Thread-safe event log shared by the hub sink and the persister.
private final class QueueSendLog: @unchecked Sendable {
    private let lock = NSLock()
    private var entries: [String] = []

    func append(_ entry: String) {
        lock.lock()
        entries.append(entry)
        lock.unlock()
    }

    var events: [String] {
        lock.lock()
        defer { lock.unlock() }
        return entries
    }
}

final class FormFailedQueueSendTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// FORM-044 — a validator that approves, then sets b and c: both model messages arrive,
    /// and the nested approval's persister runs once, after them.
    func testForm044_nestedApprovalStartsAfterEveryQueuedSend() async {
        let hub = MessageHub()
        let log = QueueSendLog()
        weak var weakForm: FormVM<String>?
        var reenter = true
        let form = FormVM(
            initial: "x",
            persister: { (_: String) in log.append("persisted") },
            hub: hub,
            validators: ["name": { candidate in
                if candidate == "a", reenter, let form = weakForm {
                    reenter = false
                    form.approveCommand.execute()
                    form.setModel("b")
                    form.setModel("c")
                }
                return nil
            }]
        )
        weakForm = form
        // Hold the scheduled persister task, so the test controls when it runs.
        var held: [@Sendable () async -> Void] = []
        form.commandApprovalTaskStarter = { operation in
            log.append("persister task started")
            held.append(operation)
        }
        hub.messages
            .sink { message in
                guard (message as? PropertyChangedMessage)?.propertyName == "model" else { return }
                log.append("model message")
            }
            .store(in: &cancellables)
        var canExecuteChanged = 0
        form.approveCommand.canExecuteChanged
            .sink { _ in canExecuteChanged += 1 }
            .store(in: &cancellables)

        form.setModel("a")
        XCTAssertEqual(log.events, ["model message", "model message", "persister task started"])
        XCTAssertEqual(canExecuteChanged, 1, "only the admission has notified")
        XCTAssertEqual(form.model, "c")
        XCTAssertEqual(held.count, 1)

        for operation in held { await operation() }
        XCTAssertEqual(log.events, ["model message", "model message", "persister task started", "persisted"])
        XCTAssertEqual(canExecuteChanged, 2, "the settlement notified once")
        XCTAssertTrue(form.approveCommand.canExecute(), "the approval settled")
        XCTAssertEqual(form.model, "c")
    }
}
