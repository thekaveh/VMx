//
// CompositeVM<VM> — homogeneous-child container with a `current`
// selection slot.
//
// See spec/06-composite-vm.md. The Swift flavor is at full library parity as
// of v3.1.0; this type covers child mutation, selection, lifecycle cascade,
// batch updates, async selection, and CollectionChanged events.
//
import Foundation
import Combine

private struct ContainerDisposalAdmissionError: Error {}
private let compositeCurrentChangeCoordinator = NSRecursiveLock()

public struct CompositeVMOptions<Child: ComponentVMBase> {
    public var name: String?
    public var hint: String
    public var hub: MessageHubProtocol?
    public var dispatcher: Dispatcher?
    public var children: (() -> [Child])?
    public var current: (([Child]) -> Child?)?
    public var onCurrentChanged: ((Child?) -> Void)?
    public var onConstruct: (() throws -> Void)?
    public var onDestruct: (() -> Void)?
    public var autoConstructOnAdd: Bool
    public var asyncSelection: Bool
    /// The order in which the composite destructs and disposes its children
    /// (default `.insertion`, ADR-0161).
    public var destructOrder: ChildOrder

    public init(
        name: String? = nil,
        hint: String = "",
        hub: MessageHubProtocol? = nil,
        dispatcher: Dispatcher? = nil,
        children: (() -> [Child])? = nil,
        current: (([Child]) -> Child?)? = nil,
        onCurrentChanged: ((Child?) -> Void)? = nil,
        onConstruct: (() throws -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        autoConstructOnAdd: Bool = false,
        asyncSelection: Bool = false,
        destructOrder: ChildOrder = .insertion
    ) {
        self.name = name
        self.hint = hint
        self.hub = hub
        self.dispatcher = dispatcher
        self.children = children
        self.current = current
        self.onCurrentChanged = onCurrentChanged
        self.onConstruct = onConstruct
        self.onDestruct = onDestruct
        self.autoConstructOnAdd = autoConstructOnAdd
        self.asyncSelection = asyncSelection
        self.destructOrder = destructOrder
    }
}

open class CompositeVM<Child: ComponentVMBase>:
    ComponentVMBase, ParentVM, TransactionalOwnershipParentVM, ChildDisposalObserver, _Batchable,
    SelectableVMCollection, ObservableMembershipSource {
    private var children: [Child] = []
    private var _current: Child?
    private let childrenFactory: (() -> [Child])?
    private let currentSelector: (([Child]) -> Child?)?
    private let onCurrentChanged: ((Child?) -> Void)?
    private var populated = false
    /// Collects the children population started constructing (see `_onConstruct`).
    private var populationJoined: [ComponentVMBase]?
    private let _autoConstructOnAdd: Bool
    private let _asyncSelection: Bool
    /// The order of the destruct walk and the dispose cascade (ADR-0161).
    let destructOrder: ChildOrder
    private var disposeRequested = false
    private var disposeDeferred = false
    private var membershipTransactionActive = false
    private var membershipTransactionToken: ContainerOwnershipTransaction?
    private var membershipTransactionDepth = 0
    private var membershipTransactionOwner: UInt64?
    private var membershipTransactionCompletion: DispatchGroup?
    /// Membership wait edges on this container; guarded by `membershipGate`.
    private var membershipWaits = 0
    private var activeCurrentPublications = 0
    /// The threads that hold a current-publication lease, one entry per
    /// lease (spec/06 §4.3 rule 5); guarded by `membershipGate`.
    private var currentPublicationThreads: [UInt64] = []
    /// Children that an add, insert, replacement or population attached but
    /// has not admitted yet. They are not members for selection (spec/06
    /// §4.3 rule 2); guarded by `membershipGate`.
    private var pendingAdmissions = Set<ObjectIdentifier>()
    /// Children detached from this composite for a transfer whose commit or
    /// rollback has not run (spec/06 §4.3 rule 4); guarded by `membershipGate`.
    private var pendingTransferDetaches = 0
    /// Set once the composite's dispose hook has run. Selection is then inert,
    /// as it was before ADR-0173 (chapter 01 §4); guarded by `membershipGate`.
    private var disposeCompleted = false
    private let membershipGate = NSRecursiveLock()
    /// Start records of the auto-construct adds the construct walk can pull
    /// as late children (spec/06 §5.1).
    private let lateStarts = LateChildStarts()

    // ── Batch-update state ──────────────────────────────────────────────

    private var _batchLevel = 0
    private var _batchDirty = false

    // ── CollectionChanged publisher ─────────────────────────────────────

    private let collectionChangedSubject = PassthroughSubject<CollectionChangedEvent, Never>()

    /// Emits a `CollectionChangedEvent` after each `add` or `remove` mutation.
    /// During a batch, granular events are suppressed; `dispose()` on the
    /// returned `BatchUpdateHandle` emits a single `.reset` (if dirty).
    ///
    /// Each event is followed by one `CollectionChangedMessage<ComponentVMBase>`
    /// sent by this composite on `hub` (spec/01 §1.4, ADR-0142).
    public var collectionChanged: AnyPublisher<CollectionChangedEvent, Never> {
        collectionChangedSubject.eraseToAnyPublisher()
    }

    /// Begin a batch update. Per-mutation `CollectionChanged` events are
    /// suppressed until `dispose()` is called on the returned handle, at which
    /// point a single `.reset` event is emitted (only if a mutation occurred).
    /// Nested `batchUpdate()` calls are supported via a reference counter; the
    /// reset fires only when the outermost batch ends.
    public func batchUpdate() -> BatchUpdateHandle {
        _batchLevel += 1
        return BatchUpdateHandle(owner: self)
    }

    /// Called by `BatchUpdateHandle.dispose()` — do not call directly.
    func _exitBatch() {
        guard _batchLevel > 0 else { return }
        _batchLevel -= 1
        if _batchLevel == 0 && _batchDirty {
            _batchDirty = false
            deliverCollectionChanged(.reset())
        }
    }

    public init(
        name: String,
        hint: String = "",
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        childrenFactory: (() -> [Child])? = nil,
        onConstruct: (() throws -> Void)? = nil,
        onDestruct: (() -> Void)? = nil,
        currentSelector: (([Child]) -> Child?)? = nil,
        onCurrentChanged: ((Child?) -> Void)? = nil,
        autoConstructOnAdd: Bool = false,
        asyncSelection: Bool = false,
        destructOrder: ChildOrder = .insertion
    ) {
        self.childrenFactory = childrenFactory
        self.currentSelector = currentSelector
        self.onCurrentChanged = onCurrentChanged
        self._autoConstructOnAdd = autoConstructOnAdd
        self._asyncSelection = asyncSelection
        self.destructOrder = destructOrder
        super.init(
            name: name, hint: hint,
            hub: hub, dispatcher: dispatcher,
            onConstruct: onConstruct, onDestruct: onDestruct
        )
    }

    open override var type: ViewModelType { .composite }

    // ── ParentVM ────────────────────────────────────────────────────────

    public var supportsChildSelection: Bool { true }

    public var currentChild: ComponentVMBase? { membershipGate.withLock { _current } }

    public func selectChild(_ vm: ComponentVMBase) {
        // Mirror C# `CanSelectComponent`: the target must be a member *and*
        // Constructed. C# throws on a violation; Swift keeps the existing
        // no-op rather than introducing an (uncatchable) trap — the
        // trap-vs-throw recoverability gap is tracked separately (ADR-0037).
        // Every other refusal of spec/06 §4.3 is a silent no-op here too, as
        // in every flavor (spec/05 §6, ADR-0188). The commit checks
        // Constructed again under its locks (#1220).
        guard vm.status == .constructed,
              let child = membershipGate.withLock({ children.first(where: { $0 === vm }) })
        else { return }
        _ = _requestSelection(child, requireConstructed: true)
    }

    public func deselectChild(_ vm: ComponentVMBase) {
        guard let child = membershipGate.withLock({ _current }), child === vm else { return }
        _ = _requestSelection(nil, expectedCurrent: child)
    }

    /// The dispose clear (spec/06 §4.3 rule 9, ADR-0189): `vm` published
    /// Disposed from its own `dispose()`. Clears `current` only while the
    /// child with `vm`'s ownership identity is still current, so a
    /// forwarding decorator works. It is not a selection call, so rules 3,
    /// 4 and 8 never refuse it. The composite's own dispose cascade skips
    /// it: the clear does not run while disposal of the composite is
    /// requested or deferred, or after Disposed.
    func childDisposed(_ vm: ComponentVMBase) {
        let identity = vm._ownershipIdentity
        let caller = ThreadWaitGraph.currentThread
        let disposed = _isDisposalRequested()
        let outcome: CompositeSelectionOutcome<Child> = {
            compositeCurrentChangeCoordinator.lock()
            defer { compositeCurrentChangeCoordinator.unlock() }
            return membershipGate.withLock {
                guard !disposed, !disposeRequested, !disposeDeferred, !disposeCompleted,
                      let current = _current, current._ownershipIdentity === identity
                else { return .unchanged }
                return _commitSelectionLocked(
                    nil,
                    selectionCall: false,
                    expectedCurrent: current,
                    validateOnly: false,
                    caller: caller,
                    disposed: disposed
                )
            }
        }()
        _publishSelection(outcome, to: nil)
    }

    var ownershipOwner: ComponentVMBase { self }
    // The parent of this ownership identity, including a forwarding
    // decorator's parent when only the decorator is parented (#724).
    var ownershipOwnerParent: OwnershipParentVM? { _transferOwnershipParent }

    func containsIdentity(_ vm: ComponentVMBase) -> Bool {
        let identity = vm._ownershipIdentity
        return membershipGate.withLock {
            children.contains(where: { $0._ownershipIdentity === identity })
        }
    }

    func detachForTransfer(_ vm: ComponentVMBase) throws -> ParentTransfer {
        try detachForTransfer(vm, transaction: ContainerOwnershipTransaction())
    }

    func detachForTransfer(
        _ vm: ComponentVMBase,
        transaction: ContainerOwnershipTransaction
    ) throws -> ParentTransfer {
        try joinMembershipTransaction(transaction)
        let detached: (Int, Child, Bool)
        do {
            detached = try membershipGate.withLock {
                let identity = vm._ownershipIdentity
                guard let index = children.firstIndex(where: {
                    $0._ownershipIdentity === identity
                }) else {
                    throw ContainerOwnershipError.inconsistentParent
                }
                let child = children.remove(at: index)
                // Uncommitted until the commit or rollback runs (spec/06 §4.3
                // rule 4).
                pendingTransferDetaches += 1
                return (index, child, _current === child)
            }
        } catch {
            endMembershipTransaction()
            throw error
        }
        let (index, child, wasCurrent) = detached
        return ParentTransfer(
            commit: {
                defer { self.endMembershipTransaction() }
                self.membershipGate.withLock { self.pendingTransferDetaches -= 1 }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
                // Clear only while the detached child is still current: a
                // selection made after the detach stays (spec/06 §4.3 rule 6).
                if wasCurrent { self._clearDetachedCurrent(child) }
                self.emit(.removed(child, at: index))
            },
            rollback: {
                defer { self.endMembershipTransaction() }
                self.membershipGate.withLock {
                    self.pendingTransferDetaches -= 1
                    guard !self.disposeRequested else {
                        child._parent = nil
                        child._ownershipParent = nil
                        return
                    }
                    self.children.insert(child, at: Swift.min(index, self.children.count))
                    child._parent = self
                    child._ownershipParent = self
                }
            }
        )
    }

    // ── Public collection surface ───────────────────────────────────────

    public var count: Int { membershipGate.withLock { children.count } }

    public func at(_ index: Int) -> Child {
        membershipGate.withLock { children[index] }
    }

    public func makeIterator() -> AnyIterator<Child> {
        var iterator = snapshot().makeIterator()
        return AnyIterator { iterator.next() }
    }

    public func snapshot() -> [Child] { membershipGate.withLock { children } }

    public func subscribeMembership(_ callback: @escaping () -> Void) -> AnyCancellable {
        collectionChanged.sink { _ in callback() }
    }

    /// The selected child, or `nil`.
    ///
    /// The **setter traps** (`preconditionFailure`) where `setCurrent(_:)`
    /// throws: on a value that is not an admitted member of this composite
    /// or is Disposed (spec/06 §3 — `Current` must be a member; ADR-0189),
    /// on a non-`nil` value while
    /// disposal of the composite is pending, and on any value inside the
    /// caller's own uncommitted membership transaction (spec/06 §4.3). Swift
    /// property setters cannot be `throws`, so the recoverable path is
    /// `setCurrent(_:)` / `canSetCurrent(_:)` (VMX-026 / ADR-0053, ADR-0009).
    /// The trapping setter is retained (not deprecated) for ergonomic binding
    /// of an already-validated member — assigning a known child or `nil` is
    /// the common case and never traps.
    public var current: Child? {
        get { membershipGate.withLock { _current } }
        set { _setCurrent(newValue) }
    }

    /// Pre-flight predicate for `setCurrent(_:)` / the `current` setter: returns
    /// `true` iff the assignment would not be refused now. `nil` is refused
    /// only inside the caller's own uncommitted membership transaction; a
    /// child must also be an admitted member that is not Disposed while no
    /// disposal of the composite is pending (spec/06 §3, §4.3, ADR-0173,
    /// ADR-0189). After Disposed an assignment of a member or `nil` is an
    /// inert no-op, not a refusal, so the predicate returns `true` for it.
    /// While the composite is Destructing, a child assignment changes
    /// nothing, so the predicate returns `false` for it (ADR-0188).
    public func canSetCurrent(_ value: Child?) -> Bool {
        switch _commitSelection(value, selectionCall: true, validateOnly: true) {
        case .refused, .ignored: return false
        case .inert, .committed, .unchanged: return true
        }
    }

    /// Throwing, catchable alternative to the `current` property setter
    /// (VMX-026 / ADR-0053). Throws `CompositeMembershipError` where the
    /// property setter traps: on a non-member, unadmitted or Disposed child,
    /// on a child
    /// while disposal of the composite is pending, and inside the caller's
    /// own uncommitted membership transaction (spec/06 §4.3). Another thread's
    /// membership transaction never makes it fail or wait (ADR-0173).
    public func setCurrent(_ value: Child?) throws {
        if let refusal = _requestSelection(value) {
            throw CompositeMembershipError(
                memberName: value?.name ?? "<nil>", compositeName: name, reason: refusal
            )
        }
    }

    /// Pre-flight predicate for `selectComponent(_:)`: returns `true` iff
    /// `selectComponent(vm)` would select `vm` now: `vm` is an admitted member
    /// and Constructed, no disposal of the composite is pending, the
    /// composite is not Destructing, and the caller is not inside its own
    /// uncommitted membership transaction (spec/06 §3.1, ADR-0173,
    /// ADR-0188).
    ///
    /// This is distinct from `canSetCurrent(_:)`, which has no Constructed
    /// gate (spec/06 §3.1). Swift throws catchably (ADR-0053) where C#
    /// surfaces `InvalidOperationException`.
    public func canSelectComponent(_ vm: Child) -> Bool {
        guard vm.status == .constructed else { return false }
        switch _commitSelection(
            vm, selectionCall: true, requireConstructed: true, validateOnly: true
        ) {
        case .committed, .unchanged: return true
        case .refused, .inert, .ignored: return false
        }
    }

    /// Selects `vm` as the current child, throwing `CompositeMembershipError`
    /// if `canSelectComponent(vm)` returns `false` (spec/06 §3.1 / COMP-008).
    /// The one exception: while the composite is Destructing, a selection
    /// that only spec/06 §4.3 rule 8 refuses changes nothing and throws
    /// nothing (ADR-0188).
    ///
    /// Swift convergence of the C#/TypeScript `selectComponent` throwing path
    /// (ADR-0053): catchable throw rather than a trap, unlike the `current`
    /// property setter which cannot be `throws` in Swift.
    public func selectComponent(_ vm: Child) throws {
        guard vm.status == .constructed else {
            throw CompositeMembershipError(
                memberName: vm.name, compositeName: name, reason: .notConstructed
            )
        }
        // The commit checks Constructed again under its locks, so a destruct
        // on another thread after this check cannot pass it (#1220).
        if let refusal = _requestSelection(vm, requireConstructed: true) {
            throw CompositeMembershipError(memberName: vm.name, compositeName: name, reason: refusal)
        }
    }

    /// Deselects `vm`, clearing the current slot, throwing
    /// `CompositeMembershipError` if `vm` is not the current selection
    /// (spec/06 §3.1 / COMP-011) or the caller is inside its own uncommitted
    /// membership transaction (spec/06 §4.3).
    ///
    /// Swift convergence of the C#/TypeScript `deselectComponent` throwing path
    /// (ADR-0053): catchable throw rather than a trap.
    public func deselectComponent(_ vm: Child) throws {
        if let refusal = _requestSelection(nil, expectedCurrent: vm) {
            throw CompositeMembershipError(memberName: vm.name, compositeName: name, reason: refusal)
        }
    }

    public func add(_ child: Child) {
        if case let .failure(error) = addResult(child) {
            assertionFailure("CompositeVM.add failed — \(error)")
        }
    }

    @discardableResult
    public func addResult(_ child: Child) -> Result<Void, ContainerOwnershipError> {
        let transaction: ContainerOwnershipTransaction
        do { transaction = try beginMembershipTransaction() } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        defer { endMembershipTransaction() }
        let originalStatus = child.status
        let transfer: ParentTransfer?
        do {
            transfer = try beginParentTransfer(child, to: self, transaction: transaction)
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        membershipGate.lock()
        do {
            try requireTransactionCanContinueLocked()
        } catch {
            membershipGate.unlock()
            transfer?.rollback()
            return .failure(.attachmentFailed(error))
        }
        children.append(child)
        child._parent = self
        child._ownershipParent = self
        pendingAdmissions.insert(ObjectIdentifier(child))
        let lateStart = registerLateStartLocked(child)
        membershipGate.unlock()
        // When autoConstructOnAdd is set and the composite is already
        // Constructed, construct the child BEFORE emitting the Add event
        // (COMP-012). `add` is non-throwing per the public API contract;
        // failures surface through assertionFailure in debug/test builds.
        // Divergence from TS (which throws on failure) is recorded in ADR-0060.
        if let error = autoConstructAttached(child, record: lateStart) {
            membershipGate.withLock {
                lateStarts.remove(child, lateStart)
                pendingAdmissions.remove(ObjectIdentifier(child))
                if let attached = children.firstIndex(where: { $0 === child }) {
                    children.remove(at: attached)
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            transfer?.rollback()
            return .failure(.attachmentFailed(error))
        }
        do {
            try membershipGate.withLock {
                try requireTransactionCanContinueLocked()
            }
        } catch {
            membershipGate.withLock {
                pendingAdmissions.remove(ObjectIdentifier(child))
                if let attached = children.firstIndex(where: { $0 === child }) {
                    children.remove(at: attached)
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            var compensationError: Error?
            if originalStatus == .destructed && child.status == .constructed {
                do { try child.destruct() } catch { compensationError = error }
            }
            transfer?.rollback()
            if let compensationError {
                return .failure(.attachmentFailed(compensationError))
            }
            return .failure(.attachmentFailed(error))
        }
        // Commit the old-parent removal before publishing the destination add.
        transfer?.commit()
        // Admit the child only after the old parent's detach commit, which
        // clears the child's isCurrent flag there: a selection in this
        // composite made before that commit would leave the flag false while
        // the child is current here (COMP-006). The admission still precedes
        // CollectionChanged (spec/06 §4.3 rule 2).
        membershipGate.withLock { _ = pendingAdmissions.remove(ObjectIdentifier(child)) }
        // Emit AFTER the child is appended, parent is wired, and (if
        // autoConstructOnAdd) the child has been constructed.
        let index = membershipGate.withLock {
            children.firstIndex(where: { $0 === child }) ?? Swift.max(children.count - 1, 0)
        }
        if _batchLevel > 0 {
            _batchDirty = true
        } else {
            deliverCollectionChanged(.added(child, at: index))
        }
        return .success(())
    }

    public func insert(_ child: Child, at index: Int) {
        _ = insertResult(child, at: index)
    }

    @discardableResult
    public func insertResult(
        _ child: Child,
        at index: Int
    ) -> Result<Void, ContainerOwnershipError> {
        let transaction: ContainerOwnershipTransaction
        do { transaction = try beginMembershipTransaction() } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        defer { endMembershipTransaction() }
        let originalStatus = child.status
        let childCount = membershipGate.withLock { children.count }
        guard index >= 0 && index <= childCount else {
            return .failure(.attachmentFailed(VMCollectionIndexError(index: index, count: childCount)))
        }
        let transfer: ParentTransfer?
        do {
            transfer = try beginParentTransfer(child, to: self, transaction: transaction)
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        membershipGate.lock()
        do {
            try requireTransactionCanContinueLocked()
        } catch {
            membershipGate.unlock()
            transfer?.rollback()
            return .failure(.attachmentFailed(error))
        }
        children.insert(child, at: index)
        child._parent = self
        child._ownershipParent = self
        pendingAdmissions.insert(ObjectIdentifier(child))
        let lateStart = registerLateStartLocked(child)
        membershipGate.unlock()
        if let error = autoConstructAttached(child, record: lateStart) {
            membershipGate.withLock {
                lateStarts.remove(child, lateStart)
                pendingAdmissions.remove(ObjectIdentifier(child))
                if let attached = children.firstIndex(where: { $0 === child }) {
                    children.remove(at: attached)
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            transfer?.rollback()
            return .failure(.attachmentFailed(error))
        }
        do {
            try membershipGate.withLock {
                try requireTransactionCanContinueLocked()
            }
        } catch {
            membershipGate.withLock {
                pendingAdmissions.remove(ObjectIdentifier(child))
                if let attached = children.firstIndex(where: { $0 === child }) {
                    children.remove(at: attached)
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            var compensationError: Error?
            if originalStatus == .destructed && child.status == .constructed {
                do { try child.destruct() } catch { compensationError = error }
            }
            transfer?.rollback()
            if let compensationError {
                return .failure(.attachmentFailed(compensationError))
            }
            return .failure(.attachmentFailed(error))
        }
        transfer?.commit()
        // Admit the child only after the old parent's detach commit, which
        // clears the child's isCurrent flag there: a selection in this
        // composite made before that commit would leave the flag false while
        // the child is current here (COMP-006). The admission still precedes
        // CollectionChanged (spec/06 §4.3 rule 2).
        membershipGate.withLock { _ = pendingAdmissions.remove(ObjectIdentifier(child)) }
        emit(.added(child, at: index))
        return .success(())
    }

    public func remove(_ child: Child) -> Bool {
        guard (try? beginMembershipTransaction()) != nil else { return false }
        defer { endMembershipTransaction() }
        let removed = _detachClearingCurrent { () -> ((Child, Int), Child?)? in
            guard let index = children.firstIndex(where: { $0 === child }) else { return nil }
            let item = children.remove(at: index)
            if item._ownershipParent === self {
                item._parent = nil
                item._ownershipParent = nil
            }
            return ((item, index), item)
        }
        guard let ((item, index), clear) = removed else { return false }
        _publishSelection(clear, to: nil)
        emit(.removed(item, at: index))
        return true
    }

    public func removeAt(_ index: Int) {
        guard (try? beginMembershipTransaction()) != nil else { return }
        defer { endMembershipTransaction() }
        let removal = _detachClearingCurrent { () -> (Child, Child?)? in
            let removed = children.remove(at: index)
            if removed._ownershipParent === self {
                removed._parent = nil
                removed._ownershipParent = nil
            }
            return (removed, removed)
        }
        guard let (item, clear) = removal else { return }
        _publishSelection(clear, to: nil)
        // Emit AFTER the child has been removed and parent cleared.
        emit(.removed(item, at: index))
    }

    public func replace(at index: Int, with child: Child) {
        _ = replaceResult(at: index, with: child)
    }

    @discardableResult
    public func replaceResult(
        at index: Int,
        with child: Child
    ) -> Result<Void, ContainerOwnershipError> {
        let transaction: ContainerOwnershipTransaction
        do { transaction = try beginMembershipTransaction() } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        defer { endMembershipTransaction() }
        let originalStatus = child.status
        let childCount = membershipGate.withLock { children.count }
        guard index >= 0 && index < childCount else {
            return .failure(.attachmentFailed(VMCollectionIndexError(index: index, count: childCount)))
        }
        let transfer: ParentTransfer?
        do {
            transfer = try beginParentTransfer(child, to: self, transaction: transaction)
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        membershipGate.lock()
        do {
            try requireTransactionCanContinueLocked()
        } catch {
            membershipGate.unlock()
            transfer?.rollback()
            return .failure(.attachmentFailed(error))
        }
        // `old` keeps this composite as its parent until the commit, which
        // frees it and clears `current` in one locked section. Until then no
        // other container can adopt it while it is still current here
        // (COMP-006), and a rollback can always put it back (#1219).
        let old = children[index]
        children[index] = child
        child._parent = self
        child._ownershipParent = self
        pendingAdmissions.insert(ObjectIdentifier(child))
        let lateStart = registerLateStartLocked(child)
        membershipGate.unlock()
        if let error = autoConstructAttached(child, record: lateStart) {
            membershipGate.withLock {
                lateStarts.remove(child, lateStart)
                pendingAdmissions.remove(ObjectIdentifier(child))
                if let attached = children.firstIndex(where: { $0 === child }) {
                    children[attached] = old
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            transfer?.rollback()
            return .failure(.attachmentFailed(error))
        }
        do {
            try membershipGate.withLock {
                try requireTransactionCanContinueLocked()
            }
        } catch {
            membershipGate.withLock {
                pendingAdmissions.remove(ObjectIdentifier(child))
                if let attached = children.firstIndex(where: { $0 === child }) {
                    children[attached] = old
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            var compensationError: Error?
            if originalStatus == .destructed && child.status == .constructed {
                do { try child.destruct() } catch { compensationError = error }
            }
            transfer?.rollback()
            if let compensationError {
                return .failure(.attachmentFailed(compensationError))
            }
            return .failure(.attachmentFailed(error))
        }
        transfer?.commit()
        // Admit the child only after the old parent's detach commit, which
        // clears the child's isCurrent flag there: a selection in this
        // composite made before that commit would leave the flag false while
        // the child is current here (COMP-006). The admission still precedes
        // CollectionChanged (spec/06 §4.3 rule 2).
        membershipGate.withLock { _ = pendingAdmissions.remove(ObjectIdentifier(child)) }
        // Free `old` and clear `current` in one section, as removeAt does.
        let detached = _detachClearingCurrent { () -> (Void, Child?)? in
            if old._ownershipParent === self {
                old._parent = nil
                old._ownershipParent = nil
            }
            return ((), old)
        }
        if let (_, clear) = detached { _publishSelection(clear, to: nil) }
        emit(.removed(old, at: index))
        emit(.added(child, at: index))
        return .success(())
    }

    public func clear() {
        guard (try? beginMembershipTransaction()) != nil else { return }
        defer { endMembershipTransaction() }
        let cleared = _detachClearingCurrent { () -> (Void, Child?)? in
            let previous = _current
            for child in children where child._ownershipParent === self {
                child._parent = nil
                child._ownershipParent = nil
            }
            children.removeAll()
            return ((), previous)
        }
        guard let (_, clear) = cleared else { return }
        _publishSelection(clear, to: nil)
        emit(.reset())
    }

    public func move(from fromIndex: Int, to toIndex: Int) throws {
        let child: Child? = try membershipGate.withLock {
            guard !disposeRequested && !disposeDeferred else {
                throw ContainerOwnershipError.attachmentFailed(ContainerDisposalAdmissionError())
            }
            guard !membershipTransactionActive else {
                throw ContainerOwnershipError.attachmentFailed(ContainerMembershipTransactionError())
            }
            try validateMoveIndex(fromIndex)
            try validateMoveIndex(toIndex)
            guard fromIndex != toIndex else { return nil }
            let item = children.remove(at: fromIndex)
            children.insert(item, at: toIndex)
            return item
        }
        guard let child else { return }
        emit(.moved(child, from: fromIndex, to: toIndex))
    }

    private func validateMoveIndex(_ index: Int) throws {
        guard index >= 0 && index < children.count else {
            throw VMCollectionIndexError(index: index, count: children.count)
        }
    }

    private func emit(_ event: CollectionChangedEvent) {
        if _batchLevel > 0 {
            _batchDirty = true
        } else {
            deliverCollectionChanged(event)
        }
    }

    /// Delivers `event` locally, then publishes it on `hub` (see
    /// `ContainerSupport.deliverCollectionChanged`). A disposed composite
    /// publishes nothing.
    private func deliverCollectionChanged(_ event: CollectionChangedEvent) {
        ContainerSupport.deliverCollectionChanged(
            event,
            from: self,
            subject: collectionChangedSubject,
            gate: membershipGate,
            disposeRequested: { disposeRequested }
        )
    }

    // ── Lifecycle overrides ─────────────────────────────────────────────

    /// Supplies the construct walk with each late child whose add starts it
    /// (see `ContainerSupport.lateChildSource`).
    private func lateChildSource(
        after snapshot: [Child],
        scope: LateChildStarts.Scope?
    ) -> LateChildSource? {
        ContainerSupport.lateChildSource(
            for: self,
            after: snapshot,
            scope: scope,
            autoConstructOnAdd: _autoConstructOnAdd,
            starts: lateStarts,
            gate: membershipGate,
            children: { $0.children }
        )
    }

    /// Call under `membershipGate`, in the section that attaches `child`
    /// (see `ContainerSupport.registerLateStartLocked`).
    private func registerLateStartLocked(_ child: Child) -> LateChildStarts.Record? {
        ContainerSupport.registerLateStartLocked(
            child, in: self, autoConstructOnAdd: _autoConstructOnAdd, starts: lateStarts
        )
    }

    /// Auto-construct-on-add of a child an add attached; returns the child's
    /// construct error (see `ContainerSupport.autoConstructAttached`).
    private func autoConstructAttached(
        _ child: Child,
        record: LateChildStarts.Record?
    ) -> Error? {
        ContainerSupport.autoConstructAttached(
            child,
            in: self,
            record: record,
            autoConstructOnAdd: _autoConstructOnAdd,
            starts: lateStarts
        )
    }

    /// Test-only seam: runs at each `LateChildStage` of this container's
    /// late-child start records. Production code never sets it.
    var lateChildProbeForTesting: ((ComponentVMBase, LateChildStage) -> Void)? {
        get { lateStarts.probeForTesting }
        set { lateStarts.probeForTesting = newValue }
    }

    /// Test-only: the start records the current construct walk holds.
    var lateStartRecordCountForTesting: Int { lateStarts.recordCountForTesting }

    open override func _onConstruct() throws {
        try super._onConstruct()
        // Children whose construct population started are joined, not restarted.
        var joined: [ComponentVMBase] = []
        if !populated {
            if let factory = childrenFactory {
                populationJoined = []
                defer {
                    joined = populationJoined ?? []
                    populationJoined = nil
                }
                try attachPopulation(factory()).get()
            }
            populated = true
        }
        // A child's throwing `construct()` (ADR-0053) propagates up through this
        // hook to the composite's originating `construct()` call. Snapshot first
        // so the lifecycle iteration is stable; membership mutations attempted
        // from population hooks are rejected until the transaction completes.
        // A background child defers the composite's Constructed status (and the
        // selector) until every child has reached Constructed (spec/02 §6).
        // Begin this walk's start-record scope with the snapshot, so an add
        // attached after the snapshot registers its record in this walk.
        let (snapshot, scope) = membershipGate.withLock {
            (children, _autoConstructOnAdd ? lateStarts.beginWalkLocked() : nil)
        }
        try _transitionContainerChildren(
            snapshot,
            construct: true,
            joined: joined,
            lateChild: lateChildSource(after: snapshot, scope: scope)
        ) { [self] in
            if let selector = currentSelector,
               let initial = selector(snapshot),
               snapshot.contains(where: { $0 === initial }) {
                _assignInitialCurrent(initial)
            }
        }
    }

    private func attachPopulation(
        _ candidates: [Child]
    ) -> Result<Void, ContainerOwnershipError> {
        var identities = Set<ObjectIdentifier>()
        guard candidates.allSatisfy({
            identities.insert(ObjectIdentifier($0._ownershipIdentity)).inserted
        }) else {
            return .failure(.duplicate)
        }
        let transaction: ContainerOwnershipTransaction
        do {
            transaction = try beginMembershipTransaction()
        } catch let error as ContainerOwnershipError {
            return .failure(error)
        } catch {
            return .failure(.attachmentFailed(error))
        }
        defer { endMembershipTransaction() }
        let start = membershipGate.withLock { children.count }

        var transfers: [ParentTransfer] = []
        var originalStatuses: [ConstructionStatus] = []
        do {
            try withOwnershipReservationBatch(candidates) {
                for child in candidates {
                    let transfer = try beginParentTransfer(
                        child,
                        to: self,
                        transaction: transaction
                    )
                    transfers.append(transfer)
                    originalStatuses.append(child.status)
                }
            }
            try membershipGate.withLock {
                try requireTransactionCanContinueLocked()
                for child in candidates {
                    children.append(child)
                    child._parent = self
                    child._ownershipParent = self
                    // Staged: not a member for selection until admitted
                    // (spec/06 §4.3 rule 2).
                    pendingAdmissions.insert(ObjectIdentifier(child))
                }
            }
            // Make the entire snapshot visible before any child hook runs.
            for child in candidates {
                if _autoConstructOnAdd && isConstructed { try child.construct() }
                if status == .constructing && child.status != .constructed {
                    try child.construct()
                    // A child population left pending is joined, never restarted.
                    if child.status != .constructed && child.status != .disposed {
                        populationJoined?.append(child)
                    }
                }
            }
            try membershipGate.withLock { try requireTransactionCanContinueLocked() }
        } catch let attachmentError {
            var compensationError: Error?
            for (offset, child) in candidates.enumerated().reversed() {
                guard offset < originalStatuses.count else { continue }
                membershipGate.withLock {
                    pendingAdmissions.remove(ObjectIdentifier(child))
                    if let attached = children.firstIndex(where: { $0 === child }) {
                        children.remove(at: attached)
                    }
                }
                let originalStatus = originalStatuses[offset]
                if originalStatus == .destructed && child.status == .constructed {
                    do { try child.destruct() } catch {
                        if compensationError == nil { compensationError = error }
                    }
                }
                if child._ownershipParent === self {
                    child._parent = nil
                    child._ownershipParent = nil
                }
            }
            for transfer in transfers.reversed() { transfer.rollback() }
            if let compensationError {
                return .failure(.attachmentFailed(compensationError))
            }
            if let ownershipError = attachmentError as? ContainerOwnershipError {
                return .failure(ownershipError)
            }
            return .failure(.attachmentFailed(attachmentError))
        }

        for transfer in transfers { transfer.commit() }
        // Admitted after the old parents' detach commits, as in `addResult`
        // (COMP-006, spec/06 §4.3 rule 2).
        membershipGate.withLock {
            for child in candidates { pendingAdmissions.remove(ObjectIdentifier(child)) }
        }
        for child in candidates {
            if let index = membershipGate.withLock({
                children.firstIndex(where: { $0 === child })
            }), index >= start {
                emit(.added(child, at: index))
            }
        }
        return .success(())
    }

    open override func _onDestruct() throws {
        // The destruct clear (spec/06 §5, ADR-0173 rule 8): synchronous, with
        // no membership transaction and no wait, under the publication lease.
        // It is never refused or skipped, so COMP-005 holds also inside the
        // composite's own transaction, while another thread holds one and
        // while disposal is deferred.
        _clearCurrentForDestruct()
        // `destructOrder` orders the walk and its waits (ADR-0161).
        let snapshot = destructOrder.arrange(snapshot())
        try _transitionContainerChildren(snapshot, construct: false) {
            try super._onDestruct()
        }
    }

    /// Completes `collectionChanged` once the container is disposed, as the
    /// other flavors do, so derived views and sinks observe termination.
    open override func _onDispose() {
        membershipGate.withLock { disposeCompleted = true }
        super._onDispose()
        collectionChangedSubject.send(completion: .finished)
    }

    open override func dispose() {
        let caller = ThreadWaitGraph.currentThread
        while true {
            var waitForTransaction: DispatchGroup?
            var snapshot: [Child]?
            let shouldReturn: Bool = membershipGate.withLock {
                if disposeRequested { return true }
                // A thread that holds a current-publication lease defers
                // before any wait for a foreign transaction (spec/06 §4.3
                // rule 5): it would otherwise wait inside its own callback.
                if currentPublicationThreads.contains(caller) {
                    disposeDeferred = true
                    return true
                }
                if membershipTransactionActive {
                    if membershipTransactionOwner == caller {
                        disposeDeferred = true
                        return true
                    }
                    if let owner = membershipTransactionOwner,
                       let completion = membershipTransactionCompletion {
                        // The owner already waits on this thread (#703): record
                        // the terminal intent; `endMembershipTransaction` disposes.
                        guard registerMembershipWaitLocked(owner: owner) else {
                            disposeDeferred = true
                            return true
                        }
                        waitForTransaction = completion
                    }
                    return false
                }
                if activeCurrentPublications > 0 {
                    disposeDeferred = true
                    return true
                }
                // Admit the disposal. A deferral stays set until here, so no
                // transaction and no non-null selection slips in between.
                disposeRequested = true
                disposeDeferred = false
                snapshot = children
                return false
            }
            if shouldReturn { return }
            if let waitForTransaction {
                awaitMembershipTransaction(waitForTransaction)
                continue
            }
            guard let snapshot else { return }
            // LIFE-013 at the base's admitted-hook boundary (LIFE-015): the
            // children are disposed in `destructOrder`, and a foreign disposal
            // disposes none while this container's hook runs. No lock is held.
            _disposeWithChildren(destructOrder.arrange(snapshot))
            return
        }
    }

    // ── Builder entrypoint ──────────────────────────────────────────────

    public static func builder() -> CompositeVMBuilder<Child> {
        CompositeVMBuilder<Child>()
    }

    public static func create(_ options: CompositeVMOptions<Child>) throws -> CompositeVM<Child> {
        var b = CompositeVM<Child>.builder()
            .hint(options.hint)
            .autoConstructOnAdd(options.autoConstructOnAdd)
            .asyncSelection(options.asyncSelection)
            .destructOrder(options.destructOrder)
        if let name = options.name { b = b.name(name) }
        if let hub = options.hub { b = b._optionHub(hub) }
        if let dispatcher = options.dispatcher { b = b._optionDispatcher(dispatcher) }
        if let children = options.children { b = b.children(children) }
        if let current = options.current { b = b.current(current) }
        if let onCurrentChanged = options.onCurrentChanged { b = b.onCurrentChanged(onCurrentChanged) }
        if let onConstruct = options.onConstruct { b = b.onConstruct(onConstruct) }
        if let onDestruct = options.onDestruct { b = b.onDestruct(onDestruct) }
        return try b.build()
    }

    // ── Internal ────────────────────────────────────────────────────────

    private func beginMembershipTransactionLocked(
        _ transaction: ContainerOwnershipTransaction,
        allowJoin: Bool
    ) throws {
        guard !disposeRequested && !disposeDeferred else {
            throw ContainerOwnershipError.attachmentFailed(ContainerDisposalAdmissionError())
        }
        if membershipTransactionActive {
            guard allowJoin, membershipTransactionToken === transaction else {
                throw ContainerOwnershipError.attachmentFailed(ContainerMembershipTransactionError())
            }
            membershipTransactionDepth += 1
            return
        }
        membershipTransactionActive = true
        membershipTransactionToken = transaction
        membershipTransactionDepth = 1
        membershipTransactionOwner = ThreadWaitGraph.currentThread
        let completion = DispatchGroup()
        completion.enter()
        membershipTransactionCompletion = completion
    }

    private func beginMembershipTransaction() throws -> ContainerOwnershipTransaction {
        let transaction = ContainerOwnershipTransaction()
        try enterMembershipTransaction(transaction, allowJoin: false)
        return transaction
    }

    private func joinMembershipTransaction(
        _ transaction: ContainerOwnershipTransaction
    ) throws {
        try enterMembershipTransaction(transaction, allowJoin: true)
    }

    /// Opens or joins a membership transaction. While another thread's
    /// transaction is open, waits for it to end instead of failing. A C# group
    /// also waits. A C# composite, Python and Rust reject the second
    /// transaction (#756). A second transaction on the same thread is still
    /// rejected (ADR-0118), and so is a wait that would close a cycle (#551).
    private func enterMembershipTransaction(
        _ transaction: ContainerOwnershipTransaction,
        allowJoin: Bool
    ) throws {
        try ContainerSupport.enterMembershipTransaction {
            try tryEnterMembershipTransaction(transaction, allowJoin: allowJoin)
        }
    }

    /// Opens or joins the transaction, or records a wait for another thread's
    /// open transaction and returns its completion. Throws on a same-thread
    /// conflict (ADR-0118) and on a wait that would close a cycle in the
    /// shared wait graph (#551, #703).
    private func tryEnterMembershipTransaction(
        _ transaction: ContainerOwnershipTransaction,
        allowJoin: Bool
    ) throws -> DispatchGroup? {
        let caller = ThreadWaitGraph.currentThread
        return try membershipGate.withLock { () -> DispatchGroup? in
            if membershipTransactionActive,
               !(allowJoin && membershipTransactionToken === transaction),
               let owner = membershipTransactionOwner, owner != caller,
               let completion = membershipTransactionCompletion {
                guard registerMembershipWaitLocked(owner: owner) else {
                    throw ContainerOwnershipError.attachmentFailed(ContainerMembershipTransactionError())
                }
                return completion
            }
            try beginMembershipTransactionLocked(transaction, allowJoin: allowJoin)
            return nil
        }
    }

    private func requireTransactionCanContinueLocked() throws {
        guard !disposeRequested && !disposeDeferred else {
            throw ContainerOwnershipError.attachmentFailed(ContainerDisposalAdmissionError())
        }
    }

    /// Records, under `membershipGate`, a wait for another thread's open
    /// transaction. Returns `false` when the wait would close a cycle.
    private func registerMembershipWaitLocked(owner: UInt64) -> Bool {
        guard beginMembershipWait(owner: owner, container: self) else { return false }
        membershipWaits += 1
        return true
    }

    private func endMembershipTransaction() {
        var completion: DispatchGroup?
        var shouldDispose = false
        membershipGate.withLock {
            precondition(membershipTransactionDepth > 0)
            membershipTransactionDepth -= 1
            if membershipTransactionDepth == 0 {
                membershipTransactionActive = false
                membershipTransactionToken = nil
                membershipTransactionOwner = nil
                completion = membershipTransactionCompletion
                membershipTransactionCompletion = nil
                if membershipWaits > 0 {
                    membershipWaits = 0
                    releaseMembershipWaiters(of: self)
                }
                // `dispose()` clears the deferral when it admits the disposal.
                shouldDispose = disposeDeferred && activeCurrentPublications == 0
            }
        }
        completion?.leave()
        if shouldDispose { dispose() }
    }

    /// The construct walk's assignment of the selector's pick (spec/06 §3.2,
    /// COMP-025, ADR-0165, ADR-0173). Hooks run during the walk, and a
    /// deferred walk resumes on the settling thread, so the pick is checked
    /// against committed membership: a pick that has left or is not admitted
    /// yet is a silent no-op (#705), and so is the assignment while disposal
    /// is pending or inside the caller's own uncommitted membership
    /// transaction. It opens no transaction, never waits for another
    /// thread's transaction, and is synchronous also with `asyncSelection`
    /// (#1150).
    private func _assignInitialCurrent(_ initial: Child) {
        _ = _applySelection(initial, selectionCall: true)
    }

    /// The destruct clear (spec/06 §5, ADR-0173 rule 8). It is not a
    /// selection call: no refusal applies, and it never waits or is skipped
    /// (#1201).
    private func _clearCurrentForDestruct() {
        // Nothing to clear: skip the shared coordination lane, as before.
        guard membershipGate.withLock({ _current != nil }) else { return }
        _ = _applySelection(nil, selectionCall: false)
    }

    /// The clear that a detach commits: only while `detached` is still
    /// current, so a selection made after the detach stays (spec/06 §4.3
    /// rule 6).
    private func _clearDetachedCurrent(_ detached: Child) {
        guard membershipGate.withLock({ _current === detached }) else { return }
        _ = _applySelection(nil, selectionCall: false, expectedCurrent: detached)
    }

    private func _setCurrent(_ value: Child?) {
        // A refusal is a programmer error reachable only via the (non-throwing)
        // `current` property setter; `setCurrent(_:)` throws a catchable
        // `CompositeMembershipError` for the same refusals (VMX-026 /
        // ADR-0053). The trap remains for the property setter, which Swift
        // cannot make `throws` (ADR-0009).
        if let refusal = _requestSelection(value) {
            preconditionFailure(
                "Cannot set current to '\(value?.name ?? "<nil>")': "
                + CompositeMembershipError.explanation(for: refusal)
                + " Use setCurrent(_:)/canSetCurrent(_:) for a catchable check."
            )
        }
    }

    /// A selection call (spec/06 §4.3): the setter, `selectComponent`,
    /// `deselectComponent` and the child `select`/`deselect` paths. A
    /// non-`nil` `expectedCurrent` makes it a deselection of that child.
    /// Returns the refusal; the caller reports it through its own channel.
    ///
    /// With `asyncSelection` the call validates now (rules 2-4), then
    /// schedules the change on the foreground dispatcher and returns; the
    /// delivery validates again and a delivery that is no longer valid is a
    /// silent no-op (COMP-010, spec/06 §4.3 rule 7).
    private func _requestSelection(
        _ value: Child?,
        requireConstructed: Bool = false,
        expectedCurrent: Child? = nil
    ) -> CompositeSelectionRefusal? {
        guard _asyncSelection else {
            if case let .refused(refusal) = _applySelection(
                value,
                selectionCall: true,
                requireConstructed: requireConstructed,
                expectedCurrent: expectedCurrent
            ) {
                return refusal
            }
            return nil
        }
        switch _commitSelection(
            value,
            selectionCall: true,
            requireConstructed: requireConstructed,
            expectedCurrent: expectedCurrent,
            validateOnly: true
        ) {
        case let .refused(refusal): return refusal
        case .inert, .ignored: return nil
        case .committed, .unchanged: break
        }
        dispatcher.scheduleForeground { [weak self] in
            _ = self?._applySelection(
                value,
                selectionCall: true,
                requireConstructed: requireConstructed,
                expectedCurrent: expectedCurrent
            )
        }
        return nil
    }

    /// Commits a selection path (`_commitSelection`) and, when it changed
    /// `Current`, publishes it under the current-publication lease.
    @discardableResult
    private func _applySelection(
        _ value: Child?,
        selectionCall: Bool,
        requireConstructed: Bool = false,
        expectedCurrent: Child? = nil
    ) -> CompositeSelectionOutcome<Child> {
        let outcome = _commitSelection(
            value,
            selectionCall: selectionCall,
            requireConstructed: requireConstructed,
            expectedCurrent: expectedCurrent
        )
        _publishSelection(outcome, to: value)
        return outcome
    }

    /// Validates and commits `Current` and both current flags under the
    /// shared coordination lane, then `membershipGate` (spec/06 §4.3 rule 1).
    /// It opens, joins and waits for no membership transaction, and waits only
    /// for those two locks, which no consumer code holds. A commit takes a
    /// current-publication lease that `_finishCurrentChange` ends.
    private func _commitSelection(
        _ value: Child?,
        selectionCall: Bool,
        requireConstructed: Bool = false,
        expectedCurrent: Child? = nil,
        validateOnly: Bool = false
    ) -> CompositeSelectionOutcome<Child> {
        let caller = ThreadWaitGraph.currentThread
        // Read before the lane: the base lifecycle lock is never taken under
        // this composite's gate.
        let disposed = _isDisposalRequested()
        compositeCurrentChangeCoordinator.lock()
        defer { compositeCurrentChangeCoordinator.unlock() }
        return membershipGate.withLock {
            _commitSelectionLocked(
                value,
                selectionCall: selectionCall,
                requireConstructed: requireConstructed,
                expectedCurrent: expectedCurrent,
                validateOnly: validateOnly,
                caller: caller,
                disposed: disposed
            )
        }
    }

    /// The body of `_commitSelection`. Call with the coordination lane and
    /// `membershipGate` held.
    ///
    /// `selectionCall` applies rule 4 (the caller's own uncommitted
    /// transaction); the destruct and detach clears pass `false`. Rule 2
    /// (admitted members) and rule 3 (no non-`nil` selection while disposal
    /// is pending) apply to every path; a `nil` value is never refused by
    /// them. `requireConstructed` (`selectComponent` and the child `select`
    /// path) refuses a child that is not Constructed at the commit, so a
    /// concurrent destruct cannot pass a check made before the locks (spec/06
    /// §3.1, #1220). `expectedCurrent` makes the change apply only while that
    /// child is current. Once the composite has published Disposed (`disposed`, read
    /// from the base lifecycle state), a selection call is inert (chapter 01
    /// §4). The destruct and detach clears still commit `nil`: they are never
    /// skipped (spec/06 §5, ADR-0173 rule 8), as in C# and Python, and the
    /// disposed composite's own notifications are no-ops.
    ///
    /// A Disposed child is not a member for selection (rule 2, ADR-0189).
    /// While the composite is Destructing, a non-`nil` value that the other
    /// rules admit is `.ignored` (rule 8, ADR-0188). The composite's status
    /// is read under the gate, as `registerLateStartLocked` and the
    /// construct seal do. The status is Destructing before the destruct
    /// clear runs, so no selection commits after that clear.
    private func _commitSelectionLocked(
        _ value: Child?,
        selectionCall: Bool,
        requireConstructed: Bool = false,
        expectedCurrent: Child?,
        validateOnly: Bool,
        caller: UInt64,
        disposed: Bool
    ) -> CompositeSelectionOutcome<Child> {
        if selectionCall && ownsUncommittedTransactionLocked(caller) {
            return .refused(.transactionInProgress)
        }
        if let value, !isAdmittedMemberLocked(value) { return .refused(.nonMember) }
        // The child's lifecycle lock nests under the gate, as in
        // `_commitIsCurrent`.
        if requireConstructed, let value, value.status != .constructed {
            return .refused(.notConstructed)
        }
        if let expectedCurrent, _current !== expectedCurrent { return .refused(.notCurrent) }
        if selectionCall && (disposed || disposeCompleted) { return .inert }
        // The child's lifecycle lock nests under the gate, as above.
        if let value, value.status == .disposed { return .refused(.nonMember) }
        if value != nil && (disposeRequested || disposeDeferred) {
            return .refused(.disposing)
        }
        if value != nil && status == .destructing { return .ignored }
        if validateOnly || _current === value { return .unchanged }
        let previous = _current
        _current = value
        let previousChanged = previous?._commitIsCurrent(false) ?? false
        let valueChanged = value?._commitIsCurrent(true) ?? false
        activeCurrentPublications += 1
        currentPublicationThreads.append(caller)
        return .committed(previous, previousChanged, valueChanged)
    }

    /// Detaches children in `detach` under the coordination lane and
    /// `membershipGate` and, when `detach` returns the child that is current,
    /// commits the detach clear in the same section. No other composite can
    /// adopt and select that child between the detach and the clear, so the
    /// clear never resets the flag of a child that is current elsewhere
    /// (COMP-006, spec/06 §4.3 rule 6). The caller publishes the returned
    /// outcome with `_publishSelection` after the section.
    private func _detachClearingCurrent<T>(
        _ detach: () -> (T, Child?)?
    ) -> (T, CompositeSelectionOutcome<Child>)? {
        let caller = ThreadWaitGraph.currentThread
        let disposed = _isDisposalRequested()
        compositeCurrentChangeCoordinator.lock()
        defer { compositeCurrentChangeCoordinator.unlock() }
        return membershipGate.withLock {
            guard let (result, detachedCurrent) = detach() else { return nil }
            guard let detachedCurrent, _current === detachedCurrent else {
                return (result, .unchanged)
            }
            return (result, _commitSelectionLocked(
                nil,
                selectionCall: false,
                expectedCurrent: detachedCurrent,
                validateOnly: false,
                caller: caller,
                disposed: disposed
            ))
        }
    }

    /// Publishes a committed `outcome` (`value` is the new `Current`).
    private func _publishSelection(_ outcome: CompositeSelectionOutcome<Child>, to value: Child?) {
        if case let .committed(previous, previousFlagChanged, valueFlagChanged) = outcome {
            _finishCurrentChange(
                from: previous,
                to: value,
                previousFlagChanged: previousFlagChanged,
                valueFlagChanged: valueFlagChanged
            )
        }
    }

    /// A member that its add, insert, replacement or population has admitted
    /// (spec/06 §4.3 rule 2). Call under `membershipGate`.
    private func isAdmittedMemberLocked(_ value: Child) -> Bool {
        children.contains(where: { $0 === value })
            && !pendingAdmissions.contains(ObjectIdentifier(value))
    }

    /// True while `caller` owns this composite's membership transaction and
    /// its rollback could still undo a staged change: a child attached but not
    /// admitted, a staged population, or a child detached for a transfer
    /// whose commit has not run (spec/06 §4.3 rule 4). Call under
    /// `membershipGate`.
    private func ownsUncommittedTransactionLocked(_ caller: UInt64) -> Bool {
        membershipTransactionActive
            && membershipTransactionOwner == caller
            && (!pendingAdmissions.isEmpty || pendingTransferDetaches > 0)
    }

    private func _finishCurrentChange(
        from previous: Child?,
        to value: Child?,
        previousFlagChanged: Bool,
        valueFlagChanged: Bool
    ) {
        defer { _endCurrentPublication() }

        // COMP-006: the flag is committed atomically with the current slot, but
        // its admitted notification remains foreground-dispatched.
        if let prev = previous, previousFlagChanged {
            dispatcher.scheduleForeground { [weak prev] in
                guard let prev else { return }
                prev._publishIsCurrent()
            }
        }
        if valueFlagChanged { value?._publishIsCurrent() }

        _notifyPropertyChanged("current")
        onCurrentChanged?(value)
    }

    /// Ends a current-publication lease. A deferred disposal starts when the
    /// last lease ends and no membership transaction is open (spec/06 §4.3
    /// rule 5); `dispose()` clears the deferral when it admits it.
    private func _endCurrentPublication() {
        let caller = ThreadWaitGraph.currentThread
        var shouldDispose = false
        membershipGate.withLock {
            precondition(activeCurrentPublications > 0)
            activeCurrentPublications -= 1
            if let lease = currentPublicationThreads.lastIndex(of: caller) {
                currentPublicationThreads.remove(at: lease)
            }
            shouldDispose = activeCurrentPublications == 0
                && !membershipTransactionActive
                && disposeDeferred
        }
        if shouldDispose { dispose() }
    }
}

/// Why `CompositeVM` refused a selection (spec/06 §3, §4.3, ADR-0173).
enum CompositeSelectionRefusal {
    /// Not an admitted member (rule 2).
    case nonMember
    /// `selectComponent` or the child `select` path on a child that is not
    /// Constructed (spec/06 §3.1).
    case notConstructed
    /// A deselection of a child that is not current (spec/06 §3.1).
    case notCurrent
    /// A non-`nil` selection while disposal is pending (rule 3).
    case disposing
    /// Inside the caller's own uncommitted membership transaction (rule 4).
    case transactionInProgress
}

/// The result of one validation or commit of a selection path.
enum CompositeSelectionOutcome<Child> {
    /// `Current` changed; the payload is the previous child and whether each
    /// current flag changed. The caller publishes under the lease it holds.
    case committed(Child?, Bool, Bool)
    /// Valid, and nothing to change (or validation only).
    case unchanged
    /// The composite is disposed: the call has no effect (chapter 01 §4).
    case inert
    /// A non-`nil` selection while the composite is Destructing: the call
    /// changes nothing and raises nothing (spec/06 §4.3 rule 8, ADR-0188).
    case ignored
    case refused(CompositeSelectionRefusal)
}

/// Thrown by `CompositeVM.setCurrent(_:)` when the argument is not a member of
/// the composite's children (spec/06 §3.1 — `Current` must be a member; cf.
/// `COMP-009`). This is the Swift convergence (ADR-0053, VMX-026) of the
/// non-child `Current` assignment that C# surfaces as `InvalidOperationException`
/// and Python/TypeScript as a thrown error. The non-throwing `current` property
/// setter traps instead, because Swift setters cannot be `throws`.
///
/// It is also the catchable channel for the other selection refusals of
/// spec/06 §4.3 (ADR-0173): a child while disposal of the composite is
/// pending, and any selection call inside the caller's own uncommitted
/// membership transaction. `description` names the reason.
public struct CompositeMembershipError: Error, CustomStringConvertible {
    public let memberName: String
    public let compositeName: String
    let reason: CompositeSelectionRefusal

    public init(memberName: String, compositeName: String) {
        self.init(memberName: memberName, compositeName: compositeName, reason: .nonMember)
    }

    init(memberName: String, compositeName: String, reason: CompositeSelectionRefusal) {
        self.memberName = memberName
        self.compositeName = compositeName
        self.reason = reason
    }

    public var description: String {
        "Cannot set current to '\(memberName)' in composite '\(compositeName)': "
        + Self.explanation(for: reason)
    }

    static func explanation(for reason: CompositeSelectionRefusal) -> String {
        switch reason {
        case .nonMember: return "not an admitted child of the composite."
        case .notConstructed: return "the child is not Constructed."
        case .notCurrent: return "not the current child of the composite."
        case .disposing: return "disposal of the composite is in progress."
        case .transactionInProgress:
            return "a membership transaction is in progress on this thread."
        }
    }
}
