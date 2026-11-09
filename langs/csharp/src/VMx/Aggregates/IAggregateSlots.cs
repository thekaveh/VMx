using VMx.Components;
using VMx.Internal;

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

internal sealed class AggregateParent(ComponentVMBase owner, IAggregateSlots slots)
    : IParentCompositeVM
{
    public IComponentVM Owner => owner;

    /// <summary>
    /// Assigns the aggregate's new slots in one step with the owner's terminal
    /// check; see <see cref="ComponentVMBase.CommitUnlessDisposing"/>.
    /// </summary>
    internal bool CommitUnlessDisposing(Action assign) => owner.CommitUnlessDisposing(assign);

    public IParentCompositeVM? OwnerParent => owner.GetParent();
    public bool SupportsChildSelection => false;
    public IComponentVM? CurrentChild => null;
    public void SelectChild(IComponentVM vm) { }
    public void DeselectChild(IComponentVM vm) { }
    public void ChildDisposed(IComponentVM vm) { }
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
    /// <summary>
    /// Runs one slot factory. When it throws, the candidates that earlier
    /// factories of the same population built are disposed, then the failure
    /// propagates (#1324).
    /// </summary>
    internal static T Build<T>(AggregateParent parent, List<IComponentVM> built, Func<T> factory)
        where T : class, IComponentVM
    {
        T next;
        try { next = factory(); }
        catch
        {
            UnownedCandidates.Dispose(parent, built);
            throw;
        }
        built.Add(next);
        return next;
    }

    internal static bool Replace(
        AggregateParent parent,
        IComponentVM?[] previous,
        IComponentVM[] next,
        Action assign,
        Action notifyCommittedError)
    {
        IDisposable reservation;
        try
        {
            reservation = ComponentOwnership.BeginExclusiveReservationBatch(next);
            try { Validate(parent, next); }
            catch
            {
                reservation.Dispose();
                throw;
            }
        }
        catch
        {
            // The preflight refused the population: the old slots stay, and
            // the candidates nobody else owns are disposed (#1324).
            UnownedCandidates.Dispose(parent, next);
            throw;
        }
        using var _ = reservation;
        System.Runtime.ExceptionServices.ExceptionDispatchInfo? firstError = null;
        foreach (var child in previous)
        {
            if (child is not null) FirstFailure.Capture(ref firstError, child.Dispose);
        }
        // The terminal check and the assignment are one step under the owner's
        // lifecycle gate: a concurrent disposal either sees the committed slots
        // in its cascade snapshot, or makes this commit fail (spec/08 §4).
        if (!parent.CommitUnlessDisposing(assign))
        {
            foreach (var child in next) FirstFailure.Capture(ref firstError, child.Dispose);
            firstError?.Throw();
            return false;
        }
        Commit(parent, previous, next);
        if (firstError is not null)
        {
            notifyCommittedError();
            firstError.Throw();
        }
        return true;
    }

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
            if (existingParent is not null)
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
