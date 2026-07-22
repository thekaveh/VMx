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

private final class BlockingOwnershipParent: ParentVM, OwnershipParentVM, @unchecked Sendable {
    let entered = DispatchSemaphore(value: 0)
    let release = DispatchSemaphore(value: 0)
    let ownershipOwner: ComponentVMBase
    var ownershipOwnerParent: OwnershipParentVM? { nil }
    var supportsChildSelection: Bool { false }
    var currentChild: ComponentVMBase? { nil }

    init(owner: ComponentVMBase) { ownershipOwner = owner }
    func selectChild(_ vm: ComponentVMBase) {}
    func deselectChild(_ vm: ComponentVMBase) {}
    func containsIdentity(_ vm: ComponentVMBase) -> Bool { true }
    func detachForTransfer(_ vm: ComponentVMBase) throws -> ParentTransfer {
        entered.signal()
        guard release.wait(timeout: .now() + 2) == .success else {
            throw ContainerOwnershipError.inconsistentParent
        }
        return ParentTransfer(commit: {}, rollback: {})
    }
}

final class DisposalInvariantTests: XCTestCase {
    func testDisposalClosesChildAdmissionBeforeSnapshot() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let child = try ComponentVM.builder()
            .name("child").services(hub: hub, dispatcher: dispatcher).build()
        let late = try ComponentVM.builder()
            .name("late").services(hub: hub, dispatcher: dispatcher).build()
        let parent = try CompositeVM<ComponentVM>.builder()
            .name("parent").services(hub: hub, dispatcher: dispatcher)
            .children { [] }.build()
        parent.add(child)
        var admissionFailed = false
        let cancellable = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .sink { message in
                if message.senderName == "child", message.status == .disposed,
                   case .failure = parent.addResult(late) {
                    admissionFailed = true
                }
            }

        parent.dispose()

        XCTAssertTrue(admissionFailed)
        XCTAssertEqual(parent.count, 1)
        XCTAssertEqual(late.status, .destructed)
        cancellable.cancel()
    }

    func testFactoryOutputAfterReentrantDisposalIsRejected() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let lateComposite = try ComponentVM.builder()
            .name("late-composite").services(hub: hub, dispatcher: dispatcher).build()
        var composite: CompositeVM<ComponentVM>!
        composite = try CompositeVM<ComponentVM>.builder()
            .name("composite").services(hub: hub, dispatcher: dispatcher)
            .children {
                composite.dispose()
                return [lateComposite]
            }.build()

        XCTAssertThrowsError(try composite.construct())
        XCTAssertEqual(composite.count, 0)
        XCTAssertEqual(lateComposite.status, .destructed)

        let lateGroup = try ComponentVM.builder()
            .name("late-group").services(hub: hub, dispatcher: dispatcher).build()
        var group: GroupVM<ComponentVM>!
        group = try GroupVM<ComponentVM>.builder()
            .name("group").services(hub: hub, dispatcher: dispatcher)
            .children {
                group.dispose()
                return [lateGroup]
            }.build()

        XCTAssertThrowsError(try group.construct())
        XCTAssertEqual(group.count, 0)
        XCTAssertEqual(lateGroup.status, .destructed)
    }

    func testFactoryPopulationRejectsDuplicateIdentityInBothContainers() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let child = try ComponentVM.builder()
            .name("duplicate").services(hub: hub, dispatcher: dispatcher).build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite").services(hub: hub, dispatcher: dispatcher)
            .children { [child, child] }.build()
        let group = try GroupVM<ComponentVM>.builder()
            .name("group").services(hub: hub, dispatcher: dispatcher)
            .children { [child, child] }.build()

        XCTAssertThrowsError(try composite.construct())
        XCTAssertThrowsError(try group.construct())
        XCTAssertTrue(composite.snapshot().isEmpty)
        XCTAssertTrue(group.snapshot().isEmpty)
    }

    func testAutoConstructHookCannotReparentBeforeAdmissionCommits() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let source = try CompositeVM<ComponentVM>.builder()
            .name("source").services(hub: hub, dispatcher: dispatcher)
            .autoConstructOnAdd(true).children { [] }.build()
        let destination = try GroupVM<ComponentVM>.builder()
            .name("destination").services(hub: hub, dispatcher: dispatcher)
            .children { [] }.build()
        var child: ComponentVM!
        child = try ComponentVM.builder().name("child")
            .services(hub: hub, dispatcher: dispatcher)
            .onConstruct {
                if case .failure(let error) = destination.addResult(child) { throw error }
            }.build()
        try source.construct()

        if case .success = source.addResult(child) {
            XCTFail("nested reparenting must fail the outer admission")
        }
        XCTAssertTrue(source.snapshot().isEmpty)
        XCTAssertTrue(destination.snapshot().isEmpty)
        XCTAssertNil(child._ownershipParent)
    }

    func testConcurrentCompositeAndGroupAdmissionCannotEscapeDisposalSnapshot() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE

        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite").services(hub: hub, dispatcher: dispatcher)
            .children { [] }.build()
        let compositeChild = try ComponentVM.builder()
            .name("composite-child").services(hub: hub, dispatcher: dispatcher).build()
        let compositeBlocker = BlockingOwnershipParent(owner: compositeChild)
        compositeChild._parent = compositeBlocker
        compositeChild._ownershipParent = compositeBlocker
        let compositeDone = expectation(description: "composite admission returned")
        DispatchQueue.global().async {
            if case .success = composite.addResult(compositeChild) {
                XCTFail("admission racing disposal must fail")
            }
            compositeDone.fulfill()
        }
        XCTAssertEqual(compositeBlocker.entered.wait(timeout: .now() + 2), .success)
        composite.dispose()
        compositeBlocker.release.signal()

        let group = try GroupVM<ComponentVM>.builder()
            .name("group").services(hub: hub, dispatcher: dispatcher)
            .children { [] }.build()
        let groupChild = try ComponentVM.builder()
            .name("group-child").services(hub: hub, dispatcher: dispatcher).build()
        let groupBlocker = BlockingOwnershipParent(owner: groupChild)
        groupChild._parent = groupBlocker
        groupChild._ownershipParent = groupBlocker
        let groupDone = expectation(description: "group admission returned")
        DispatchQueue.global().async {
            if case .success = group.addResult(groupChild) {
                XCTFail("admission racing disposal must fail")
            }
            groupDone.fulfill()
        }
        XCTAssertEqual(groupBlocker.entered.wait(timeout: .now() + 2), .success)
        group.dispose()
        groupBlocker.release.signal()

        wait(for: [compositeDone, groupDone], timeout: 2)
        XCTAssertTrue(composite.snapshot().isEmpty)
        XCTAssertTrue(group.snapshot().isEmpty)
    }

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
