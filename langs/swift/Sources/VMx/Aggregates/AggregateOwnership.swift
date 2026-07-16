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
        slots().contains { $0 === vm }
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
        guard seen.insert(ObjectIdentifier(child)).inserted else {
            throw ContainerOwnershipError.duplicate
        }
        if let current = child._ownershipParent,
           !(current === parent && parent.containsIdentity(child)) {
            throw ContainerOwnershipError.inconsistentParent
        }
        var cursor: OwnershipParentVM? = parent
        while let current = cursor {
            guard current.ownershipOwner !== child else {
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
