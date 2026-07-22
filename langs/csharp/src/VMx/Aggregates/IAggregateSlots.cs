using VMx.Components;

namespace VMx.Aggregates;

/// <summary>
/// Internal helper interface used by <see cref="Tree.Tree"/> to enumerate the
/// non-null component slots of an aggregate VM without reflection. All six
/// concrete <c>AggregateVMN</c> classes implement this explicitly; consumers
/// should depend on the public <c>IAggregateVM1..IAggregateVM6</c> interfaces
/// instead.
/// </summary>
internal interface IAggregateSlots
{
    /// <summary>Yields non-null component slots in declaration order.</summary>
    IEnumerable<IComponentVM> EnumerateSlots();

}

internal sealed class AggregateParent(IComponentVM owner, IAggregateSlots slots)
    : IParentCompositeVM
{
    public IComponentVM Owner => owner;
    public IParentCompositeVM? OwnerParent => owner.GetParent();
    public bool SupportsChildSelection => false;
    public IComponentVM? CurrentChild => null;
    public void SelectChild(IComponentVM vm) { }
    public void DeselectChild(IComponentVM vm) { }
    public bool ContainsChild(IComponentVM vm)
    {
        var identity = vm.GetOwnershipIdentity();
        return slots.EnumerateSlots().Any(child =>
            ReferenceEquals(child.GetOwnershipIdentity(), identity));
    }
    public ParentTransferToken DetachForTransfer(IComponentVM vm)
        => throw new InvalidOperationException(
            $"Cannot transfer '{vm.Name}' out of a fixed aggregate slot.");
}

internal static class AggregateOwnership
{
    internal static void Validate(IParentCompositeVM parent, params IComponentVM[] children)
    {
        for (var index = 0; index < children.Length; index++)
        {
            var child = children[index];
            var identity = child.GetOwnershipIdentity();
            if (children.Take(index).Any(candidate =>
                    ReferenceEquals(candidate.GetOwnershipIdentity(), identity)))
                throw new InvalidOperationException(
                    "Aggregate factories returned the same canonical component identity more than once.");
            var existingParent = child.GetParent();
            if (existingParent is not null &&
                !(ReferenceEquals(existingParent, parent) && parent.ContainsChild(child)))
                throw new InvalidOperationException(
                    $"Cannot populate aggregate slot with '{child.Name}': it already has a parent.");

            for (IParentCompositeVM? cursor = parent; cursor is not null; cursor = cursor.OwnerParent)
                if (cursor.Owner is not null &&
                    ReferenceEquals(cursor.Owner.GetOwnershipIdentity(), identity))
                    throw new InvalidOperationException(
                        $"Cannot populate aggregate slot with '{child.Name}': parent cycle.");
        }
    }

    internal static void Commit(
        IParentCompositeVM parent,
        IEnumerable<IComponentVM?> previous,
        IEnumerable<IComponentVM> next)
    {
        foreach (var child in previous.OfType<IComponentVM>())
            if (ReferenceEquals(child.GetParent(), parent)) child.SetParent(null);
        foreach (var child in next) child.SetParent(parent);
    }
}
