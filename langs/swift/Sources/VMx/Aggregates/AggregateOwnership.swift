// Fixed-slot ownership support shared by AggregateVM1...AggregateVM6.

final class AggregateParent: ParentVM, OwnershipParentVM {
    unowned let owner: ComponentVMBase
    private let slots: () -> [ComponentVMBase]

    init(owner: ComponentVMBase, slots: @escaping () -> [ComponentVMBase]) {
        self.owner = owner
        self.slots = slots
    }

    var supportsChildSelection: Bool { false }
    var currentChild: ComponentVMBase? { nil }
    func selectChild(_ vm: ComponentVMBase) {}
    func deselectChild(_ vm: ComponentVMBase) {}

    var ownershipOwner: ComponentVMBase { owner }
    var ownershipOwnerParent: OwnershipParentVM? { owner._ownershipParent }
    func containsIdentity(_ vm: ComponentVMBase) -> Bool {
        let identity = vm._ownershipIdentity
        return slots().contains { $0._ownershipIdentity === identity }
    }

    func detachForTransfer(_ vm: ComponentVMBase) throws -> ParentTransfer {
        throw ContainerOwnershipError.inconsistentParent
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
        if let current = child._transferOwnershipParent,
           !(current === parent && parent.containsIdentity(child)) {
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
