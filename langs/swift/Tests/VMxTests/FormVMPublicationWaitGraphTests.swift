//
// FormVMPublicationWaitGraphTests.swift — #1170 regression tests.
//
// Thread Y drains hub `H`, and its subscriber waits until thread X publishes
// a form notification. X's sink then sends on `H`, and Y's subscriber calls
// `setModel`, deny or `dispose()` on the form. X's send waits for Y's drain,
// and Y's call waits for X's publication scope. The form wait now records an
// edge in `ThreadWaitGraph`, so the wait that closes the cycle is refused
// (spec/20 §5.5, ADR-0176):
//
// - Hub wait first: Y's form wait is refused. Y's update joins X's queue and
//   replays when X's scope ends, or Y's disposal is left to X.
// - Form wait first: X's send is refused and enqueues for Y's drain
//   (ADR-0119). Y's call proceeds when X's scope ends.
//
// Each test forces one arrival order through the test seams. Every wait is
// bounded by `hangGuard`, so a stall fails the test instead of hanging the
// run. No conformance ID: this is a flavor-local repair.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private struct Ping: Message {
    let senderObject: AnyObject
    let senderName: String
}

/// Where X's sink runs.
private enum PublisherSink {
    /// `setModel("bad")` on a validated form: the update's `errorsChanged`.
    case errorsChanged
    /// A successful approval's `onApproved`.
    case onApproved
    /// A successful approval's `onApproved`, which calls `setModel` on a form
    /// whose hub is `H`. No consumer code sends on `H`.
    case onApprovedSetModel
    /// The `errorsChanged` of an approval whose `resetOnApproved` returns
    /// `"bad"`.
    case reset
    /// The settlement `canExecuteChanged` of a successful approval.
    case settlement
}

/// What Y's subscriber calls on the form.
private enum DrainerCall {
    case setModel
    case deny
    case dispose
}

/// Which wait the test lets record first.
private enum Arrival {
    /// X's `H.send` waits for Y's drain before Y calls the form.
    case hubWaitFirst
    /// Y's form wait is recorded before X sends on `H`.
    case formWaitFirst
}

/// Thread-safe counters and flags shared by the sinks.
private final class Observations: @unchecked Sendable {
    private let lock = NSLock()
    private var deliveries: [String: Int] = [:]
    private var finished: Set<String> = []
    private var drainerThread: UInt64 = 0

    func deliver(to subscriber: String) {
        lock.lock()
        deliveries[subscriber, default: 0] += 1
        lock.unlock()
    }

    func deliveries(to subscriber: String) -> Int {
        lock.lock()
        defer { lock.unlock() }
        return deliveries[subscriber] ?? 0
    }

    func finish(_ channel: String) {
        lock.lock()
        finished.insert(channel)
        lock.unlock()
    }

    func isFinished(_ channel: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return finished.contains(channel)
    }

    var drainer: UInt64 {
        get { lock.lock(); defer { lock.unlock() }; return drainerThread }
        set { lock.lock(); drainerThread = newValue; lock.unlock() }
    }
}

/// Lets a callback act once.
private final class Once: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    /// `true` on the `n`th call only.
    func isCall(_ n: Int) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        count += 1
        return count == n
    }
}

final class FormVMPublicationWaitGraphTests: XCTestCase {
    private var cancellables = Set<AnyCancellable>()

    override func tearDown() {
        ThreadWaitGraph.shared.onWaitDecidedForTesting = nil
        cancellables.removeAll()
        super.tearDown()
    }

    @discardableResult
    private func wait(
        _ semaphore: DispatchSemaphore,
        _ message: String,
        file: StaticString,
        line: UInt
    ) -> Bool {
        let result = semaphore.wait(timeout: .now() + hangGuard)
        XCTAssertEqual(result, .success, message, file: file, line: line)
        return result == .success
    }

    private func run(
        _ sink: PublisherSink,
        _ call: DrainerCall,
        _ arrival: Arrival,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let hub = MessageHub()
        let observations = Observations()
        let rejectBad: [String: (String) -> String?] = ["value": { $0 == "bad" ? "rejected" : nil }]
        let form: FormVM<String>
        switch sink {
        case .errorsChanged:
            form = FormVM(initial: "saved", persister: { _ in }, validators: rejectBad)
        case .onApproved, .settlement:
            form = FormVM(initial: "saved", persister: { _ in })
            form.setModel("edited")
        case .onApprovedSetModel:
            form = FormVM(initial: "saved", persister: { _ in }, hub: hub)
            // Dirty the form before the hub counters subscribe.
            form.setModel("edited")
        case .reset:
            form = FormVM(
                initial: "saved",
                persister: { _ in },
                validators: rejectBad,
                resetOnApproved: { _ in "bad" }
            )
            form.setModel("edited")
        }

        let drainerEntered = DispatchSemaphore(value: 0)
        let releaseDrainer = DispatchSemaphore(value: 0)
        let publisherWaitsOnHub = DispatchSemaphore(value: 0)
        let drainerWaitsOnForm = DispatchSemaphore(value: 0)
        let publisherDone = DispatchSemaphore(value: 0)
        let drainerDone = DispatchSemaphore(value: 0)
        let boxedForm = UncheckedSendableBox(form)
        let boxedHub = UncheckedSendableBox(hub)

        switch arrival {
        case .hubWaitFirst:
            hub.onWaitRegisteredForTesting = { publisherWaitsOnHub.signal() }
        case .formWaitFirst:
            ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
                if accepted && caller == observations.drainer { drainerWaitsOnForm.signal() }
            }
        }

        // X's message on `H`: a ping, or the nested update's model message.
        func isPublisherMessage(_ message: any Message) -> Bool {
            if sink == .onApprovedSetModel {
                return (message as? PropertyChangedMessage)?.propertyName == "model"
            }
            return message.senderName == "publisher"
        }

        // Y's subscriber: once Y holds the drain, it waits for X's sink, then
        // calls the form.
        hub.messages
            .sink { message in
                if isPublisherMessage(message) { observations.deliver(to: "drainer subscriber") }
                guard message.senderName == "drainer" else { return }
                drainerEntered.signal()
                _ = releaseDrainer.wait(timeout: .now() + hangGuard * 2)
                if arrival == .hubWaitFirst {
                    _ = publisherWaitsOnHub.wait(timeout: .now() + hangGuard)
                }
                switch call {
                case .setModel: boxedForm.value.setModel("y")
                case .deny: boxedForm.value.denyCommand.execute()
                case .dispose: boxedForm.value.dispose()
                }
            }
            .store(in: &cancellables)
        hub.messages
            .sink { message in
                if isPublisherMessage(message) { observations.deliver(to: "second subscriber") }
            }
            .store(in: &cancellables)
        form.onApproved
            .sink(receiveCompletion: { _ in observations.finish("onApproved") }, receiveValue: { _ in })
            .store(in: &cancellables)
        form.errorsChanged
            .sink(receiveCompletion: { _ in observations.finish("errorsChanged") }, receiveValue: { _ in })
            .store(in: &cancellables)

        // X's sink: release Y, then send on `H` while X's scope is open.
        let once = Once()
        let publish: () -> Void = {
            releaseDrainer.signal()
            if arrival == .formWaitFirst {
                _ = drainerWaitsOnForm.wait(timeout: .now() + hangGuard)
            }
            if sink == .onApprovedSetModel {
                boxedForm.value.setModel("nested")
            } else {
                boxedHub.value.send(Ping(senderObject: NSObject(), senderName: "publisher"))
            }
        }
        switch sink {
        case .errorsChanged, .reset:
            form.errorsChanged.sink { _ in if once.isCall(1) { publish() } }.store(in: &cancellables)
        case .onApproved, .onApprovedSetModel:
            form.onApproved.sink { _ in if once.isCall(1) { publish() } }.store(in: &cancellables)
        case .settlement:
            // The admission notification comes first, then the settlement.
            form.approveCommand.canExecuteChanged
                .sink { _ in if once.isCall(2) { publish() } }
                .store(in: &cancellables)
        }

        Thread {
            observations.drainer = ThreadWaitGraph.currentThread
            boxedHub.value.send(Ping(senderObject: NSObject(), senderName: "drainer"))
            drainerDone.signal()
        }.start()
        guard wait(drainerEntered, "Y never took the drain", file: file, line: line) else { return }

        switch sink {
        case .errorsChanged:
            Thread {
                boxedForm.value.setModel("bad")
                publisherDone.signal()
            }.start()
        case .onApproved, .onApprovedSetModel, .reset, .settlement:
            Task.detached {
                try? await boxedForm.value.approveAsync()
                publisherDone.signal()
            }
        }

        // A stalled pair leaves both threads blocked, so return before
        // reading the form.
        guard wait(publisherDone, "thread X stalled", file: file, line: line),
              wait(drainerDone, "thread Y stalled", file: file, line: line)
        else { return }

        // Y's call is not lost.
        switch call {
        case .setModel:
            XCTAssertEqual(form.model, "y", file: file, line: line)
        case .deny:
            XCTAssertEqual(form.model, form.snapshot, file: file, line: line)
        case .dispose:
            XCTAssertTrue(observations.isFinished("onApproved"), file: file, line: line)
            XCTAssertTrue(observations.isFinished("errorsChanged"), file: file, line: line)
        }
        // Each X send reaches every subscriber exactly once. With the nested
        // update, Y's `setModel("y")` publishes the second model message.
        let expected = sink == .onApprovedSetModel ? 2 : 1
        XCTAssertEqual(observations.deliveries(to: "drainer subscriber"), expected, file: file, line: line)
        XCTAssertEqual(observations.deliveries(to: "second subscriber"), expected, file: file, line: line)
    }

    // ── errorsChanged ─────────────────────────────────────────────────────────

    func testErrorsChangedSendWhileDrainerSetsModelHubWaitFirst() {
        run(.errorsChanged, .setModel, .hubWaitFirst)
    }

    func testErrorsChangedSendWhileDrainerSetsModelFormWaitFirst() {
        run(.errorsChanged, .setModel, .formWaitFirst)
    }

    func testErrorsChangedSendWhileDrainerDeniesHubWaitFirst() {
        run(.errorsChanged, .deny, .hubWaitFirst)
    }

    func testErrorsChangedSendWhileDrainerDeniesFormWaitFirst() {
        run(.errorsChanged, .deny, .formWaitFirst)
    }

    func testErrorsChangedSendWhileDrainerDisposesHubWaitFirst() {
        run(.errorsChanged, .dispose, .hubWaitFirst)
    }

    func testErrorsChangedSendWhileDrainerDisposesFormWaitFirst() {
        run(.errorsChanged, .dispose, .formWaitFirst)
    }

    // ── onApproved ────────────────────────────────────────────────────────────

    func testApprovedSendWhileDrainerSetsModelHubWaitFirst() {
        run(.onApproved, .setModel, .hubWaitFirst)
    }

    func testApprovedSendWhileDrainerSetsModelFormWaitFirst() {
        run(.onApproved, .setModel, .formWaitFirst)
    }

    func testApprovedSendWhileDrainerDeniesHubWaitFirst() {
        run(.onApproved, .deny, .hubWaitFirst)
    }

    func testApprovedSendWhileDrainerDeniesFormWaitFirst() {
        run(.onApproved, .deny, .formWaitFirst)
    }

    func testApprovedSendWhileDrainerDisposesHubWaitFirst() {
        run(.onApproved, .dispose, .hubWaitFirst)
    }

    func testApprovedSendWhileDrainerDisposesFormWaitFirst() {
        run(.onApproved, .dispose, .formWaitFirst)
    }

    // ── onApproved calls setModel on a form whose hub is H ────────────────────

    func testApprovedNestedSetModelWhileDrainerSetsModelHubWaitFirst() {
        run(.onApprovedSetModel, .setModel, .hubWaitFirst)
    }

    func testApprovedNestedSetModelWhileDrainerSetsModelFormWaitFirst() {
        run(.onApprovedSetModel, .setModel, .formWaitFirst)
    }

    // ── Approval reset ────────────────────────────────────────────────────────

    func testResetErrorsChangedSendWhileDrainerSetsModelHubWaitFirst() {
        run(.reset, .setModel, .hubWaitFirst)
    }

    func testResetErrorsChangedSendWhileDrainerSetsModelFormWaitFirst() {
        run(.reset, .setModel, .formWaitFirst)
    }

    // ── Settlement canExecuteChanged ──────────────────────────────────────────

    func testSettlementCanExecuteSendWhileDrainerSetsModelHubWaitFirst() {
        run(.settlement, .setModel, .hubWaitFirst)
    }

    func testSettlementCanExecuteSendWhileDrainerSetsModelFormWaitFirst() {
        run(.settlement, .setModel, .formWaitFirst)
    }

    // ── Waits without a cycle ─────────────────────────────────────────────────

    /// Runs `call` on another thread while the publisher's sink blocks, and
    /// checks that the call returns only after that sink. `attach` installs a
    /// sink that runs `block` once, inside the publication scope.
    private func assertWaitsForScope(
        _ form: FormVM<String>,
        attach: (@escaping () -> Void) -> Void,
        call: @escaping (FormVM<String>) -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let publisherEntered = DispatchSemaphore(value: 0)
        let releasePublisher = DispatchSemaphore(value: 0)
        let approvalDone = DispatchSemaphore(value: 0)
        let callDone = DispatchSemaphore(value: 0)
        let orderLock = NSLock()
        var order: [String] = []
        func record(_ event: String) {
            orderLock.lock()
            order.append(event)
            orderLock.unlock()
        }
        attach {
            publisherEntered.signal()
            _ = releasePublisher.wait(timeout: .now() + hangGuard * 2)
            record("publisher sink returned")
        }

        let boxedForm = UncheckedSendableBox(form)
        Task.detached {
            try? await boxedForm.value.approveAsync()
            approvalDone.signal()
        }
        guard wait(publisherEntered, "the publisher sink never ran", file: file, line: line) else { return }
        Thread {
            call(boxedForm.value)
            record("call returned")
            callDone.signal()
        }.start()
        let early = callDone.wait(timeout: .now() + 0.2)
        XCTAssertEqual(early, .timedOut, "the call waits for the publication scope", file: file, line: line)
        releasePublisher.signal()
        guard wait(approvalDone, "the approval stalled", file: file, line: line),
              early == .success || wait(callDone, "the call stalled", file: file, line: line)
        else { return }
        orderLock.lock()
        let observed = order
        orderLock.unlock()
        XCTAssertEqual(observed, ["publisher sink returned", "call returned"], file: file, line: line)
    }

    /// Another thread's approval admission waits for a settlement scope, as
    /// in C# and Python (spec/20 §5.5).
    func testAnotherThreadsAdmissionWaitsForTheSettlementScope() {
        let form = FormVM<String>(initial: "saved", persister: { _ in })
        form.setModel("edited")
        let once = Once()
        assertWaitsForScope(
            form,
            attach: { block in
                form.onApproved
                    .sink { _ in if once.isCall(1) { block() } }
                    .store(in: &cancellables)
            },
            call: { $0.approveCommand.execute() }
        )
    }

    /// A failed settlement holds a scope over its `canExecuteChanged`, so
    /// another thread's `setModel` waits for that delivery (spec/20 §5.5).
    func testAnotherThreadsSetModelWaitsForAFailedSettlementScope() {
        struct PersistFailure: Error {}
        let form = FormVM<String>(initial: "saved", persister: { _ in throw PersistFailure() })
        form.setModel("edited")
        let once = Once()
        assertWaitsForScope(
            form,
            attach: { block in
                // The admission notification comes first, then the
                // failed settlement's.
                form.approveCommand.canExecuteChanged
                    .sink { _ in if once.isCall(2) { block() } }
                    .store(in: &cancellables)
            },
            call: { $0.setModel("after") }
        )
        XCTAssertEqual(form.model, "after")
    }

    // ── A nested call meets another thread's scope (spec/20 §5.4, #1472) ──────

    /// Thread Y holds the drain of hub `H`. Thread X's `setModel("bad")`
    /// delivers `errorsChanged` in its scope, and X's sink sends on `H`, so the
    /// send waits for Y. Y's subscriber then calls `setModel("outer")`. Its
    /// wait for X's scope closes a cycle and is refused, so the call prepares
    /// at once (spec/20 §5.5). Y's validator then makes the nested call, which
    /// never waits for X's scope (spec/20 §5.4). `onWaitDecidedForTesting`
    /// records every wait request, accepted or refused.
    private func runNestedCall(
        dispose: Bool,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> (run: NestedRun, form: FormVM<String>)? {
        let hub = MessageHub()
        let formHub = MessageHub()
        let run = NestedRun()
        let form = FormVM<String>(
            initial: "initial",
            persister: { _ in },
            hub: formHub,
            validators: ["value": { value in
                if value == "outer" && ThreadWaitGraph.currentThread == run.drainer {
                    run.nestedCall {
                        guard let form = run.target else { return }
                        if dispose {
                            form.dispose()
                        } else {
                            form.setModel("nested")
                            run.modelAfterNestedCall = form.model
                        }
                    }
                }
                return value == "bad" ? "rejected" : nil
            }]
        )
        run.target = form
        let boxedForm = UncheckedSendableBox(form)
        let boxedHub = UncheckedSendableBox(hub)
        let drainerEntered = DispatchSemaphore(value: 0)
        let releaseDrainer = DispatchSemaphore(value: 0)
        let publisherWaitsOnHub = DispatchSemaphore(value: 0)
        let publisherDone = DispatchSemaphore(value: 0)
        let drainerDone = DispatchSemaphore(value: 0)

        hub.onWaitRegisteredForTesting = { publisherWaitsOnHub.signal() }
        ThreadWaitGraph.shared.onWaitDecidedForTesting = { caller, accepted in
            if caller == run.drainer { run.recordRequest(accepted) }
        }
        form.onApproved
            .sink(receiveCompletion: { _ in run.approvedCompleted() }, receiveValue: { _ in })
            .store(in: &cancellables)
        // X's update sends its `model` message after its outermost scope
        // closes (spec/20 §5.4).
        formHub.messages
            .sink { message in
                guard (message as? PropertyChangedMessage)?.propertyName == "model",
                      ThreadWaitGraph.currentThread == run.publisher
                else { return }
                run.publisherScopeClosed()
            }
            .store(in: &cancellables)
        hub.messages
            .sink { message in
                guard message.senderName == "drainer" else { return }
                drainerEntered.signal()
                _ = releaseDrainer.wait(timeout: .now() + graphTimeout)
                // X's hub send waits for Y before Y calls the form.
                _ = publisherWaitsOnHub.wait(timeout: .now() + graphTimeout)
                boxedForm.value.setModel("outer")
            }
            .store(in: &cancellables)
        let once = Once()
        form.errorsChanged
            .sink { _ in
                guard once.isCall(1) else { return }
                releaseDrainer.signal()
                // Y drains H, so this send waits for Y.
                boxedHub.value.send(Ping(senderObject: NSObject(), senderName: "publisher"))
                run.publisherSinkReturned()
            }
            .store(in: &cancellables)

        Thread {
            run.drainer = ThreadWaitGraph.currentThread
            boxedHub.value.send(Ping(senderObject: NSObject(), senderName: "drainer"))
            drainerDone.signal()
        }.start()
        guard wait(drainerEntered, "Y never took the drain", file: file, line: line) else { return nil }
        Thread {
            run.publisher = ThreadWaitGraph.currentThread
            boxedForm.value.setModel("bad")
            publisherDone.signal()
        }.start()

        // Both threads return within the fixed bound.
        guard wait(publisherDone, "thread X did not return: deadlock", file: file, line: line),
              wait(drainerDone, "thread Y did not return: deadlock", file: file, line: line)
        else { return nil }
        ThreadWaitGraph.shared.onWaitDecidedForTesting = nil

        XCTAssertTrue(run.requests.contains(false), "Y's outer wait is refused", file: file, line: line)
        XCTAssertEqual(run.nestedCalls, 1, file: file, line: line)
        XCTAssertEqual(run.publisherScopeOpenAfterNestedCall, true,
            "the nested call returns while X holds its scope", file: file, line: line)
        XCTAssertEqual(run.requestsDuringNestedCall, [],
            "a nested call makes no wait request", file: file, line: line)
        return (run, form)
    }

    /// The nested call joins X's queue and replays after X's scope ends.
    func testANestedSetModelNeverWaitsForAnotherThreadsScope() {
        guard let (run, form) = runNestedCall(dispose: false) else { return }

        XCTAssertNotNil(run.modelAfterNestedCall)
        XCTAssertNotEqual(run.modelAfterNestedCall, "nested",
            "the nested call returns before it takes effect")
        XCTAssertEqual(form.model, "nested", "the nested call replays after X's scope ends")
        XCTAssertTrue(form.isValid)
    }

    /// A nested dispose returns at once; `onApproved` completes after X's
    /// outermost scope closes.
    func testANestedDisposeNeverWaitsForAnotherThreadsScope() {
        guard let (run, _) = runNestedCall(dispose: true) else { return }

        XCTAssertEqual(run.approvedCompletions, [true],
            "onApproved completes once, after X's outermost scope closed and X sent its model message")
    }
}

/// What a nested call observed while another thread held a scope (#1472).
private final class NestedRun: @unchecked Sendable {
    private let lock = NSLock()
    private var drainerThread: UInt64 = 0
    private var publisherThread: UInt64 = 0
    private var allRequests: [Bool] = []
    private var nestedActive = false
    private var nestedRequests: [Bool] = []
    private var sinkReturned = false
    private var scopeClosed = false
    private var completions: [Bool] = []
    private var calls = 0
    private var scopeOpen: Bool?
    private var modelAfterNested: String?
    private weak var targetForm: FormVM<String>?

    /// The form under test; weak, because its validator captures this run.
    var target: FormVM<String>? {
        get { lock.withLock { targetForm } }
        set { lock.withLock { targetForm = newValue } }
    }

    var drainer: UInt64 {
        get { lock.withLock { drainerThread } }
        set { lock.withLock { drainerThread = newValue } }
    }

    var publisher: UInt64 {
        get { lock.withLock { publisherThread } }
        set { lock.withLock { publisherThread = newValue } }
    }

    var requests: [Bool] { lock.withLock { allRequests } }
    var requestsDuringNestedCall: [Bool] { lock.withLock { nestedRequests } }
    var approvedCompletions: [Bool] { lock.withLock { completions } }
    var nestedCalls: Int { lock.withLock { calls } }
    var publisherScopeOpenAfterNestedCall: Bool? { lock.withLock { scopeOpen } }

    var modelAfterNestedCall: String? {
        get { lock.withLock { modelAfterNested } }
        set { lock.withLock { modelAfterNested = newValue } }
    }

    func recordRequest(_ accepted: Bool) {
        lock.withLock {
            allRequests.append(accepted)
            if nestedActive { nestedRequests.append(accepted) }
        }
    }

    func nestedCall(_ body: () -> Void) {
        lock.withLock {
            calls += 1
            nestedActive = true
        }
        body()
        lock.withLock {
            nestedActive = false
            scopeOpen = !sinkReturned
        }
    }

    func publisherSinkReturned() {
        lock.withLock { sinkReturned = true }
    }

    /// X's `model` message arrived, so X's outermost scope has closed.
    func publisherScopeClosed() {
        lock.withLock { scopeClosed = true }
    }

    func approvedCompleted() {
        lock.withLock { completions.append(scopeClosed) }
    }
}
