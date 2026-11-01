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

func replaceAggregateSlots(
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
    for child in previous where child?._ownershipParent === parent {
        child?._parent = nil
        child?._ownershipParent = nil
    }
    for child in next {
        child._parent = parent
        child._ownershipParent = parent
    }
}
