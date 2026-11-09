//
// FormVMUnscopedDeliveryTests.swift — #1228 regression tests.
//
// Thread A delivers a form notification that opens no publication scope: an
// approval admission's `canExecuteChanged`, or an `approveErrors` send.
// Thread B's `dispose()` does not wait for it. It marks the form disposed and
// returns, and the channels complete only after A's delivery returns, as in
// C# and Python (spec/20 §5.5, ADR-0176).
//
// Every wait is bounded by `hangGuard`, so a stall fails the test
// instead of hanging the run. No conformance ID: this is a flavor-local
// repair.
//

import Combine
import Foundation
import XCTest
@testable import VMx

/// Marks thread A, whose observer blocks.
private let blockingThread = "FormVMUnscopedDeliveryTests.threadA"

private struct PersistFailure: Error {}

/// Records which form channels completed.
private final class Completions: @unchecked Sendable {
    private let lock = NSLock()
    private var names: Set<String> = []

    func finish(_ name: String) {
        lock.lock()
        names.insert(name)
        lock.unlock()
    }

    var finished: Set<String> {
        lock.lock()
        defer { lock.unlock() }
        return names
    }
}

/// Lets one delivery block, once.
private final class Blocker: @unchecked Sendable {
    private let lock = NSLock()
    private var armed = true
    let entered = DispatchSemaphore(value: 0)
    let release = DispatchSemaphore(value: 0)
    private var completedOnReturn: Set<String>?

    func claim() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard armed else { return false }
        armed = false
        return true
    }

    /// Signals the test, then waits, bounded, until it releases this
    /// delivery. Records the channels that had completed when it returns.
    func block(_ completions: Completions) {
        entered.signal()
        _ = release.wait(timeout: .now() + hangGuard * 2)
        lock.lock()
        completedOnReturn = completions.finished
        lock.unlock()
    }

    var finishedOnReturn: Set<String>? {
        lock.lock()
        defer { lock.unlock() }
        return completedOnReturn
    }
}

final class FormVMUnscopedDeliveryTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()
    private let channels: Set<String> = ["onApproved", "approveErrors", "errorsChanged"]

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func watchCompletions(_ form: FormVM<String>) -> Completions {
        let completions = Completions()
        form.onApproved
            .sink(receiveCompletion: { _ in completions.finish("onApproved") }, receiveValue: { _ in })
            .store(in: &cancellables)
        form.approveErrors
            .sink(receiveCompletion: { _ in completions.finish("approveErrors") }, receiveValue: { _ in })
            .store(in: &cancellables)
        form.errorsChanged
            .sink(receiveCompletion: { _ in completions.finish("errorsChanged") }, receiveValue: { _ in })
            .store(in: &cancellables)
        return completions
    }

    /// Waits until `blocker` holds A's delivery, disposes the form on thread
    /// B, and checks that no channel completes before A's delivery returns.
    private func disposeDuringBlockedDelivery(
        _ form: FormVM<String>,
        _ blocker: Blocker,
        _ completions: Completions,
        aDone: DispatchSemaphore,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        guard blocker.entered.wait(timeout: .now() + hangGuard) == .success else {
            XCTFail("A's observer never ran", file: file, line: line)
            return
        }
        let bDone = DispatchSemaphore(value: 0)
        let boxedForm = UncheckedSendableBox(form)
        Thread {
            boxedForm.value.dispose()
            bDone.signal()
        }.start()
        let bReturned = bDone.wait(timeout: .now() + hangGuard) == .success
        let finishedAtDisposeReturn = completions.finished
        blocker.release.signal()
        let aReturned = aDone.wait(timeout: .now() + hangGuard) == .success

        XCTAssertTrue(bReturned, "B's dispose() returns without waiting", file: file, line: line)
        XCTAssertTrue(aReturned, "A's delivery returns", file: file, line: line)
        XCTAssertEqual(
            finishedAtDisposeReturn, [],
            "B's dispose() completed a channel during A's delivery", file: file, line: line
        )
        XCTAssertEqual(
            blocker.finishedOnReturn, [],
            "a channel completed before A's observer returned", file: file, line: line
        )
        XCTAssertFalse(form.approveCommand.canExecute(), file: file, line: line)
        // The deferred teardown runs on A right after its delivery returns.
        let deadline = Date().addingTimeInterval(hangGuard)
        while completions.finished != channels, Date() < deadline {
            Thread.sleep(forTimeInterval: 0.001)
        }
        XCTAssertEqual(
            completions.finished, channels,
            "the channels complete after A's delivery", file: file, line: line
        )
    }

    /// #1228 — B's `dispose()` during A's admission `canExecuteChanged`.
    func testDisposeDuringAdmissionNotificationCompletesChannelsAfterIt() {
        let persisted = DispatchSemaphore(value: 0)
        let form = FormVM<String>(initial: "valid", persister: { _ in persisted.signal() })
        let completions = watchCompletions(form)
        let blocker = Blocker()
        form.approveCommand.canExecuteChanged
            .sink { _ in
                guard Thread.current.threadDictionary[blockingThread] as? Bool == true,
                      blocker.claim()
                else { return }
                blocker.block(completions)
            }
            .store(in: &cancellables)

        let aDone = DispatchSemaphore(value: 0)
        let boxedForm = UncheckedSendableBox(form)
        Thread {
            Thread.current.threadDictionary[blockingThread] = true
            boxedForm.value.approveCommand.execute()
            aDone.signal()
        }.start()
        disposeDuringBlockedDelivery(form, blocker, completions, aDone: aDone)
        // A form disposed during admission never starts its persister.
        XCTAssertEqual(persisted.wait(timeout: .now() + 0.2), .timedOut)
    }

    /// #1228 — B's `dispose()` during A's `approveErrors` send.
    func testDisposeDuringApproveErrorsSendCompletesChannelsAfterIt() {
        let form = FormVM<String>(initial: "valid", persister: { _ in throw PersistFailure() })
        let completions = watchCompletions(form)
        let blocker = Blocker()
        let aDone = DispatchSemaphore(value: 0)
        form.approveErrors
            .sink { _ in
                guard blocker.claim() else { return }
                blocker.block(completions)
                aDone.signal()
            }
            .store(in: &cancellables)

        form.approveCommand.execute()
        disposeDuringBlockedDelivery(form, blocker, completions, aDone: aDone)
    }
}
