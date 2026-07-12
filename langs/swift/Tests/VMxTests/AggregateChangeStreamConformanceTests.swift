import Combine
import Foundation
import XCTest
@testable import VMx

private struct CrossThreadOncePublisher: Publisher {
    typealias Output = Void
    typealias Failure = Never

    func receive<S: Subscriber>(subscriber: S)
    where S.Input == Void, S.Failure == Never {
        subscriber.receive(subscription: CrossThreadOnceSubscription(subscriber))
    }
}

private final class CrossThreadOnceSubscription<S: Subscriber>: Subscription
where S.Input == Void, S.Failure == Never {
    private var subscriber: S?
    private var emitted = false

    init(_ subscriber: S) { self.subscriber = subscriber }

    func request(_ demand: Subscribers.Demand) {
        guard demand > .none, !emitted, let subscriber else { return }
        emitted = true
        let delivered = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            _ = subscriber.receive(())
            subscriber.receive(completion: .finished)
            delivered.signal()
        }
        precondition(delivered.wait(timeout: .now() + 2) == .success)
    }

    func cancel() { subscriber = nil }
}

private struct HookCoordinatedPublisher: Publisher {
    typealias Output = Void
    typealias Failure = Never
    let hookEntered: DispatchSemaphore

    func receive<S: Subscriber>(subscriber: S)
    where S.Input == Void, S.Failure == Never {
        subscriber.receive(subscription: HookCoordinatedSubscription(
            subscriber,
            hookEntered: hookEntered
        ))
    }
}

private final class HookCoordinatedSubscription<S: Subscriber>: Subscription
where S.Input == Void, S.Failure == Never {
    private var subscriber: S?
    private let hookEntered: DispatchSemaphore
    private var emitted = false

    init(_ subscriber: S, hookEntered: DispatchSemaphore) {
        self.subscriber = subscriber
        self.hookEntered = hookEntered
    }

    func request(_ demand: Subscribers.Demand) {
        guard demand > .none, !emitted, let subscriber else { return }
        emitted = true
        DispatchQueue.global().async { _ = subscriber.receive(()) }
        precondition(hookEntered.wait(timeout: .now() + 2) == .success)
    }

    func cancel() { subscriber = nil }
}

private final class AggregateTestChanges {
    private let subject = PassthroughSubject<Void, Never>()
    var subscribeCount = 0
    var cancelCount = 0
    var emitOnSubscribe = false
    var emitCrossThreadOnSubscribe = false

    var publisher: AnyPublisher<Void, Never> {
        let selected: AnyPublisher<Void, Never>
        if emitCrossThreadOnSubscribe {
            selected = CrossThreadOncePublisher().append(subject).eraseToAnyPublisher()
        } else if emitOnSubscribe {
            selected = Just(()).append(subject).eraseToAnyPublisher()
        } else {
            selected = subject.eraseToAnyPublisher()
        }
        return selected
            .handleEvents(
                receiveSubscription: { [weak self] _ in
                    self?.subscribeCount += 1
                },
                receiveCancel: { [weak self] in self?.cancelCount += 1 }
            )
            .eraseToAnyPublisher()
    }

    func emit() { subject.send(()) }
    func complete() { subject.send(completion: .finished) }
}

private final class AggregateTestItem {
    let name: String
    let changes = AggregateTestChanges()
    var disposeCount = 0

    init(_ name: String) { self.name = name }
    func dispose() { disposeCount += 1 }
}

private final class AggregateTestSource<Item: AnyObject>: ObservableMembershipSource {
    private let lock = NSRecursiveLock()
    private let membership = PassthroughSubject<Void, Never>()
    var items: [Item]
    var snapshotCount = 0
    var subscriptionCount = 0
    var cancellationCount = 0
    var snapshotOverride: (() -> [Item])?

    init(_ items: [Item] = []) { self.items = items }

    func snapshot() -> [Item] {
        lock.lock()
        defer { lock.unlock() }
        snapshotCount += 1
        return snapshotOverride?() ?? items
    }

    func subscribeMembership(_ callback: @escaping () -> Void) -> AnyCancellable {
        lock.lock()
        subscriptionCount += 1
        lock.unlock()
        let upstream = membership.sink { callback() }
        return AnyCancellable { [weak self] in
            upstream.cancel()
            self?.lock.lock()
            self?.cancellationCount += 1
            self?.lock.unlock()
        }
    }

    func pulse() { membership.send(()) }

    func add(_ item: Item) {
        items.append(item)
        pulse()
    }

    func remove(_ item: Item) {
        if let index = items.firstIndex(where: { $0 === item }) {
            items.remove(at: index)
        }
        pulse()
    }

    func move(from: Int, to: Int) {
        let item = items.remove(at: from)
        items.insert(item, at: to)
        pulse()
    }
}

private struct AggregateBodyError: Error, Equatable {}

private final class FiniteAggregateSubscriber<Item: AnyObject>: Subscriber {
    typealias Input = AggregateChange<Item>
    typealias Failure = Never

    private var subscription: Subscription?
    var values: [AggregateChange<Item>] = []

    func receive(subscription: Subscription) {
        self.subscription = subscription
        subscription.request(.max(1))
    }

    func receive(_ input: AggregateChange<Item>) -> Subscribers.Demand {
        values.append(input)
        return .none
    }

    func receive(completion: Subscribers.Completion<Never>) {
        subscription = nil
    }

    func requestOne() { subscription?.request(.max(1)) }
    func cancel() { subscription?.cancel() }
}

final class AggregateChangeStreamConformanceTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    private func aggregate(
        _ source: AggregateTestSource<AggregateTestItem>
    ) -> AggregateChangeStream<AggregateTestItem> {
        AggregateChangeStream(source: source) { $0.changes.publisher }
    }

    private func observe(
        _ aggregate: AggregateChangeStream<AggregateTestItem>,
        emitInitial: Bool = false,
        into changes: inout [AggregateChange<AggregateTestItem>]
    ) {
        aggregate.observe(emitInitial: emitInitial)
            .sink { changes.append($0) }
            .store(in: &cancellables)
    }

    /// AGCH-001 — optional initial delivery is atomic and subscriber-local.
    func testAgch001AtomicSubscriberLocalInitial() {
        let source = AggregateTestSource([AggregateTestItem("first")])
        let sut = aggregate(source)
        var plain: [AggregateChange<AggregateTestItem>] = []
        var seeded: [AggregateChange<AggregateTestItem>] = []
        observe(sut, into: &plain)

        sut.observe(emitInitial: true).sink { change in
            seeded.append(change)
            if change.reason == .initial {
                source.add(AggregateTestItem("racing"))
            }
        }.store(in: &cancellables)

        XCTAssertEqual(seeded.map(\.reason), [.initial, .membership])
        XCTAssertEqual(plain.map(\.reason), [.membership])
        sut.dispose()
    }

    /// AGCH-002 — setup races reconcile and staged values follow membership.
    func testAgch002SetupRaceAndStagedOrdering() {
        let first = AggregateTestItem("first")
        let raced = AggregateTestItem("raced")
        let source = AggregateTestSource([first])
        var raceOnce = true
        source.snapshotOverride = {
            let snapshot = source.items
            if raceOnce {
                raceOnce = false
                source.items.append(raced)
                source.pulse()
            }
            return snapshot
        }

        let sut = aggregate(source)
        XCTAssertEqual(source.snapshotCount, 2)
        XCTAssertEqual(first.changes.subscribeCount, 1)
        XCTAssertEqual(raced.changes.subscribeCount, 1)

        var observed: [AggregateChange<AggregateTestItem>] = []
        observe(sut, into: &observed)
        let synchronous = AggregateTestItem("synchronous")
        synchronous.changes.emitOnSubscribe = true
        source.add(synchronous)

        XCTAssertEqual(observed.map(\.reason), [.membership, .item])
        XCTAssertTrue(observed.last?.item === synchronous)

        let crossThread = AggregateTestItem("cross-thread")
        crossThread.changes.emitCrossThreadOnSubscribe = true
        source.add(crossThread)
        XCTAssertEqual(
            observed.map(\.reason),
            [.membership, .item, .membership, .item]
        )
        XCTAssertTrue(observed.last?.item === crossThread)

        let orderedFirst = AggregateTestItem("ordered-first")
        let orderedSecond = AggregateTestItem("ordered-second")
        orderedFirst.changes.emitOnSubscribe = true
        orderedSecond.changes.emitOnSubscribe = true
        source.items.append(contentsOf: [orderedFirst, orderedSecond])
        source.pulse()
        XCTAssertEqual(
            observed.suffix(3).map(\.reason),
            [.membership, .item, .item]
        )
        XCTAssertTrue(observed[observed.count - 2].item === orderedFirst)
        XCTAssertTrue(observed.last?.item === orderedSecond)
        sut.dispose()

        let hookEnteredByPublisher = DispatchSemaphore(value: 0)
        let hookEnteredByTest = DispatchSemaphore(value: 0)
        let releaseHook = DispatchSemaphore(value: 0)
        let constructionFinished = DispatchSemaphore(value: 0)
        let raceItem = AggregateTestItem("atomic-stage")
        let raceSource = AggregateTestSource([raceItem])
        DispatchQueue.global().async {
            let raceAggregate = AggregateChangeStream(
                source: raceSource,
                observeItem: { _ in
                    HookCoordinatedPublisher(hookEntered: hookEnteredByPublisher)
                        .eraseToAnyPublisher()
                },
                _beforeStageRecord: {
                    hookEnteredByPublisher.signal()
                    hookEnteredByTest.signal()
                    _ = releaseHook.wait(timeout: .now() + 2)
                }
            )
            constructionFinished.signal()
            raceAggregate.dispose()
        }
        XCTAssertEqual(hookEnteredByTest.wait(timeout: .now() + 2), .success)
        XCTAssertEqual(
            constructionFinished.wait(timeout: .now() + 0.05),
            .timedOut,
            "activation must wait for atomic staging record"
        )
        releaseHook.signal()
        XCTAssertEqual(constructionFinished.wait(timeout: .now() + 2), .success)
    }

    /// AGCH-003 — selected changes identify the identical current member.
    func testAgch003ItemIdentity() {
        let item = AggregateTestItem("nested")
        let sut = aggregate(AggregateTestSource([item]))
        var observed: [AggregateChange<AggregateTestItem>] = []
        observe(sut, into: &observed)

        item.changes.emit()

        XCTAssertEqual(observed.map(\.reason), [.item])
        XCTAssertTrue(observed.first?.item === item)
        sut.dispose()
    }

    /// AGCH-004 — zero-refcount and completed membership epochs stay silent.
    func testAgch004TerminalEpochAndZeroRefcountSilence() throws {
        let first = AggregateTestItem("first")
        let second = AggregateTestItem("second")
        let source = ServicedObservableCollection<AggregateTestItem>()
        source.append(first)
        source.append(second)
        let sut = AggregateChangeStream(source: source) { $0.changes.publisher }
        var observed: [AggregateChange<AggregateTestItem>] = []
        sut.observe().sink { observed.append($0) }.store(in: &cancellables)

        first.changes.complete()
        first.changes.emit()
        XCTAssertTrue(observed.isEmpty)

        try source.move(from: 0, to: 1)
        source.replaceAll([second, first])
        source.append(first)
        XCTAssertEqual(first.changes.subscribeCount, 1)

        source.removeAt(1)
        source.removeAt(1)
        source.append(first)
        XCTAssertEqual(first.changes.subscribeCount, 2)
        sut.dispose()
    }

    /// AGCH-005 — Reset transactionally rebuilds keyed membership.
    func testAgch005KeyedResetRebuildsMembership() throws {
        let first = AggregateTestItem("first")
        let retained = AggregateTestItem("retained")
        let added = AggregateTestItem("added")
        let source = KeyedServicedObservableCollection<String, AggregateTestItem> {
            $0.name
        }
        try source.append(first)
        try source.append(retained)
        let sut = AggregateChangeStream(source: source) { $0.changes.publisher }
        var observed: [AggregateChange<AggregateTestItem>] = []
        sut.observe().sink { observed.append($0) }.store(in: &cancellables)

        try source.replaceAll([retained, added])

        XCTAssertEqual(observed.map(\.reason), [.membership])
        XCTAssertEqual(first.changes.cancelCount, 1)
        XCTAssertEqual(retained.changes.subscribeCount, 1)
        XCTAssertEqual(added.changes.subscribeCount, 1)
        added.changes.emit()
        XCTAssertTrue(observed.last?.item === added)
        sut.dispose()
    }

    /// AGCH-006 — duplicate identities share one refcounted subscription.
    func testAgch006DuplicateIdentityRefcount() {
        let item = AggregateTestItem("duplicate")
        let source = AggregateTestSource([item, item])
        let sut = aggregate(source)
        var observed: [AggregateChange<AggregateTestItem>] = []
        observe(sut, into: &observed)

        XCTAssertEqual(item.changes.subscribeCount, 1)
        item.changes.emit()
        XCTAssertEqual(observed.map(\.reason), [.item])
        source.remove(item)
        XCTAssertEqual(item.changes.cancelCount, 0)
        source.remove(item)
        XCTAssertEqual(item.changes.cancelCount, 1)
        sut.dispose()
    }

    /// AGCH-007 — nested exceptional batches emit once and preserve body failure.
    func testAgch007ExceptionalNestedBatch() {
        let item = AggregateTestItem("item")
        let source = AggregateTestSource([item])
        let sut = aggregate(source)
        var observed: [AggregateChange<AggregateTestItem>] = []
        observe(sut, into: &observed)

        XCTAssertThrowsError(try sut.withBatch {
            item.changes.emit()
            sut.withBatch { source.add(AggregateTestItem("added")) }
            throw AggregateBodyError()
        }) { XCTAssertEqual($0 as? AggregateBodyError, AggregateBodyError()) }

        XCTAssertEqual(observed.map(\.reason), [.batch])
        item.changes.emit()
        XCTAssertEqual(observed.map(\.reason), [.batch, .item])

        observed.removeAll()
        var late: [AggregateChange<AggregateTestItem>] = []
        sut.withBatch {
            item.changes.emit()
            observe(sut, into: &late)
        }
        XCTAssertEqual(observed.map(\.reason), [.batch])
        XCTAssertTrue(late.isEmpty, "a late subscriber must not receive historical batch work")

        let terminalItem = AggregateTestItem("terminal-race")
        let terminalSource = AggregateTestSource([terminalItem])
        var terminateBeforeGate = true
        let terminalAggregate = AggregateChangeStream(
            source: terminalSource,
            observeItem: { $0.changes.publisher },
            _beforeStageRecord: {},
            _beforeAdmittedGate: {
                if terminateBeforeGate {
                    terminateBeforeGate = false
                    terminalItem.changes.complete()
                }
            }
        )
        var terminalObserved: [AggregateChange<AggregateTestItem>] = []
        observe(terminalAggregate, into: &terminalObserved)
        terminalAggregate.withBatch { terminalItem.changes.emit() }
        XCTAssertTrue(
            terminalObserved.isEmpty,
            "an epoch ending before aggregate-gate admission must not dirty a batch"
        )
        terminalAggregate.dispose()
        sut.dispose()
    }

    /// AGCH-008 — empty batches are silent and Move preserves subscriptions.
    func testAgch008EmptyBatchAndMoveStability() throws {
        let first = AggregateTestItem("first")
        let second = AggregateTestItem("second")
        let source = ServicedObservableCollection<AggregateTestItem>()
        source.append(first)
        source.append(second)
        let sut = AggregateChangeStream(source: source) { $0.changes.publisher }
        var observed: [AggregateChange<AggregateTestItem>] = []
        sut.observe().sink { observed.append($0) }.store(in: &cancellables)

        sut.withBatch {}
        XCTAssertTrue(observed.isEmpty)
        try source.move(from: 0, to: 1)
        XCTAssertEqual(observed.map(\.reason), [.membership])
        XCTAssertEqual(first.changes.subscribeCount, 1)
        XCTAssertEqual(first.changes.cancelCount, 0)

        let pendingItem = AggregateTestItem("pending")
        let pendingSource = AggregateTestSource([pendingItem])
        let pending = aggregate(pendingSource)
        var pendingReasons: [AggregateChangeReason] = []
        var runBatch = true
        pending.observe().sink { change in
            pendingReasons.append(change.reason)
            if runBatch, change.reason == .item {
                runBatch = false
                pending.withBatch { pendingSource.add(AggregateTestItem("added")) }
            }
        }.store(in: &cancellables)
        pendingItem.changes.emit()
        XCTAssertEqual(pendingReasons, [.item, .batch])
        pending.dispose()
        sut.dispose()
    }

    /// AGCH-009 — reentrant FIFO delivery discards stale epoch work.
    func testAgch009ReentrantFifoAndStaleEpoch() {
        let item = AggregateTestItem("item")
        let source = AggregateTestSource([item])
        let sut = aggregate(source)
        var observed: [AggregateChange<AggregateTestItem>] = []
        sut.observe().sink { change in
            observed.append(change)
            if change.reason == .item, !source.items.isEmpty {
                // Removal reconciliation is queued behind the current delivery.
                // This next callback is therefore captured from the old epoch
                // before cancellation, then must be rejected after removal.
                source.remove(item)
                item.changes.emit()
            }
        }.store(in: &cancellables)

        item.changes.emit()
        XCTAssertEqual(observed.map(\.reason), [.item, .membership])
        XCTAssertEqual(item.changes.cancelCount, 1)
        source.add(item)
        XCTAssertEqual(item.changes.subscribeCount, 2)
        item.changes.emit()
        XCTAssertEqual(observed.filter { $0.reason == .item }.count, 2)
        sut.dispose()
    }

    /// AGCH-010 — disposal, ownership, adapters, and subscriber effects are bounded.
    func testAgch010DisposalOwnershipAndAdapters() throws {
        let demandItem = AggregateTestItem("demand")
        let demandAggregate = aggregate(AggregateTestSource([demandItem]))
        let finite = FiniteAggregateSubscriber<AggregateTestItem>()
        demandAggregate.observe().subscribe(finite)
        demandItem.changes.emit()
        demandItem.changes.emit()
        XCTAssertEqual(finite.values.count, 1)
        finite.requestOne()
        demandItem.changes.emit()
        XCTAssertEqual(finite.values.count, 2)
        finite.cancel()
        demandItem.changes.emit()
        XCTAssertEqual(finite.values.count, 2)
        demandAggregate.dispose()

        let owned = AggregateTestItem("owned")
        let source = AggregateTestSource([owned])
        let sut = aggregate(source)
        var completionCount = 0
        var safeReasons: [AggregateChangeReason] = []
        sut.observe().sink(
            receiveCompletion: { _ in completionCount += 1 },
            receiveValue: { safeReasons.append($0.reason) }
        ).store(in: &cancellables)

        sut.dispose()
        sut.dispose()
        source.add(AggregateTestItem("late"))
        owned.changes.emit()
        XCTAssertEqual(completionCount, 1)
        XCTAssertTrue(safeReasons.isEmpty)
        XCTAssertEqual(source.cancellationCount, 1)
        XCTAssertEqual(owned.changes.cancelCount, 1)
        XCTAssertEqual(owned.disposeCount, 0)

        let component = try ComponentVMOf<Int>.builder()
            .name("component").withNullServices().model(1).build()
        let components = ServicedObservableCollection<ComponentVMOf<Int>>()
        components.append(component)
        let componentAggregate = AggregateChangeStream.forComponents(components)
        var componentChanges: [AggregateChange<ComponentVMOf<Int>>] = []
        componentAggregate.observe().sink { componentChanges.append($0) }
            .store(in: &cancellables)
        component.model = 2
        XCTAssertTrue(componentChanges.last?.item === component)
        componentAggregate.dispose()

        let child = try ComponentVM.builder().name("child").withNullServices().build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("composite").withNullServices().children { [] }.build()
        var compositePulses = 0
        let compositeSubscription = composite.subscribeMembership { compositePulses += 1 }
        composite.add(child)
        XCTAssertTrue(composite.snapshot().first === child)
        _ = composite.remove(child)
        XCTAssertEqual(compositePulses, 2)
        compositeSubscription.cancel()

        let group = try GroupVM<ComponentVM>.builder()
            .name("group").withNullServices().children { [] }.build()
        var groupPulses = 0
        let groupSubscription = group.subscribeMembership { groupPulses += 1 }
        group.add(child)
        _ = group.remove(child)
        XCTAssertEqual(groupPulses, 2)
        groupSubscription.cancel()
    }
}
