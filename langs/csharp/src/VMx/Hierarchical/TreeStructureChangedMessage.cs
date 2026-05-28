using VMx.Messages;

namespace VMx.Hierarchical;

/// <summary>
/// Discriminated enum for the structural mutation that occurred in a
/// <see cref="HierarchicalVM{TModel,TVM}"/> subtree.
/// </summary>
public enum TreeStructureChange
{
    /// <summary>A child node was added to the subtree.</summary>
    Added,

    /// <summary>A child node was removed from the subtree.</summary>
    Removed,

    /// <summary>A node was moved to a different parent within the tree.</summary>
    Reparented,
}

/// <summary>
/// Message published on <c>IMessageHub</c> when a <see cref="HierarchicalVM{TModel,TVM}"/>
/// subtree changes structurally (add / remove / reparent of a child).
///
/// See spec/18-hierarchical-vm.md §6 and ADR-0028 §3.4.
/// </summary>
/// <param name="Source">The node whose <c>Children</c> collection changed.</param>
/// <param name="Change">The kind of structural mutation.</param>
/// <param name="Affected">The node that was added, removed, or reparented.</param>
/// <param name="Index">Position in <c>Children</c> at which the change occurred; -1 when not applicable (e.g. Reparented).</param>
public sealed record TreeStructureChangedMessage(
    object Source,
    TreeStructureChange Change,
    object Affected,
    int Index) : IMessage
{
    /// <inheritdoc/>
    public string SenderName => Source.GetType().Name;

    /// <summary>The source cast to <see cref="object"/> (satisfies <see cref="IMessage"/> protocol).</summary>
    public object SenderObject => Source;
}
