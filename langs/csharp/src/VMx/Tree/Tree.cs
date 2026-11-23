using VMx.Aggregates;
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
    /// implementation. For aggregate VMs, walks non-null Component1..Component6 slots in order
    /// (via each aggregate's <c>IAggregateSlots.EnumerateSlots</c>).
    /// Leaf nodes yield exactly themselves.
    /// </summary>
    /// <param name="root">The root of the sub-tree to walk.</param>
    /// <returns>A lazy sequence of nodes in DFS pre-order.</returns>
    public static IEnumerable<IComponentVM> Walk(IComponentVM root) =>
        PreOrder(root, static _ => true);

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
    public static IEnumerable<IComponentVM> WalkExpanded(IComponentVM root) =>
        PreOrder(root, static node => !(node is IExpandable expandable && !expandable.IsExpanded));

    // Pre-order with an explicit stack of open levels, one enumerator per level, in
    // place of a nested iterator per level. A node is yielded before its children are
    // read, and its children are read only when the walk descends into it, so the
    // factory read order and error timing match the recursive walk (spec/13 §2, §6.1).
    // Tree depth costs heap, not call stack, so a deep chain cannot overflow it.
    private static IEnumerable<IComponentVM> PreOrder(
        IComponentVM root,
        Func<IComponentVM, bool> shouldDescend)
    {
        yield return root;
        if (!shouldDescend(root)) yield break;

        var open = new Stack<IEnumerator<IComponentVM>>();
        open.Push(ChildrenOf(root).GetEnumerator());
        try
        {
            while (open.Count > 0)
            {
                var level = open.Peek();
                if (!level.MoveNext())
                {
                    open.Pop().Dispose();
                    continue;
                }

                var child = level.Current;
                yield return child;
                if (shouldDescend(child))
                    open.Push(ChildrenOf(child).GetEnumerator());
            }
        }
        finally
        {
            // Released innermost first, also when the consumer stops early or a read throws.
            while (open.Count > 0)
                open.Pop().Dispose();
        }
    }

    // The children of a node in visit order: its IEnumerable<IComponentVM> members, or
    // its non-null aggregate slots. Other nodes are leaves.
    private static IEnumerable<IComponentVM> ChildrenOf(IComponentVM node)
    {
        if (node is IEnumerable<IComponentVM> children) return children;
        if (node is IAggregateSlots agg) return agg.EnumerateSlots();
        return [];
    }
}
