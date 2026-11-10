// Fixed-slot ownership support shared by AggregateVM1...AggregateVM6.

import Foundation

final class AggregateParent: ParentVM, OwnershipParentVM {
    unowned let owner: ComponentVMBase
    private let slots: () -> [ComponentVMBase]
    private let transactionLock = NSRecursiveLock()

    init(owner: ComponentVMBase, slots: @escaping () -> [ComponentVMBase]) {
        self.owner = owner
        self.slots = slots
    }

    var supportsChildSelection: Bool { false }
    var currentChild: ComponentVMBase? { nil }
    func selectChild(_ vm: ComponentVMBase) {}
    func deselectChild(_ vm: ComponentVMBase) {}

    var ownershipOwner: ComponentVMBase { owner }
    var ownershipOwnerParent: OwnershipParentVM? { owner._transferOwnershipParent }
    func containsIdentity(_ vm: ComponentVMBase) -> Bool {
        let identity = vm._ownershipIdentity
        return slots().contains { $0._ownershipIdentity === identity }
    }

    func detachForTransfer(_ vm: ComponentVMBase) throws -> ParentTransfer {
        throw ContainerOwnershipError.inconsistentParent
    }

    func withTransaction<T>(_ action: () throws -> T) rethrows -> T {
        transactionLock.lock()
        defer { transactionLock.unlock() }
        return try action()
    }

    /// The current slots, in slot order. Waits for an active slot
    /// replacement first (spec/08 §4).
    func slotSnapshot() -> [ComponentVMBase] {
        withTransaction { slots() }
    }
}

func validateAggregateSlots(
    parent: AggregateParent,
    children: [ComponentVMBase]
) throws {
    var seen = Set<ObjectIdentifier>()
    for child in children {
        let identity = child._ownershipIdentity
        guard seen.insert(ObjectIdentifier(identity)).inserted else {
            throw ContainerOwnershipError.duplicate
        }
        if child._transferOwnershipParent != nil {
            throw ContainerOwnershipError.inconsistentParent
        }
        var cursor: OwnershipParentVM? = parent
        while let current = cursor {
            guard current.ownershipOwner._ownershipIdentity !== identity else {
                throw ContainerOwnershipError.cycle
            }
            cursor = current.ownershipOwnerParent
        }
    }
}

/// Disposes the candidates of a population that its preflight refused before
/// the commit (#1324). A candidate that has a parent, that another ownership
/// transaction holds, or that is an owner on the ancestor chain of `parent`,
/// belongs to someone else and is skipped. Each canonical identity is
/// disposed once.
///
/// The cleanup is best-effort. The parent check takes no lock, so another
/// thread that starts to attach a candidate after the checks can still lose
/// it to this cleanup. The in-progress check never waits: a candidate whose
/// gate another thread holds at that moment is skipped and stays undisposed.
/// A factory's fresh output is normally reachable only by the refused
/// population, so both windows are narrow.
func disposeUnownedCandidates(parent: OwnershipParentVM, _ candidates: [ComponentVMBase]) {
    var seen = Set<ObjectIdentifier>()
    for candidate in candidates {
        let identity = candidate._ownershipIdentity
        guard seen.insert(ObjectIdentifier(identity)).inserted else { continue }
        if candidate._transferOwnershipParent != nil { continue }
        if isOwnershipTransactionInProgress(candidate) { continue }
        var ownsOnChain = false
        var cursor: OwnershipParentVM? = parent
        while let current = cursor {
            if current.ownershipOwner._ownershipIdentity === identity {
                ownsOnChain = true
                break
            }
            cursor = current.ownershipOwnerParent
        }
        if !ownsOnChain { candidate.dispose() }
    }
}

func replaceAggregateSlots(
    parent: AggregateParent,
    previous: [ComponentVMBase?],
    next: [ComponentVMBase],
    assign: () -> Void
) throws -> Bool {
    do {
        return try replaceValidatedAggregateSlots(
            parent: parent, previous: previous, next: next, assign: assign)
    } catch {
        // Only the reservation and the preflight throw: the old slots stay,
        // and the candidates nobody else owns are disposed (#1324).
        disposeUnownedCandidates(parent: parent, next)
        throw error
    }
}

private func replaceValidatedAggregateSlots(
    parent: AggregateParent,
    previous: [ComponentVMBase?],
    next: [ComponentVMBase],
    assign: () -> Void
) throws -> Bool {
    try withExclusiveOwnershipReservationBatch(next) {
        try validateAggregateSlots(parent: parent, children: next)
        guard !parent.owner._isDisposalRequested() else {
            // The dispose cascade owns the current slots (LIFE-015).
            for child in next { child.dispose() }
            return false
        }
        for child in previous { child?.dispose() }
        // A foreign dispose requests disposal under the owner's lifecycle
        // lock, so the final check and `assign` run as one step (spec/08 §4).
        guard parent.owner._commitUnlessDisposalRequested(assign) else {
            for child in next { child.dispose() }
            return false
        }
        commitAggregateSlots(parent: parent, previous: previous, next: next)
        return true
    }
}

func commitAggregateSlots(
    parent: AggregateParent,
    previous: [ComponentVMBase?],
    next: [ComponentVMBase]
) {
    for child in previous {
        child?._unlinkParent(ifOwnedBy: parent)
    }
    for child in next {
        child._linkParent(parent)
    }
}
