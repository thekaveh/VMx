//
// FormVM<Model> — snapshot/revert edit lifecycle ViewModel.
//
// Standalone (not a ComponentVMOf subclass) per spec/20-form-vm.md §1.1
// and ADR-0030.
//
// See spec/20-form-vm.md and ADR-0048 (injectable deep-equal + deep snapshot).
//
import Combine
import Foundation

/// A ViewModel that wraps a mutable domain model with snapshot-based dirty
/// tracking and an edit lifecycle (approve / deny). Captures a snapshot at
/// construction; mutations via `setModel` update the live model only.
///
/// ``isDirty`` is `true` when the current model is not equal to the snapshot
/// according to the injectable `equals` predicate.
///
/// Use ``approveCommand`` (fire-and-forget) or ``approveAsync()`` (awaitable)
/// to persist; use ``denyCommand`` to revert. Persister failures surface on
/// ``approveErrors`` when the command path is used, and rethrow directly when
/// awaited via ``approveAsync()``. One approval runs at a time: an approve
/// call made while another is in flight does nothing (spec/20-form-vm.md
/// §5.3, ADR-0143).
///
/// `setModel` and ``denyCommand`` prepare before they commit: the equality,
/// snapshotter, and validator callbacks run first without changing form
/// state, and only then is the result committed in one step and published.
/// Updates are serialized: the form's re-entrant state lock is held across
/// preparation, so another thread's update, approval commit, or disposal
/// waits for it (spec/20-form-vm.md §5.4, ADR-0144).
public final class FormVM<Model> {

    // ── Stored state ──────────────────────────────────────────────────────────

    private var _model: Model
    private var _snapshot: Model
    private var _disposed = false
    // Failure-atomic updates (§5.4, ADR-0144): every commit of the model,
    // snapshot, or errors advances this generation under `stateGate`. An
    // update holds the gate from admission through commit, so only a
    // callback re-entering on the preparing thread can dispose the form or
    // commit another update meanwhile; the prepared result is then stale and
    // dropped, and the newest committed state stands.
    private var commitGeneration: UInt64 = 0
    private var activeMutations = 0
    // A disposal's teardown (§10) waits until no update is active (§5.4) and
    // no other thread holds a publication scope. A disposal whose scope wait
    // was refused sets `teardownAfterScopes`: its teardown then waits until
    // no thread holds a scope, so the publisher runs it after its outermost
    // scope ends (§5.5).
    private var teardownPending = false
    private var teardownAfterScopes = false
    // Updates during approval publication (§5.3, ADR-0174): the threads
    // inside an approval's pre-publication window, which runs from the start
    // of the post-persist commit until `onApproved` delivery starts. A
    // `setModel` or deny on such a thread prepares, then joins that thread's
    // queue in `deferredUpdates` instead of committing. A Swift approval
    // commits from its own task, so windows never nest on one thread.
    private var prePublishingThreads = Set<UInt64>()
    // Each publisher's queue (§5.5): its own pre-publication calls, then the
    // refused updates of other threads, in the order they joined. It replays
    // after the publisher's outermost publication scope ends.
    // `deferredGeneration` advances on each enqueue, so a queued nested
    // update also makes a preparation stale.
    private var deferredUpdates: [UInt64: [DeferredUpdate]] = [:]
    private var deferredGeneration: UInt64 = 0
    // Single-flight admission (§5.3, ADR-0143): set when an approval is
    // admitted and cleared when it settles, both under `stateGate`. The gate
    // is never held while the persister runs or observers are notified.
    private var approvalInFlight = false
    private let stateGate = NSRecursiveLock()
    // Publication scopes (§5.5, ADR-0176): the open scopes of each publisher
    // thread. A committed `setModel` or deny holds an update scope while it
    // sends `errorsChanged` (#704), so error maps keep commit order; its
    // `canExecuteChanged` and hub messages follow the scope (#1057). A
    // settlement holds a settlement scope from clearing the in-flight mark
    // until `onApproved` returns, or, after a failure, until its
    // `canExecuteChanged` returns (#533). Scopes are delivered outside
    // `stateGate`, so other threads can read the form meanwhile.
    //
    // Another thread's `setModel`, deny, approval admission, settlement, or
    // disposal waits until no other thread holds a scope. The wait records
    // an edge on `scopeFinished` in `ThreadWaitGraph`, owned by one
    // publisher, so a wait that would close a cycle is refused and the call
    // takes its §5.5 escape instead. Two threads hold scopes only after such
    // a refusal.
    private var scopeDepths: [UInt64: Int] = [:]
    private var scopeWaitsRecorded = false
    private var scopeGeneration = 0
    private let scopeFinished = NSCondition()
    // Consumer callbacks of an approval commit that run under `stateGate`
    // (the reset, the snapshotter, and the validators). With `preparationDepth`
    // this tells a nested call that it holds the gate and must not wait.
    private var commitCallbackDepth = 0
    // Re-entrant updates (#1057): `setModel` and deny hold `stateGate` across
    // consumer callbacks. This counts those frames on the thread that holds
    // the gate. A call nested in one of them queues its notifications in
    // `pendingNotices`, and the outermost frame delivers them after it
    // releases the gate, because another thread's sink may wait for the gate.
    private var preparationDepth = 0
    private var pendingNotices = Notices()
    // The threads that send error maps inside their open update scopes in
    // `deliver`. An update or admission on such a thread, made from an
    // `errorsChanged` sink, queues its notifications in that thread's entry
    // of `scopedNotices`. Its error maps go out inside those scopes, and the
    // rest follows them. Only the owning thread adds to or takes from an
    // entry.
    private var scopedDeliveryThreads = Set<UInt64>()
    private var scopedNotices: [UInt64: Notices] = [:]

    private let persister: (Model) async throws -> Void
    private let hub: MessageHubProtocol
    private let strict: Bool
    private let snapshotter: (Model) -> Model
    private let equals: (Model, Model) -> Bool
    private let validators: [String: (Model) -> String?]
    private let modelValidator: ((Model) -> [String: String?])?
    private let resetOnApproved: ((Model) throws -> Model)?
    private var _errors: [String: String]

    // ── Reactive channels (sealed) ────────────────────────────────────────────
    //
    // Every channel, and `canExecuteChanged` of both commands, delivers
    // through `VMxConcurrentSubject`, which holds no lock while a sink runs
    // (#1168, ADR-0174 §2.1). A sink that updates or disposes the form can
    // then wait for another thread's publication scope without blocking that
    // thread's next send, as in C# and Python. One sink can run on two
    // threads at once.

    private let _onApproved = VMxConcurrentSubject<Model, Never>()
    private let _approveErrors = VMxConcurrentSubject<Error, Never>()
    private let _errorsChanged = VMxConcurrentSubject<[String: String], Never>()
    /// Fires when `isDirty` transitions in strict mode; wired as a trigger on
    /// `approveCommand` so that subscribers to `canExecuteChanged` are notified.
    private let _approveCanExecSubject = VMxConcurrentSubject<Void, Never>()

    // ── Init ──────────────────────────────────────────────────────────────────

    /// Designated initializer.
    ///
    /// - Parameters:
    ///   - initial: The starting model value; also forms the initial snapshot.
    ///   - persister: Async closure invoked on approve. Throw on failure.
    ///   - hub: Message hub (default: `NullMessageHub.INSTANCE`).
    ///   - strict: When `true`, approve is disabled while `isDirty` is false.
    ///   - snapshotter: Function that produces a snapshot copy of the model.
    ///     Defaults to identity `{ $0 }`, which is correct for value types
    ///     (Swift structs are copied on assignment).
    ///   - equals: Equality predicate for dirty-tracking.
    ///     `isDirty == !equals(model, snapshot)`.
    ///   - resetOnApproved: Optional throwing callback that derives the next
    ///     pristine model from the captured value after persistence succeeds.
    public init(
        initial: Model,
        persister: @escaping (Model) async throws -> Void,
        hub: MessageHubProtocol = NullMessageHub.INSTANCE,
        strict: Bool = false,
        snapshotter: @escaping (Model) -> Model = { $0 },
        validators: [String: (Model) -> String?] = [:],
        modelValidator: ((Model) -> [String: String?])? = nil,
        resetOnApproved: ((Model) throws -> Model)? = nil,
        equals: @escaping (Model, Model) -> Bool
    ) {
        self._model = initial
        self.persister = persister
        self.hub = hub
        self.strict = strict
        self.snapshotter = snapshotter
        self.equals = equals
        self.validators = validators
        self.modelValidator = modelValidator
        self.resetOnApproved = resetOnApproved
        // Capture snapshot at construction via snapshotter.
        self._snapshot = snapshotter(initial)
        self._errors = Self.validate(
            initial,
            validators: validators,
            modelValidator: modelValidator
        )

        // Phase 1: satisfy Swift's two-phase init by giving both commands a
        // placeholder before `self` is available for capture.
        self.denyCommand = RelayCommand(task: nil, predicate: nil, triggers: [])
        self.approveCommand = RelayCommand(task: nil, predicate: nil, triggers: [])

        // Phase 2: all stored properties are set; wire the real closures that
        // capture `self` (weakly to avoid retain cycles).
        wireCommands()
    }

    // ── Commands ──────────────────────────────────────────────────────────────

    /// Reverts `model` to `snapshotter(snapshot)` and publishes
    /// `FormRevertedMessage` + `PropertyChangedMessage("model")` on the hub.
    /// After execution `isDirty == false`.
    public private(set) var denyCommand: RelayCommand

    /// Fire-and-forget approve. Persister failures surface on ``approveErrors``;
    /// they do NOT propagate to the caller of `execute()` (use ``approveAsync()``
    /// directly when you need to `await` the outcome). `execute()` admits the
    /// approval synchronously, and `canExecute()` is `false` while an approval
    /// is in flight; `canExecuteChanged` fires on admission and on settlement.
    public private(set) var approveCommand: RelayCommand

    // ── Properties ────────────────────────────────────────────────────────────

    /// The live, editable domain model.
    public var model: Model { withStateGate { _model } }

    /// Read-only snapshot captured at construction (until the next successful
    /// approve).
    public var snapshot: Model { withStateGate { _snapshot } }

    /// `true` when `model` is not equal to `snapshot` under the `equals`
    /// predicate.
    public var isDirty: Bool {
        let state = withStateGate { (_model, _snapshot) }
        return !equals(state.0, state.1)
    }

    /// Current validation errors keyed by field/property name.
    public var errors: [String: String] {
        withStateGate { _errors }
    }

    /// `true` when the current model has no validation errors.
    public var isValid: Bool {
        withStateGate { _errors.isEmpty }
    }

    /// Emits the persisted model value after each successful ``approveAsync()``
    /// call (including the command path). Does NOT emit on failure.
    public var onApproved: AnyPublisher<Model, Never> {
        _onApproved.eraseToAnyPublisher()
    }

    /// Emits the `Error` thrown by the persister when ``approveCommand`` (the
    /// fire-and-forget path) fails. The awaitable ``approveAsync()`` rethrows
    /// directly instead of surfacing here.
    public var approveErrors: AnyPublisher<Error, Never> {
        _approveErrors.eraseToAnyPublisher()
    }

    /// Emits only when the effective validation error map changes.
    public var errorsChanged: AnyPublisher<[String: String], Never> {
        _errorsChanged.eraseToAnyPublisher()
    }

    /// Returns the current validation error for a field, if any.
    public func fieldError(_ field: String) -> String? {
        withStateGate { _errors[field] }
    }

    // ── Mutation ──────────────────────────────────────────────────────────────

    /// Replaces the current model. The snapshot is unaffected.
    /// In strict mode fires `approveCommand.canExecuteChanged` when `isDirty`
    /// transitions so that UI bindings can re-evaluate the approve button state.
    /// A call begun after disposal returns before inspecting the candidate.
    ///
    /// The equality and validator callbacks run before anything is committed
    /// and observe the previous form state (§5.4). Another thread's update or
    /// disposal waits until this call has committed. If a callback re-enters
    /// on this thread and disposes the form or commits another update, this
    /// call commits and publishes nothing, and the newest committed state
    /// stands. The notifications of an update made from such a callback are
    /// delivered after this call releases the form's state lock (#1057).
    ///
    /// Called on the approving thread from `resetOnApproved`, another
    /// callback of the approval's commit, or a settlement `errorsChanged` or
    /// `canExecuteChanged` sink, the call prepares, then is queued and
    /// returns without changing the form. It replays after `onApproved` is
    /// delivered (§5.3, ADR-0174).
    ///
    /// While another thread publishes form notifications, the call waits
    /// until that publication scope ends. When the wait would close a
    /// wait-for cycle, the call prepares, joins that publisher's queue, and
    /// returns before it takes effect (§5.5, ADR-0176).
    public func setModel(_ newModel: Model) {
        stateGate.lock()
        let queueOwner = admitUpdateLocked()
        guard !_disposed else {
            stateGate.unlock()
            return
        }
        activeMutations += 1
        preparationDepth += 1
        var notices = Notices()
        defer {
            // Observers are notified after the gate is released (ADR-0143,
            // #704), by the outermost update on this thread (#1057).
            preparationDepth -= 1
            let delivery = takeNoticesLocked(notices)
            stateGate.unlock()
            deliver(delivery)
            endMutation()
        }

        // Preparation (§5.2, §5.4): consumer callbacks run under the
        // re-entrant `stateGate`, which keeps updates serialized, and change
        // no form state.
        let base = updateBaseLocked()
        // A queued call is never skipped for equality: earlier queued calls
        // can change the live model before it replays (§5.3).
        guard !equals(base.model, newModel) || queueOwner != nil else { return }
        let wasDirty = !equals(base.model, base.snapshot)
        let nextErrors = Self.validate(
            newModel,
            validators: validators,
            modelValidator: modelValidator
        )
        let nextDirty = !equals(newModel, base.snapshot)
        let wasValid = base.errors.isEmpty
        let errorsChanged = nextErrors != base.errors
        let canExecuteChanged =
            (strict && nextDirty != wasDirty) || nextErrors.isEmpty != wasValid

        if let queueOwner {
            // The call-time preparation is discarded; the replay prepares again.
            enqueueLocked(.setModel(newModel), for: queueOwner, preparedAgainst: base)
            return
        }
        // Commit in one step, unless a re-entrant callback made the prepared
        // result stale.
        guard beginCommitLocked(base) else { return }
        _model = newModel
        _errors = nextErrors
        enterPublicationLocked()
        notices.scopes += 1
        if errorsChanged {
            notices.errors.append(nextErrors)
        }
        if canExecuteChanged {
            notices.afterScope.append(.canExecuteChanged)
        }
        notices.afterScope.append(.message(PropertyChangedMessage(
            sender: self,
            senderName: "FormVM",
            propertyName: "model"
        )))
    }

    // ── Async core ────────────────────────────────────────────────────────────

    /// Awaitable approve flow. Captures the current model **before** awaiting
    /// the persister, so a racing `setModel` cannot swap the persisted payload.
    ///
    /// On success: advances the snapshot and fires ``onApproved``.
    /// On persister throw: mutates nothing and rethrows.
    /// While another approval is in flight: returns without persisting,
    /// mutating, throwing, or emitting (spec §5.3).
    /// After `dispose()`: returns immediately (no-op).
    public func approveAsync() async throws {
        guard let admission = admitApproval() else { return }
        try await runApproval(admission)
    }

    // ── Dispose ───────────────────────────────────────────────────────────────

    /// Complete both reactive channels and dispose the commands. Idempotent.
    ///
    /// While another thread publishes form notifications, the call waits
    /// until that publication scope ends. When the wait would close a
    /// wait-for cycle, the call marks the form disposed and returns. The
    /// publisher then completes the channels and disposes the commands after
    /// its outermost scope ends (§5.5, ADR-0176).
    public func dispose() {
        stateGate.lock()
        let refused = awaitForeignScopesLocked() != nil
        guard !_disposed else {
            stateGate.unlock()
            return
        }
        _disposed = true
        teardownPending = true
        teardownAfterScopes = refused
        let shouldTearDown = takeTeardownLocked()
        stateGate.unlock()
        if shouldTearDown { tearDown() }
    }

    // ── Wire commands post-init ───────────────────────────────────────────────

    /// Called once from `init` (after every stored property is set) to replace
    /// the placeholder commands with the real closures that capture `self`.
    fileprivate func wireCommands() {
        denyCommand = RelayCommand(
            task: { [weak self] in self?.performDeny() },
            predicate: nil,
            triggers: [],
            concurrentDelivery: true
        )
        approveCommand = RelayCommand(
            task: { [weak self] in
                // Admit before returning, so a second `execute()` is refused
                // even before the persister task starts (§5.3).
                _ = self?.admitApproval(startingCommandTask: true)
            },
            predicate: { [weak self] in
                self?.canApprove() ?? false
            },
            triggers: [_approveCanExecSubject.eraseToAnyPublisher()],
            concurrentDelivery: true
        )
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    private func performDeny() {
        stateGate.lock()
        let queueOwner = admitUpdateLocked()
        guard !_disposed else {
            stateGate.unlock()
            return
        }
        activeMutations += 1
        preparationDepth += 1
        var notices = Notices()
        defer {
            // Observers are notified after the gate is released (ADR-0143,
            // #704), by the outermost update on this thread (#1057).
            preparationDepth -= 1
            let delivery = takeNoticesLocked(notices)
            stateGate.unlock()
            deliver(delivery)
            endMutation()
        }

        // Preparation (§5.4): the snapshotter, validator, and equality
        // callbacks run under the re-entrant `stateGate`, which keeps updates
        // serialized, and change no form state.
        let base = updateBaseLocked()
        let nextModel = snapshotter(base.snapshot)
        let nextErrors = Self.validate(
            nextModel,
            validators: validators,
            modelValidator: modelValidator
        )
        let wasDirty = !equals(base.model, base.snapshot)
        let wasValid = base.errors.isEmpty
        let nextDirty = !equals(nextModel, base.snapshot)
        let nextValid = nextErrors.isEmpty
        let errorsChanged = nextErrors != base.errors
        let canExecuteChanged =
            (strict && nextDirty != wasDirty) || nextValid != wasValid

        if let queueOwner {
            // Queued like `setModel` (§5.3, §5.5): `onApproved` observers
            // never see a revert that a settlement observer requests.
            enqueueLocked(.deny, for: queueOwner, preparedAgainst: base)
            return
        }
        // Commit in one step, unless a re-entrant callback made the prepared
        // revert stale: a form disposed meanwhile is not reverted and
        // publishes no deny message.
        guard beginCommitLocked(base) else { return }
        _model = nextModel
        _errors = nextErrors
        enterPublicationLocked()
        notices.scopes += 1
        if errorsChanged {
            notices.errors.append(nextErrors)
        }
        notices.afterScope.append(.message(FormRevertedMessage(senderObject: self, senderName: "FormVM")))
        notices.afterScope.append(.message(
            PropertyChangedMessage(sender: self, senderName: "FormVM", propertyName: "model")
        ))
        if canExecuteChanged {
            notices.afterScope.append(.canExecuteChanged)
        }
    }

    // ── Deferred notifications (#1057) ────────────────────────────────────────

    /// Notifications an update or admission delivers after it releases
    /// `stateGate`. Each `errors` map is sent inside the update scope its
    /// commit opened, so error maps keep commit order across threads. The
    /// scopes then close. `afterScope` is delivered after those scopes,
    /// because a sink that updates the form waits for an open scope. An
    /// approval's own settlement scope can still be open around it.
    private struct Notices {
        var errors: [[String: String]] = []
        var scopes = 0
        var afterScope: [Notice] = []

        mutating func append(_ other: Notices) {
            errors += other.errors
            scopes += other.scopes
            afterScope += other.afterScope
        }
    }

    private enum Notice {
        case canExecuteChanged
        case message(any Message)
        case startApproval(ApprovalAdmission)
    }

    /// Called under `stateGate` by a frame about to release it. A frame
    /// nested in an update on this thread queues `notices` for the outermost
    /// one and returns nothing. The outermost frame takes the whole queue.
    /// Inside the error-map phase of a delivery on this thread, the outermost
    /// frame queues that queue for the delivery instead.
    private func takeNoticesLocked(_ notices: Notices) -> Notices {
        pendingNotices.append(notices)
        guard preparationDepth == 0 else { return Notices() }
        let delivery = pendingNotices
        pendingNotices = Notices()
        let caller = Self.currentThread
        guard !scopedDeliveryThreads.contains(caller) else {
            scopedNotices[caller, default: Notices()].append(delivery)
            return Notices()
        }
        return delivery
    }

    /// Delivers notifications taken by `takeNoticesLocked`, with `stateGate`
    /// released. When this closes the thread's outermost scope, the updates
    /// queued for this publisher replay after the last notification (§5.5).
    private func deliver(_ notices: Notices) {
        var notices = notices
        let caller = Self.currentThread
        if !notices.errors.isEmpty {
            withStateGate { _ = scopedDeliveryThreads.insert(caller) }
            var sent = 0
            while sent < notices.errors.count {
                _errorsChanged.send(notices.errors[sent])
                sent += 1
                if sent == notices.errors.count {
                    // An `errorsChanged` sink may have updated the form on
                    // this thread. Its queued error maps go out inside the
                    // scopes that are still open.
                    notices.append(withStateGate {
                        scopedNotices.removeValue(forKey: caller) ?? Notices()
                    })
                }
            }
            withStateGate { _ = scopedDeliveryThreads.remove(caller) }
        }
        var deferred: [DeferredUpdate] = []
        for _ in 0..<notices.scopes {
            deferred += exitPublication()
        }
        for notice in notices.afterScope {
            switch notice {
            case .canExecuteChanged:
                _approveCanExecSubject.send(())
            case .message(let message):
                hub.send(message)
            case .startApproval(let admission):
                startCommandApproval(admission)
            }
        }
        replay(deferred)
    }

    /// The committed state an update prepares against (§5.4). `queued`
    /// is the queue generation (§5.3).
    private struct UpdateBase {
        let generation: UInt64
        let queued: UInt64
        let model: Model
        let snapshot: Model
        let errors: [String: String]
    }

    /// An update queued during an approval's pre-publication window (§5.3).
    private enum DeferredUpdate {
        case setModel(Model)
        case deny
    }

    /// Reads the committed state for an update to prepare against. The caller
    /// holds `stateGate`.
    private func updateBaseLocked() -> UpdateBase {
        UpdateBase(
            generation: commitGeneration,
            queued: deferredGeneration,
            model: _model,
            snapshot: _snapshot,
            errors: _errors
        )
    }

    /// Admits the commit of an update prepared against `base`, with
    /// `stateGate` held since admission. A prepared result is stale (§5.4)
    /// when a callback re-entering on this thread disposed the form, or
    /// committed another update, while it was prepared; it is then dropped.
    /// Otherwise this advances the generation for the commit that follows.
    private func beginCommitLocked(_ base: UpdateBase) -> Bool {
        guard isCurrentLocked(base) else { return false }
        commitGeneration &+= 1
        return true
    }

    /// `false` when, since `base` was read, the form was disposed or another
    /// update was committed or queued (§5.3, §5.4). The caller holds
    /// `stateGate`.
    private func isCurrentLocked(_ base: UpdateBase) -> Bool {
        !_disposed && commitGeneration == base.generation && deferredGeneration == base.queued
    }

    /// Admits a `setModel` or deny (§5.3, §5.5). Returns the publisher whose
    /// queue the update joins, or `nil` when the update commits. On the
    /// approving thread inside its pre-publication window, that is this
    /// thread, and the call does not wait, because it changes nothing until
    /// it replays. Otherwise the call waits for other threads' scopes; a
    /// refused wait returns the publisher its edge named. The caller holds
    /// `stateGate`.
    private func admitUpdateLocked() -> UInt64? {
        let caller = Self.currentThread
        if prePublishingThreads.contains(caller) { return caller }
        return awaitForeignScopesLocked()
    }

    /// Queues an update prepared against `base` for `publisher`, unless a
    /// re-entrant callback disposed the form or made another update meanwhile
    /// (§5.3 rule 2). The caller holds `stateGate`, so `publisher` still
    /// holds its scope or window and replays the queue.
    private func enqueueLocked(
        _ update: DeferredUpdate,
        for publisher: UInt64,
        preparedAgainst base: UpdateBase
    ) {
        guard isCurrentLocked(base) else { return }
        deferredUpdates[publisher, default: []].append(update)
        deferredGeneration &+= 1
    }

    /// Replays queued updates in call order, each as a new call (§5.3 rule
    /// 4): admission and preparation run again on the state at replay time,
    /// so a call replayed after disposal does nothing.
    private func replay(_ updates: [DeferredUpdate]) {
        for update in updates {
            switch update {
            case .setModel(let model): setModel(model)
            case .deny: performDeny()
            }
        }
    }

    /// The model captured by an admitted approval.
    private struct ApprovalAdmission {
        let captured: Model
    }

    /// Admits an approval when the form is not disposed, is valid, and has no
    /// approval in flight (§5.3). The in-flight mark and the capture happen
    /// together under `stateGate`; `canExecuteChanged` is then raised once
    /// outside it. Returns `nil` for a refused call, which has no effect.
    ///
    /// The command path passes `startingCommandTask` to start its persister
    /// task after that notification. An admission nested in an update on
    /// this thread queues both for the outermost update (#1057).
    ///
    /// Admission waits while another thread holds a publication scope. A
    /// wait that would close a wait-for cycle is refused, and the call is
    /// admitted without waiting (§5.5). The admission notification opens no
    /// scope.
    private func admitApproval(startingCommandTask: Bool = false) -> ApprovalAdmission? {
        stateGate.lock()
        _ = awaitForeignScopesLocked()
        guard !_disposed, _errors.isEmpty, !approvalInFlight else {
            stateGate.unlock()
            return nil
        }
        approvalInFlight = true
        let admission = ApprovalAdmission(captured: _model)
        var notices = Notices()
        notices.afterScope.append(.canExecuteChanged)
        if startingCommandTask {
            notices.afterScope.append(.startApproval(admission))
        }
        let delivery = takeNoticesLocked(notices)
        stateGate.unlock()
        deliver(delivery)
        return admission
    }

    /// Runs a command-path approval; a failure surfaces on ``approveErrors``.
    private func startCommandApproval(_ admission: ApprovalAdmission) {
        let context = UncheckedSendableBox((self, admission))
        Task { [context] in
            let (form, admitted) = context.value
            do {
                try await form.runApproval(admitted)
            } catch {
                form.emitApproveError(error)
            }
        }
    }

    /// Persists an admitted approval and settles it. A persister failure or
    /// cancellation, or a failed reset, settles before it is rethrown, so the
    /// caller routes it to exactly one channel.
    private func runApproval(_ admission: ApprovalAdmission) async throws {
        let captured = admission.captured
        // A form disposed since admission never starts the persister, an
        // external side effect (§10), and settles silently.
        let disposedBeforePersist = withStateGate { () -> Bool in
            guard _disposed else { return false }
            approvalInFlight = false
            return true
        }
        guard !disposedBeforePersist else { return }

        do {
            // Throw path — no state mutation if this throws.
            try await persister(captured)
        } catch {
            settleFailedPersistence()
            throw error
        }

        // Commit under the gate, then publish outside it: an observer may hand
        // work to another thread that reads this form (#533).
        switch commitApproval(captured) {
        case .published(let publication):
            publishApproval(publication)
        case .suppressed:
            return
        case .failed(let error, let scopeOpened):
            if scopeOpened { finishFailedSettlement() }
            throw error
        }
    }

    /// Settles an approval whose persister failed (§5.3). Like a commit, it
    /// first waits for other threads' publication scopes (§5.5).
    private func settleFailedPersistence() {
        let scopeOpened = withStateGate { () -> Bool in
            _ = awaitForeignScopesLocked()
            return beginFailedSettlementLocked()
        }
        if scopeOpened { finishFailedSettlement() }
    }

    /// Settlement step 1 of a failed approval: clears the in-flight mark and,
    /// unless the form was disposed meanwhile, opens the settlement scope.
    /// Returns whether the scope opened. The caller holds `stateGate`, after
    /// its scope wait.
    private func beginFailedSettlementLocked() -> Bool {
        approvalInFlight = false
        guard !_disposed else {
            // A replay after disposal does nothing.
            deferredUpdates.removeValue(forKey: Self.currentThread)
            return false
        }
        enterPublicationLocked()
        return true
    }

    /// Raises the failed settlement's `canExecuteChanged` once inside its
    /// scope, then closes the scope. The updates a failed post-persist commit
    /// queued, and other threads' refused updates, replay before the caller
    /// routes the failure (§5.3 rule 4, §5.5). A persister failure has no
    /// window, and the scope holds only this thread's queue: another
    /// approval's queue stays with its own thread.
    private func finishFailedSettlement() {
        _approveCanExecSubject.send(())
        replay(exitPublication())
    }

    /// Values an approval publishes once its state is committed.
    private struct ApprovalPublication {
        let approved: Model
        let errors: [String: String]?
    }

    /// The result of a post-persist commit.
    private enum ApprovalCommit {
        /// Committed; the settlement scope is open.
        case published(ApprovalPublication)
        /// Disposal suppressed the commit.
        case suppressed
        /// The commit failed and the approval settled. `scopeOpened` is
        /// `false` when the form was disposed meanwhile.
        case failed(Error, scopeOpened: Bool)
    }

    /// Commits a successful approval under `stateGate`, clears the in-flight
    /// mark, and opens this thread's settlement scope. A failed reset settles
    /// at once, with the gate still held.
    ///
    /// The commit first waits for other threads' publication scopes. A wait
    /// that would close a wait-for cycle is refused, and the commit proceeds
    /// at once: two threads then hold scopes (§5.5).
    ///
    /// The pre-publication window opens before the commit's callbacks run, so
    /// a `setModel` or deny from `resetOnApproved`, the snapshotter, or a
    /// validator is queued and publishes nothing under the gate (§5.1, §5.3).
    private func commitApproval(_ captured: Model) -> ApprovalCommit {
        stateGate.lock()
        defer { stateGate.unlock() }
        _ = awaitForeignScopesLocked()
        let caller = Self.currentThread
        prePublishingThreads.insert(caller)
        let committed: ApprovalPublication?
        do {
            commitCallbackDepth += 1
            defer { commitCallbackDepth -= 1 }
            committed = try completeApproval(captured)
        } catch {
            // The window ends with the failure; `finishFailedSettlement`
            // replays what the commit queued.
            prePublishingThreads.remove(caller)
            return .failed(error, scopeOpened: beginFailedSettlementLocked())
        }
        guard let publication = committed else {
            // Disposal suppressed the commit, and a replay after disposal
            // does nothing.
            prePublishingThreads.remove(caller)
            deferredUpdates.removeValue(forKey: caller)
            approvalInFlight = false
            return .suppressed
        }
        // Settlement clears the mark before publishing, so every observer
        // below sees an idle form and may start the next approval (§5.3).
        approvalInFlight = false
        enterPublicationLocked()
        return .published(publication)
    }

    /// Delivers a committed approval without holding `stateGate`, then admits
    /// waiting threads and replays the updates queued during pre-publication.
    /// Settlement order (§5.3): `errorsChanged` when the commit changed the
    /// error map, one `canExecuteChanged`, then `onApproved`.
    private func publishApproval(_ publication: ApprovalPublication) {
        defer { finishApprovalPublication() }
        if let errors = publication.errors {
            _errorsChanged.send(errors)
            guard !isDisposed else { return }
        }
        // The single settlement notification also covers any validity or
        // strict-mode change made by the commit.
        _approveCanExecSubject.send(())
        guard !isDisposed else { return }
        // The window ends when `onApproved` delivery starts: an update from
        // an `onApproved` sink is an ordinary update.
        withStateGate { _ = prePublishingThreads.remove(Self.currentThread) }
        _onApproved.send(publication.approved)
    }

    /// Ends the approval's settlement scope and replays this thread's queue
    /// (§5.3 rule 4, §5.5). The queue is taken as the scope closes, so no
    /// other thread can add to it afterwards. A Swift approval commits from
    /// its own task after awaiting the persister, so its scope never nests in
    /// another scope on this thread.
    private func finishApprovalPublication() {
        withStateGate { _ = prePublishingThreads.remove(Self.currentThread) }
        replay(exitPublication())
    }

    /// Opens a publication scope on this thread. The caller holds `stateGate`
    /// after its scope wait, so no other thread holds a scope unless that
    /// wait was refused (§5.5). A same-thread scope nests.
    private func enterPublicationLocked() {
        scopeDepths[Self.currentThread, default: 0] += 1
    }

    /// Closes one scope on this thread. When it was the thread's outermost
    /// scope, this removes the wait-for edges that name this thread, then
    /// wakes the waiting threads (ADR-0172 rule 3). It runs a teardown that
    /// waited for the scopes, and returns this thread's queue for the caller
    /// to replay (§5.5).
    private func exitPublication() -> [DeferredUpdate] {
        let caller = Self.currentThread
        let closed = withStateGate { () -> (deferred: [DeferredUpdate], tearDown: Bool)? in
            let depth = (scopeDepths[caller] ?? 1) - 1
            guard depth == 0 else {
                scopeDepths[caller] = depth
                return nil
            }
            scopeDepths.removeValue(forKey: caller)
            if scopeWaitsRecorded {
                ThreadWaitGraph.shared.release(resource: scopeResource, owner: caller)
                if scopeDepths.isEmpty { scopeWaitsRecorded = false }
            }
            return (deferredUpdates.removeValue(forKey: caller) ?? [], takeTeardownLocked())
        }
        guard let closed else { return [] }
        scopeFinished.lock()
        scopeGeneration &+= 1
        scopeFinished.broadcast()
        scopeFinished.unlock()
        if closed.tearDown { tearDown() }
        return closed.deferred
    }

    /// The wait-for graph resource of this form's publication scopes.
    private var scopeResource: ObjectIdentifier { ObjectIdentifier(scopeFinished) }

    /// Waits, releasing `stateGate`, while another thread holds a publication
    /// scope (§5.5). Each wait records an edge in `ThreadWaitGraph` to one
    /// publisher, and the waiter records again when it wakes. Returns `nil`
    /// once no other thread holds a scope, or the form is disposed.
    ///
    /// Returns the publisher that the edge named when the wait would close a
    /// wait-for cycle. The caller then takes its §5.5 escape without waiting.
    /// A call nested in a callback that runs under `stateGate` takes the same
    /// escape, because it cannot release the gate for the publisher.
    ///
    /// Otherwise the caller holds `stateGate` exactly once: a scope opens
    /// only under the gate, so no other thread can be inside it.
    private func awaitForeignScopesLocked() -> UInt64? {
        let caller = Self.currentThread
        while !_disposed, let owner = scopeDepths.keys.first(where: { $0 != caller }) {
            guard preparationDepth == 0, commitCallbackDepth == 0,
                  ThreadWaitGraph.shared.beginWait(caller: caller, owner: owner, resource: scopeResource)
            else { return owner }
            scopeWaitsRecorded = true
            scopeFinished.lock()
            let generation = scopeGeneration
            stateGate.unlock()
            while scopeGeneration == generation { scopeFinished.wait() }
            scopeFinished.unlock()
            ThreadWaitGraph.shared.endWait(caller: caller)
            stateGate.lock()
        }
        return nil
    }

    /// `true`, once, when a requested teardown may run on this thread: no
    /// update is active, and no other thread holds a publication scope. After
    /// a refused disposal wait, no thread may hold one (§5.5, §10). The
    /// caller holds `stateGate`.
    private func takeTeardownLocked() -> Bool {
        let caller = Self.currentThread
        let scopesEnded = teardownAfterScopes
            ? scopeDepths.isEmpty
            : scopeDepths.keys.allSatisfy { $0 == caller }
        guard teardownPending, activeMutations == 0, scopesEnded else { return false }
        teardownPending = false
        return true
    }

    private var isDisposed: Bool { withStateGate { _disposed } }

    private static var currentThread: UInt64 {
        UInt64(pthread_mach_thread_np(pthread_self()))
    }

    private func completeApproval(_ captured: Model) throws -> ApprovalPublication? {
        guard !_disposed else { return nil }
        let currentErrors = _errors

        let nextModel: Model?
        let nextSnapshot: Model
        let nextErrors: [String: String]?
        if let resetOnApproved {
            let reset = try resetOnApproved(captured)
            guard !_disposed else { return nil }
            let preparedModel = snapshotter(reset)
            guard !_disposed else { return nil }
            nextModel = preparedModel
            nextSnapshot = snapshotter(reset)
            guard !_disposed else { return nil }
            nextErrors = Self.validate(
                preparedModel,
                validators: validators,
                modelValidator: modelValidator
            )
            guard !_disposed else { return nil }
        } else {
            nextModel = nil
            nextSnapshot = snapshotter(captured)
            guard !_disposed else { return nil }
            nextErrors = nil
        }

        let committedErrors = nextErrors ?? currentErrors
        let errorsChanged = committedErrors != currentErrors

        // Like every commit, the approval advances the generation (§5.4); it
        // remains authoritative over earlier edits (§5.1, §5.3).
        commitGeneration &+= 1
        if let nextModel { _model = nextModel }
        _snapshot = nextSnapshot
        if nextErrors != nil { _errors = committedErrors }
        return ApprovalPublication(
            approved: captured,
            errors: errorsChanged ? committedErrors : nil
        )
    }

    private func canApprove() -> Bool {
        // `equals` runs after the gate is released, as in `isDirty`, so a
        // callback that updates the form cannot wait for another thread's
        // publication scope while it holds the gate (#704).
        let state = withStateGate { () -> (model: Model, snapshot: Model)? in
            guard !_disposed, _errors.isEmpty, !approvalInFlight else { return nil }
            return (_model, _snapshot)
        }
        guard let state else { return false }
        guard strict else { return true }
        return !equals(state.model, state.snapshot)
    }

    private func endMutation() {
        stateGate.lock()
        activeMutations -= 1
        let shouldTearDown = takeTeardownLocked()
        stateGate.unlock()
        if shouldTearDown { tearDown() }
    }

    private func tearDown() {
        _onApproved.send(completion: .finished)
        _approveErrors.send(completion: .finished)
        _errorsChanged.send(completion: .finished)
        _approveCanExecSubject.send(completion: .finished)
        denyCommand.dispose()
        approveCommand.dispose()
    }

    private func withStateGate<T>(_ action: () throws -> T) rethrows -> T {
        stateGate.lock()
        defer { stateGate.unlock() }
        return try action()
    }

    private static func validate(
        _ model: Model,
        validators: [String: (Model) -> String?],
        modelValidator: ((Model) -> [String: String?])?
    ) -> [String: String] {
        var errors: [String: String] = [:]
        for (field, validator) in validators {
            if let error = validator(model) {
                errors[field] = error
            }
        }
        if let modelValidator {
            for (field, error) in modelValidator(model) {
                if let error {
                    errors[field] = error
                } else {
                    errors.removeValue(forKey: field)
                }
            }
        }
        return errors
    }

    /// Routes a command-path failure to ``approveErrors`` after settlement.
    /// Sent outside `stateGate`, like every settlement notification (§5.3);
    /// a failure that lands after disposal is dropped (§8.2).
    private func emitApproveError(_ error: Error) {
        guard !isDisposed else { return }
        _approveErrors.send(error)
    }
}

// ─── Builder entry point ─────────────────────────────────────────────────────

extension FormVM {
    /// Entry point for the immutable fluent builder. Mirrors the `.builder()`
    /// convention used by other VM family members. See spec/10-builders.md §3
    /// and ADR-0035 §2 FV1/FV2.
    public static func builder() -> FormVMBuilder<Model> {
        FormVMBuilder<Model>()
    }
}

// ─── Equatable convenience initializer ───────────────────────────────────────
//
// When `Model` conforms to `Equatable`, the caller does not need to supply an
// explicit `equals` predicate — structural `==` is the correct default.
// Mirrors the `ComponentVMOf` Equatable convenience-init pattern exactly.

extension FormVM where Model: Equatable {
    /// Convenience initializer for `Equatable` models — defaults `equals` to
    /// `==`.
    public convenience init(
        initial: Model,
        persister: @escaping (Model) async throws -> Void,
        hub: MessageHubProtocol = NullMessageHub.INSTANCE,
        strict: Bool = false,
        snapshotter: @escaping (Model) -> Model = { $0 },
        validators: [String: (Model) -> String?] = [:],
        modelValidator: ((Model) -> [String: String?])? = nil,
        resetOnApproved: ((Model) throws -> Model)? = nil
    ) {
        self.init(
            initial: initial,
            persister: persister,
            hub: hub,
            strict: strict,
            snapshotter: snapshotter,
            validators: validators,
            modelValidator: modelValidator,
            resetOnApproved: resetOnApproved,
            equals: ==
        )
    }
}
