import Combine
import Foundation

/// Identifies why an aggregate notification was emitted.
public enum AggregateChangeReason: Sendable {
    /// Subscriber-local readiness seed.
    case initial
    /// A structural pulse committed a fresh ordered membership snapshot.
    case membership
    /// A current member's selected publisher emitted.
    case item
    /// One or more changes were coalesced by an explicit batch.
    case batch
}

/// Provenance for one aggregate notification.
public struct AggregateChange<Item: AnyObject> {
    public let reason: AggregateChangeReason
    public let item: Item?

    init(reason: AggregateChangeReason, item: Item? = nil) {
        self.reason = reason
        self.item = item
    }
}

/// Follows live source membership and fans in one selected local publisher per
/// distinct current reference identity.
public final class AggregateChangeStream<Item: AnyObject> {
    private enum EntryPhase {
        case stagingSetup
        case stagingMembership
        case admitted
        case terminal
    }

    private enum EmissionClassification {
        case setup
        case membership
    }

    /// Item callbacks use a separate lock so a background value can retain its
    /// event-time staging classification while the aggregate gate is held.
    private final class Entry {
        let item: Item
        let identity: ObjectIdentifier
        let epoch: UInt64
        var refcount: Int

        private let lock = NSRecursiveLock()
        private var phase: EntryPhase
        private var subscription: AnyCancellable?

        init(item: Item, epoch: UInt64, refcount: Int, setup: Bool) {
            self.item = item
            self.identity = ObjectIdentifier(item)
            self.epoch = epoch
            self.refcount = refcount
            self.phase = setup ? .stagingSetup : .stagingMembership
        }

        /// Routes staging work while the phase lock is still held, making
        /// classification + queue insertion atomic with `activate()`.
        func routeEmission(
            stage: (EmissionClassification) -> Void
        ) -> Bool {
            lock.lock()
            defer { lock.unlock() }
            switch phase {
            case .stagingSetup:
                stage(.setup)
                return false
            case .stagingMembership:
                stage(.membership)
                return false
            case .admitted:
                return true
            case .terminal:
                return false
            }
        }

        func install(_ cancellable: AnyCancellable) {
            lock.lock()
            if phase == .terminal {
                lock.unlock()
                cancellable.cancel()
                return
            }
            subscription = cancellable
            lock.unlock()
        }

        func activate() {
            lock.lock()
            if phase != .terminal { phase = .admitted }
            lock.unlock()
        }

        func finishEpoch() {
            lock.lock()
            guard phase != .terminal else {
                lock.unlock()
                return
            }
            phase = .terminal
            let current = subscription
            subscription = nil
            lock.unlock()
            current?.cancel()
        }

        func terminate() {
            finishEpoch()
        }

        var isActive: Bool {
            lock.lock()
            defer { lock.unlock() }
            return phase == .admitted
        }
    }

    private struct SnapshotPlan {
        let counts: [ObjectIdentifier: Int]
        let orderedItems: [(ObjectIdentifier, Item)]
        var staged: [Entry] = []
    }

    private struct PendingChange {
        let change: AggregateChange<Item>
        let entry: Entry?
        let epoch: UInt64

        init(
            _ change: AggregateChange<Item>,
            entry: Entry? = nil,
            epoch: UInt64 = 0
        ) {
            self.change = change
            self.entry = entry
            self.epoch = epoch
        }
    }

    private enum Work {
        case structural(coalesced: Bool, recipients: [UUID])
        case item(entry: Entry, epoch: UInt64, coalesced: Bool, recipients: [UUID])
        case notification(PendingChange, recipients: [UUID])
        case completion([AggregateOutputEndpoint<Item>])
    }

    private let gate = NSRecursiveLock()
    private let versionLock = NSLock()
    private let stagingLock = NSLock()
    private let snapshotSource: () -> [Item]
    private let observeItem: (Item) -> AnyPublisher<Void, Never>
    private let beforeStageRecord: (() -> Void)?
    private let beforeAdmittedGate: (() -> Void)?
    private var membershipSubscription: AnyCancellable?
    private var entries: [ObjectIdentifier: Entry] = [:]
    private var observers: [UUID: AggregateOutputEndpoint<Item>] = [:]
    private var work: [Work] = []
    private var stagedEmissions: [(Entry, EmissionClassification)] = []
    private var structuralVersion: UInt64 = 0
    private var setupBoundaryVersion: UInt64 = 0
    private var nextEpoch: UInt64 = 0
    private var processing = false
    private var setupComplete = false
    private var completed = false
    private var batchDepth = 0
    private var batchDirty = false
    private var batchRecipients: Set<UUID> = []

    /// Creates an aggregate over a read-only live membership source.
    public init<Source: ObservableMembershipSource>(
        source: Source,
        observeItem: @escaping (Item) -> AnyPublisher<Void, Never>
    ) where Source.Item == Item {
        self.snapshotSource = { source.snapshot() }
        self.observeItem = observeItem
        self.beforeStageRecord = nil
        self.beforeAdmittedGate = nil

        gate.lock()
        membershipSubscription = source.subscribeMembership { [weak self] in
            self?.membershipChanged()
        }
        initializeLocked()
        gate.unlock()
    }

    /// Internal deterministic race seam used only by the conformance suite.
    init<Source: ObservableMembershipSource>(
        source: Source,
        observeItem: @escaping (Item) -> AnyPublisher<Void, Never>,
        _beforeStageRecord: @escaping () -> Void,
        _beforeAdmittedGate: (() -> Void)? = nil
    ) where Source.Item == Item {
        self.snapshotSource = { source.snapshot() }
        self.observeItem = observeItem
        self.beforeStageRecord = _beforeStageRecord
        self.beforeAdmittedGate = _beforeAdmittedGate

        gate.lock()
        membershipSubscription = source.subscribeMembership { [weak self] in
            self?.membershipChanged()
        }
        initializeLocked()
        gate.unlock()
    }

    /// Returns the hot output. The optional seed is private to this subscriber
    /// and is registered through the same serialized gate as normal delivery.
    public func observe(emitInitial: Bool = false) -> AnyPublisher<AggregateChange<Item>, Never> {
        AggregateOutputPublisher(owner: self, emitInitial: emitInitial)
            .eraseToAnyPublisher()
    }

    /// Runs `body` in a nested, ref-counted aggregate coalescing scope.
    @discardableResult
    public func withBatch<Result>(_ body: () throws -> Result) rethrows -> Result {
        gate.lock()
        if !completed { batchDepth += 1 }
        gate.unlock()

        defer { exitBatch() }
        return try body()
    }

    /// Detaches aggregate-owned subscriptions and completes output once.
    public func dispose() {
        var shouldProcess = false
        gate.lock()
        if !completed {
            completed = true
            membershipSubscription?.cancel()
            membershipSubscription = nil
            for entry in entries.values { entry.terminate() }
            entries.removeAll()
            stagingLock.lock()
            stagedEmissions.removeAll()
            stagingLock.unlock()
            work.removeAll()
            let recipients = Array(observers.values)
            observers.removeAll()
            if !recipients.isEmpty { work.append(.completion(recipients)) }
            shouldProcess = startProcessingLocked()
        }
        gate.unlock()
        if shouldProcess { processWork() }
    }

    fileprivate func register(
        _ observer: AggregateOutputEndpoint<Item>,
        emitInitial: Bool
    ) {
        var shouldProcess = false
        gate.lock()
        guard !completed else {
            gate.unlock()
            observer.finish()
            return
        }
        let identifier = observer.identifier
        observers[identifier] = observer
        if emitInitial {
            work.append(.notification(
                PendingChange(AggregateChange(reason: .initial)),
                recipients: [identifier]
            ))
            shouldProcess = startProcessingLocked()
        }
        gate.unlock()
        if shouldProcess { processWork() }
    }

    fileprivate func unregister(_ identifier: UUID) {
        gate.lock()
        observers.removeValue(forKey: identifier)
        gate.unlock()
    }

    private func initializeLocked() {
        while true {
            let version = currentStructuralVersion()
            let snapshot = snapshotSource()
            guard version == currentStructuralVersion() else { continue }

            var plan = makePlan(snapshot, setup: true)
            stageNewEntries(&plan, setup: true)
            guard version == currentStructuralVersion() else {
                disposeStaged(plan)
                continue
            }

            commit(plan)
            guard version == currentStructuralVersion() else { continue }
            discardBufferedItems()

            versionLock.lock()
            if structuralVersion == version {
                setupBoundaryVersion = version
                setupComplete = true
                versionLock.unlock()
                return
            }
            versionLock.unlock()
        }
    }

    private func membershipChanged() {
        versionLock.lock()
        structuralVersion &+= 1
        let version = structuralVersion
        versionLock.unlock()

        var shouldProcess = false
        gate.lock()
        if !completed, setupComplete, version > setupBoundaryVersion {
            let coalesced = batchDepth > 0
            let recipients = Array(observers.keys)
            if coalesced { markBatchDirtyLocked(recipients) }
            work.append(.structural(
                coalesced: coalesced,
                recipients: recipients
            ))
            shouldProcess = startProcessingLocked()
        }
        gate.unlock()
        if shouldProcess { processWork() }
    }

    private func selectedItemChanged(_ entry: Entry) {
        let admitted = entry.routeEmission { classification in
            beforeStageRecord?()
            stagingLock.lock()
            stagedEmissions.append((entry, classification))
            stagingLock.unlock()
        }
        guard admitted else { return }
        beforeAdmittedGate?()

        var shouldProcess = false
        gate.lock()
        if !completed,
           setupComplete,
           entries[entry.identity] === entry,
           entry.refcount > 0,
           entry.isActive {
            let coalesced = batchDepth > 0
            let recipients = Array(observers.keys)
            if coalesced { markBatchDirtyLocked(recipients) }
            work.append(.item(
                entry: entry,
                epoch: entry.epoch,
                coalesced: coalesced,
                recipients: recipients
            ))
            shouldProcess = startProcessingLocked()
        }
        gate.unlock()
        if shouldProcess { processWork() }
    }

    private func selectedItemCompleted(_ entry: Entry) {
        entry.finishEpoch()
    }

    private func processWork() {
        while true {
            var delivery: Work?
            gate.lock()
            guard !work.isEmpty else {
                processing = false
                gate.unlock()
                return
            }

            let current = work.removeFirst()
            switch current {
            case .structural(let coalesced, let recipients):
                processStructuralLocked(coalesced: coalesced, recipients: recipients)
            case .item(let entry, let epoch, let coalesced, let recipients):
                processItemLocked(
                    entry: entry,
                    epoch: epoch,
                    coalesced: coalesced,
                    recipients: recipients
                )
            case .notification, .completion:
                delivery = current
            }
            gate.unlock()

            guard let delivery else { continue }
            deliver(delivery)
        }
    }

    private func processStructuralLocked(coalesced: Bool, recipients: [UUID]) {
        guard !completed else { return }
        while true {
            let version = currentStructuralVersion()
            let snapshot = snapshotSource()
            guard version == currentStructuralVersion() else { continue }

            var plan = makePlan(snapshot, setup: false)
            stageNewEntries(&plan, setup: false)
            guard version == currentStructuralVersion() else {
                disposeStaged(plan)
                continue
            }

            commit(plan)
            guard version == currentStructuralVersion() else { continue }

            var changes = [PendingChange(AggregateChange(reason: .membership))]
            appendBufferedItems(to: &changes)
            prepend(changes, coalesced: coalesced, recipients: recipients)
            return
        }
    }

    private func processItemLocked(
        entry: Entry,
        epoch: UInt64,
        coalesced: Bool,
        recipients: [UUID]
    ) {
        guard !completed,
              entries[entry.identity] === entry,
              entry.epoch == epoch,
              entry.refcount > 0,
              entry.isActive else { return }
        prepend(
            [PendingChange(
                AggregateChange(reason: .item, item: entry.item),
                entry: entry,
                epoch: epoch
            )],
            coalesced: coalesced,
            recipients: recipients
        )
    }

    private func deliver(_ work: Work) {
        switch work {
        case .notification(let pending, let recipients):
            gate.lock()
            let valid: Bool
            if let entry = pending.entry {
                valid = !completed
                    && entries[entry.identity] === entry
                    && entry.epoch == pending.epoch
                    && entry.refcount > 0
                    && entry.isActive
            } else {
                valid = !completed
            }
            let targets = valid ? recipients.compactMap { observers[$0] } : []
            gate.unlock()
            for target in targets { target.offer(pending.change) }
        case .completion(let recipients):
            for recipient in recipients { recipient.finish() }
        case .structural, .item:
            break
        }
    }

    private func makePlan(_ snapshot: [Item], setup: Bool) -> SnapshotPlan {
        var counts: [ObjectIdentifier: Int] = [:]
        var ordered: [(ObjectIdentifier, Item)] = []
        for item in snapshot {
            let identity = ObjectIdentifier(item)
            if counts[identity] == nil { ordered.append((identity, item)) }
            counts[identity, default: 0] += 1
        }
        return SnapshotPlan(counts: counts, orderedItems: ordered)
    }

    private func stageNewEntries(_ plan: inout SnapshotPlan, setup: Bool) {
        for (identity, item) in plan.orderedItems where entries[identity] == nil {
            nextEpoch &+= 1
            let entry = Entry(
                item: item,
                epoch: nextEpoch,
                refcount: plan.counts[identity] ?? 1,
                setup: setup
            )
            let publisher = observeItem(item)
            let cancellable = publisher.sink(
                receiveCompletion: { [weak self, weak entry] _ in
                    guard let entry else { return }
                    self?.selectedItemCompleted(entry)
                },
                receiveValue: { [weak self, weak entry] _ in
                    guard let entry else { return }
                    self?.selectedItemChanged(entry)
                }
            )
            entry.install(cancellable)
            plan.staged.append(entry)
        }
    }

    private func commit(_ plan: SnapshotPlan) {
        for (identity, existing) in entries {
            if let count = plan.counts[identity] {
                existing.refcount = count
            } else {
                existing.refcount = 0
                existing.terminate()
                purgeStagedEmissions(for: existing)
                entries.removeValue(forKey: identity)
            }
        }
        for staged in plan.staged {
            staged.activate()
            entries[staged.identity] = staged
        }
    }

    private func disposeStaged(_ plan: SnapshotPlan) {
        for staged in plan.staged {
            staged.terminate()
            purgeStagedEmissions(for: staged)
        }
    }

    private func appendBufferedItems(to changes: inout [PendingChange]) {
        stagingLock.lock()
        let pending = stagedEmissions
        stagedEmissions.removeAll()
        stagingLock.unlock()
        for (entry, classification) in pending where classification == .membership {
            if entries[entry.identity] === entry, entry.isActive {
                changes.append(PendingChange(
                    AggregateChange(reason: .item, item: entry.item),
                    entry: entry,
                    epoch: entry.epoch
                ))
            }
        }
    }

    private func discardBufferedItems() {
        stagingLock.lock()
        stagedEmissions.removeAll()
        stagingLock.unlock()
    }

    private func purgeStagedEmissions(for entry: Entry) {
        stagingLock.lock()
        stagedEmissions.removeAll { $0.0 === entry }
        stagingLock.unlock()
    }

    private func prepend(
        _ changes: [PendingChange],
        coalesced: Bool,
        recipients: [UUID]
    ) {
        guard !changes.isEmpty, !coalesced else { return }
        guard !recipients.isEmpty else { return }
        work.insert(
            contentsOf: changes.map { .notification($0, recipients: recipients) },
            at: 0
        )
    }

    private func exitBatch() {
        var shouldProcess = false
        gate.lock()
        if batchDepth > 0 { batchDepth -= 1 }
        if batchDepth == 0, batchDirty, !completed {
            batchDirty = false
            let recipients = Array(batchRecipients)
            batchRecipients.removeAll()
            if !recipients.isEmpty {
                work.append(.notification(
                    PendingChange(AggregateChange(reason: .batch)),
                    recipients: recipients
                ))
                shouldProcess = startProcessingLocked()
            }
        }
        gate.unlock()
        if shouldProcess { processWork() }
    }

    private func markBatchDirtyLocked(_ recipients: [UUID]) {
        batchDirty = true
        batchRecipients.formUnion(recipients)
    }

    private func startProcessingLocked() -> Bool {
        guard !processing, !work.isEmpty else { return false }
        processing = true
        return true
    }

    private func currentStructuralVersion() -> UInt64 {
        versionLock.lock()
        let version = structuralVersion
        versionLock.unlock()
        return version
    }
}

public extension AggregateChangeStream where Item: ComponentVMBase {
    /// Selects each current component's standard local property-change stream.
    static func forComponents<Source>(_ source: Source) -> AggregateChangeStream<Item>
    where Source: ObservableMembershipSource, Source.Item == Item {
        AggregateChangeStream(source: source) {
            $0.propertyChanged.map { _ in () }.eraseToAnyPublisher()
        }
    }
}

private struct AggregateOutputPublisher<Item: AnyObject>: Publisher {
    typealias Output = AggregateChange<Item>
    typealias Failure = Never

    let owner: AggregateChangeStream<Item>
    let emitInitial: Bool

    func receive<Downstream: Subscriber>(subscriber: Downstream)
    where Downstream.Input == Output, Downstream.Failure == Failure {
        let subscription = AggregateOutputEndpoint(
            owner: owner,
            downstream: AnySubscriber(subscriber),
            emitInitial: emitInitial
        )
        subscriber.receive(subscription: subscription)
    }
}

fileprivate final class AggregateOutputEndpoint<Item: AnyObject>: Subscription {
    private let lock = NSRecursiveLock()
    private var owner: AggregateChangeStream<Item>?
    private var downstream: AnySubscriber<AggregateChange<Item>, Never>?
    private let emitInitial: Bool
    fileprivate let identifier = UUID()
    private var demand: Subscribers.Demand = .none
    private var registered = false
    private var cancelled = false
    private var completed = false

    init(
        owner: AggregateChangeStream<Item>,
        downstream: AnySubscriber<AggregateChange<Item>, Never>,
        emitInitial: Bool
    ) {
        self.owner = owner
        self.downstream = downstream
        self.emitInitial = emitInitial
    }

    func request(_ demand: Subscribers.Demand) {
        guard demand > .none else { return }
        lock.lock()
        guard !cancelled, !completed, let owner else {
            lock.unlock()
            return
        }
        self.demand += demand
        if !registered {
            registered = true
            owner.register(self, emitInitial: emitInitial)
        }
        lock.unlock()
    }

    fileprivate func offer(_ change: AggregateChange<Item>) {
        lock.lock()
        guard !cancelled, !completed, demand > .none, let downstream else {
            lock.unlock()
            return
        }
        if demand != .unlimited { demand -= 1 }
        demand += downstream.receive(change)
        lock.unlock()
    }

    fileprivate func finish() {
        lock.lock()
        guard !cancelled, !completed, let downstream else {
            lock.unlock()
            return
        }
        completed = true
        owner = nil
        self.downstream = nil
        downstream.receive(completion: .finished)
        lock.unlock()
    }

    func cancel() {
        lock.lock()
        guard !cancelled else {
            lock.unlock()
            return
        }
        cancelled = true
        if registered { owner?.unregister(identifier) }
        owner = nil
        downstream = nil
        lock.unlock()
    }
}
