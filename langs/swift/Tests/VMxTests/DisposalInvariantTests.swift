import Combine
import Foundation
import XCTest
@testable import VMx

private final class LockedCounter: @unchecked Sendable {
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

final class DisposalInvariantTests: XCTestCase {
    /// DISP-001 — VM disposal and owned child cascades are observably idempotent.
    func testDisp001RepeatedParentDisposeEmitsOneTerminalTransitionPerNode() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let child = try ComponentVM.builder()
            .name("child").services(hub: hub, dispatcher: dispatcher).build()
        let parent = try CompositeVM<ComponentVM>.builder()
            .name("parent").services(hub: hub, dispatcher: dispatcher)
            .children { [child] }.build()
        try parent.construct()
        var disposed: [String] = []
        let cancellable = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .sink { if $0.status == .disposed { disposed.append($0.senderName) } }

        parent.dispose()
        parent.dispose()

        XCTAssertEqual(disposed.filter { $0 == "child" }.count, 1)
        XCTAssertEqual(disposed.filter { $0 == "parent" }.count, 1)
        cancellable.cancel()
    }

    /// DISP-002 — command disposal is idempotent and cancels in-flight work.
    func testDisp002RepeatedAsyncCommandDisposeCancelsOneInFlightRun() async {
        let started = expectation(description: "command started")
        let cancellations = LockedCounter()
        let command = AsyncRelayCommand.builder()
            .task {
                started.fulfill()
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 1_000_000)
                }
                cancellations.increment()
                try Task.checkCancellation()
            }
            .build()
        let run = Task<Void, Error> { try await command.executeAsync() }
        await fulfillment(of: [started], timeout: 2.0)

        command.dispose()
        command.dispose()
        do {
            try await run.value
        } catch {
            XCTFail("default disposal cancellation must complete without throwing: \(error)")
        }

        XCTAssertEqual(cancellations.value, 1)
        XCTAssertFalse(command.canExecute())
    }

    /// DISP-003 — concurrent disposal of a thread-safe hub performs terminal work once.
    func testDisp003ConcurrentNotificationHubDisposeCompletesOnce() async {
        let hub = NotificationHub()
        let notification = VMx.Notification(type: .notification, message: "info")
        let appeared = expectation(description: "notification appeared")
        appeared.assertForOverFulfill = false
        let completions = LockedCounter()
        var cancellables = Set<AnyCancellable>()
        hub.pending.sink(
            receiveCompletion: { _ in completions.increment() },
            receiveValue: { snapshot in
                if snapshot.contains(where: { $0 === notification }) {
                    appeared.fulfill()
                }
            }
        ).store(in: &cancellables)
        let pending = Task { await hub.post(notification) }
        await fulfillment(of: [appeared], timeout: 2.0)

        let disposed = expectation(description: "all disposers returned")
        disposed.expectedFulfillmentCount = 64
        for _ in 0..<64 {
            DispatchQueue.global().async {
                hub.dispose()
                disposed.fulfill()
            }
        }
        await fulfillment(of: [disposed], timeout: 2.0)

        let pendingResult = await pending.value
        XCTAssertEqual(pendingResult, .pending)
        XCTAssertEqual(completions.value, 1)
    }

    /// DISP-004 — interaction owners complete once and preserve the first result.
    func testDisp004InteractionOwnersCompleteOnceAndPreserveFirstResult() async {
        let form = FormVM(initial: 1, persister: { _ in })
        let completions = LockedCounter()
        let cancellable = form.onApproved.sink(
            receiveCompletion: { _ in completions.increment() },
            receiveValue: { _ in }
        )
        form.dispose()
        form.dispose()
        XCTAssertEqual(completions.value, 1)
        cancellable.cancel()

        let modal = BasicModalVM(cancellationResult: "cancel")
        modal.dismiss("first")
        modal.dispose()
        modal.dispose()
        let modalResult = await modal.waitResult()
        XCTAssertEqual(modalResult, "first")
    }

    /// DISP-005 — reactive helper disposal completes once and retains the last value.
    func testDisp005ReactiveHelperCompletesOnceAndRetainsLastValue() throws {
        let source = CurrentValueSubject<Int, Never>(7)
        let property = DerivedProperty<Int>.from(source.eraseToAnyPublisher()) { $0 }
        let completions = LockedCounter()
        let cancellable = property.valueChanged.sink(
            receiveCompletion: { _ in completions.increment() },
            receiveValue: { _ in }
        )

        property.dispose()
        property.dispose()
        source.send(8)

        XCTAssertEqual(try property.value, 7)
        XCTAssertEqual(completions.value, 1)
        cancellable.cancel()
    }

    /// DISP-006 — disposable collection helpers end one batch exactly once.
    func testDisp006BatchHandleEndsOneBatchOnce() throws {
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite").withNullServices().children { [] }.build()
        try composite.construct()
        var events: [CollectionChangedEvent] = []
        let cancellable = composite.collectionChanged.sink { events.append($0) }
        let handle = composite.batchUpdate()
        let child = try ComponentVM.builder().name("child").withNullServices().build()
        composite.add(child)

        handle.dispose()
        handle.dispose()

        XCTAssertEqual(events.map(\.action), [.reset])
        cancellable.cancel()
    }
}
