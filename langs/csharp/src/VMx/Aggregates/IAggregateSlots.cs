using VMx.Components;

namespace VMx.Aggregates;

/// <summary>
/// Internal helper interface used by <see cref="Tree.Tree"/> to enumerate the
/// non-null component slots of an aggregate VM without reflection. All five
/// concrete <c>AggregateVMN</c> classes implement this explicitly; consumers
/// should depend on the public <c>IAggregateVM1..IAggregateVM5</c> interfaces
/// instead.
/// </summary>
internal interface IAggregateSlots
{
    /// <summary>Yields non-null component slots in declaration order.</summary>
    IEnumerable<IComponentVM> EnumerateSlots();
}
