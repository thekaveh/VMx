using VMx.Components;
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
    /// <remarks>
    /// Reads <see cref="IComponentVM.Name"/> when the source implements
    /// <see cref="IComponentVM"/> (the canonical case), matching Python
    /// (`hierarchical_vm.py`) and TypeScript (`hierarchicalVm.ts`) which both
    /// emit the VM's configured name. Falls back to the runtime type name
    /// for the rare case where a non-VM source is supplied.
    /// </remarks>
    public string SenderName => (Source as IComponentVM)?.Name ?? Source.GetType().Name;

    /// <summary>The source cast to <see cref="object"/> (satisfies <see cref="IMessage"/> protocol).</summary>
    public object SenderObject => Source;
}
