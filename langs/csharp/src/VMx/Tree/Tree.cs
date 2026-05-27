using VMx.Capabilities;
using VMx.Components;

namespace VMx.Tree;

/// <summary>
/// Static helpers for traversing a VMx tree rooted at any <see cref="IComponentVM"/>.
/// See spec/13-tree-utilities.md.
/// </summary>
public static class Tree
{
    /// <summary>
    /// Yields <paramref name="root"/> then every descendant in depth-first pre-order.
    /// For composite and group containers, walks children via their <see cref="IEnumerable{T}"/>
    /// implementation. For aggregate VMs, walks non-null Component1..Component5 slots in order.
    /// Leaf nodes yield exactly themselves.
    /// </summary>
    /// <param name="root">The root of the sub-tree to walk.</param>
    /// <returns>A lazy sequence of nodes in DFS pre-order.</returns>
    public static IEnumerable<IComponentVM> Walk(IComponentVM root)
    {
        yield return root;

        if (root is IEnumerable<IComponentVM> children)
        {
            foreach (var child in children)
                foreach (var node in Walk(child))
                    yield return node;
        }
        else
        {
            foreach (var slot in AggregateSlots(root))
                foreach (var node in Walk(slot))
                    yield return node;
        }
    }

    /// <summary>
    /// Returns the first node for which <paramref name="predicate"/> returns <c>true</c>
    /// when iterating in <see cref="Walk"/> order, or <c>null</c> if no node matches.
    /// Short-circuits on the first match.
    /// </summary>
    /// <param name="root">The root of the sub-tree to search.</param>
    /// <param name="predicate">The matching condition.</param>
    /// <returns>The first matching node, or <c>null</c>.</returns>
    public static IComponentVM? Find(IComponentVM root, Func<IComponentVM, bool> predicate)
    {
        foreach (var node in Walk(root))
            if (predicate(node))
                return node;
        return null;
    }

    /// <summary>
    /// Yields <paramref name="root"/> then descends only into children whose parent
    /// reports as expanded. A node that does NOT implement <see cref="IExpandable"/>
    /// is treated as always-expanded. See spec/13-tree-utilities.md §Expand-aware traversal.
    /// </summary>
    public static IEnumerable<IComponentVM> WalkExpanded(IComponentVM root)
    {
        yield return root;
        if (root is IExpandable expandable && !expandable.IsExpanded) yield break;

        if (root is IEnumerable<IComponentVM> children)
        {
            foreach (var child in children)
                foreach (var node in WalkExpanded(child))
                    yield return node;
        }
        else
        {
            foreach (var slot in AggregateSlots(root))
                foreach (var node in WalkExpanded(slot))
                    yield return node;
        }
    }

    // Enumerate Component1..Component5 on aggregate VMs via reflection, skipping nulls.
    private static IEnumerable<IComponentVM> AggregateSlots(IComponentVM vm)
    {
        var type = vm.GetType();
        for (var i = 1; i <= 5; i++)
        {
            var prop = type.GetProperty($"Component{i}");
            if (prop is null) break;
            if (prop.GetValue(vm) is IComponentVM child)
                yield return child;
        }
    }
}
