namespace VMx.Components;

/// <summary>
/// The order in which a <c>GroupVM</c> or <c>CompositeVM</c> destructs and
/// disposes its children (spec/02 §6, spec/06 §5, spec/07 §2, ADR-0161).
/// Construct order is not affected: children always construct in child order.
/// </summary>
public enum ChildOrder
{
    /// <summary>
    /// The default: destruct and dispose walk the children in child order
    /// (index 0 first), the order construct uses.
    /// </summary>
    Insertion = 0,

    /// <summary>
    /// Destruct and dispose walk the children in reverse child order (last
    /// index first), so a later child that depends on an earlier one is torn
    /// down first. Disposal stays depth-first (LIFE-013).
    /// </summary>
    Reverse = 1,
}

/// <summary>Applies a <see cref="ChildOrder"/> to a child snapshot.</summary>
internal static class ChildOrderExtensions
{
    /// <summary>
    /// Returns <paramref name="snapshot"/> in <paramref name="order"/>:
    /// unchanged for <see cref="ChildOrder.Insertion"/>, reversed in place for
    /// <see cref="ChildOrder.Reverse"/>. The caller owns the array.
    /// </summary>
    internal static T[] InDestructOrder<T>(this T[] snapshot, ChildOrder order)
    {
        if (order == ChildOrder.Reverse) Array.Reverse(snapshot);
        return snapshot;
    }
}
