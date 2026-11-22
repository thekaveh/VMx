using System.Runtime.ExceptionServices;
using FluentAssertions;
using static VMx.Tree.Tree;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Hierarchical;

/// <summary>
/// Unit tests for <see cref="HierarchicalVM{TModel,TVM}"/> edge cases.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class HierarchicalVMTests
{
    // ── Test doubles ─────────────────────────────────────────────────────────

    private sealed class Model
    {
        public string Tag { get; }
        public Model(string tag = "") => Tag = tag;
    }

    private sealed class Node : HierarchicalVM<Model, Node>
    {
        public override ViewModelType Type => ViewModelType.Component;

        public Node(
            Model model,
            Func<Node, IEnumerable<Node>> childrenFactory,
            TestHub? hub = null,
            TestDispatcher? dispatcher = null,
            string? name = null,
            bool eagerChildren = false)
            : base(
                model,
                childrenFactory,
                hub ?? new TestHub(),
                dispatcher ?? new TestDispatcher(),
                name,
                eagerChildren: eagerChildren)
        { }
    }

    private static Node Leaf(TestHub? hub = null, string? name = null)
        => new(new Model(), _ => [], hub, name: name);

    private static Node Parent(IEnumerable<Node> children, TestHub? hub = null)
    {
        var list = children.ToList();
        return new Node(new Model(), _ => list, hub);
    }

    // ── Empty children factory ───────────────────────────────────────────────

    [Fact]
    public void Empty_Children_Factory_Returns_Empty_List()
    {
        var node = Leaf();
        node.Children.Should().BeEmpty();
        node.IsLeaf.Should().BeTrue();
    }

    [Fact]
    public void Multiple_Accesses_To_Children_Return_Same_Instance()
    {
        var node = Leaf();
        var first = node.Children;
        var second = node.Children;
        second.Should().BeSameAs(first);
    }

    // ── Single-node tree ─────────────────────────────────────────────────────

    [Fact]
    public void Single_Node_Tree_Path_Contains_Only_Self()
    {
        var node = Leaf();
        node.Path.Should().ContainSingle().Which.Should().BeSameAs(node);
    }

    [Fact]
    public void Single_Node_Depth_Is_Zero()
    {
        var node = Leaf();
        node.Depth.Should().Be(0);
    }

    [Fact]
    public void Single_Node_IsRoot_True_And_IsLeaf_True()
    {
        var node = Leaf();
        node.IsRoot.Should().BeTrue();
        node.IsLeaf.Should().BeTrue();
    }

    // ── Reparenting ──────────────────────────────────────────────────────────

    [Fact]
    public void Reparent_Updates_Parent_Reference()
    {
        var hub = new TestHub();
        var child = new Node(new Model(), _ => [], hub);
        var parent1 = new Node(new Model(), _ => [], hub);
        var parent2 = new Node(new Model(), _ => [], hub);

        parent1.AddChild(child);
        child.HierarchicalParent.Should().BeSameAs(parent1);

        parent2.ReparentChild(child);
        child.HierarchicalParent.Should().BeSameAs(parent2);

        parent1.Children.Should().NotContain(child);
        parent2.Children.Should().Contain(child);
    }

    [Fact]
    public void Reparent_Is_Noop_When_Parent_Is_Same()
    {
        var hub = new TestHub();
        var child = new Node(new Model(), _ => [], hub);
        var parent = new Node(new Model(), _ => [], hub);

        parent.AddChild(child);

        using var messages = new RecordedMessages<TreeStructureChangedMessage>(hub.Messages);

        parent.ReparentChild(child); // same parent — no-op
        messages.Items.Should().BeEmpty("reparent to same parent is a no-op");
    }

    // ── Multiple lazy accesses ───────────────────────────────────────────────

    [Fact]
    public void Lazy_Children_Factory_Invoked_Exactly_Once()
    {
        var invocations = 0;
        var node = new Node(new Model(), _ =>
        {
            invocations++;
            return [Leaf()];
        });

        _ = node.Children;
        _ = node.Children;
        _ = node.Children;

        invocations.Should().Be(1, "factory invoked only on first access");
    }

    // ── Path cache invalidation across a chain ───────────────────────────────

    [Fact]
    public void Path_Cache_Invalidated_For_Whole_Subtree_On_Reparent()
    {
        var hub = new TestHub();
        var grandchild = new Node(new Model(), _ => [], hub);
        var child = new Node(new Model(), _ => [grandchild], hub);
        var root = new Node(new Model(), _ => [child], hub);

        // Force materialization.
        _ = root.Children;
        _ = child.Children;

        // Cache paths.
        var oldGrandchildPath = grandchild.Path;
        var oldChildPath = child.Path;

        // Reparent child to a new root.
        var newRoot = new Node(new Model(), _ => [], hub);
        newRoot.ReparentChild(child);

        // Both child and grandchild paths must be invalidated.
        child.Path.Should().NotBeSameAs(oldChildPath, "path cache invalidated after reparent");
        grandchild.Path.Should().NotBeSameAs(oldGrandchildPath, "grandchild path cache also invalidated");
        grandchild.Path[0].Should().BeSameAs(newRoot);
    }

    // ── AddChild / RemoveChild messaging ────────────────────────────────────

    [Fact]
    public void AddChild_Publishes_Added_Message_With_Correct_Index()
    {
        var hub = new TestHub();
        var parent = new Node(new Model(), _ => [], hub);
        var c1 = new Node(new Model(), _ => [], hub);
        var c2 = new Node(new Model(), _ => [], hub);

        using var messages = new RecordedMessages<TreeStructureChangedMessage>(hub.Messages);

        parent.AddChild(c1);
        parent.AddChild(c2);

        messages.Items[0].Index.Should().Be(0, "first child added at index 0");
        messages.Items[1].Index.Should().Be(1, "second child added at index 1");
    }

    [Fact]
    public void RemoveChild_Noop_When_Child_Not_In_List()
    {
        var hub = new TestHub();
        var parent = new Node(new Model(), _ => [], hub);
        var orphan = new Node(new Model(), _ => [], hub);

        using var messages = new RecordedMessages<TreeStructureChangedMessage>(hub.Messages);

        parent.RemoveChild(orphan); // not a child — should be a no-op
        messages.Items.Should().BeEmpty("no message for removing a non-child");
    }

    // ── IsFirst / IsLast on single child ────────────────────────────────────

    [Fact]
    public void Single_Child_Is_Both_First_And_Last()
    {
        var child = Leaf();
        var root = Parent([child]);
        _ = root.Children;

        child.IsFirst.Should().BeTrue();
        child.IsLast.Should().BeTrue();
    }

    // ── Depth across multiple levels ─────────────────────────────────────────

    [Fact]
    public void Depth_Accumulates_Correctly_Across_Five_Levels()
    {
        var nodes = new Node[5];
        nodes[4] = Leaf();
        for (int i = 3; i >= 0; i--)
        {
            var child = nodes[i + 1];
            nodes[i] = new Node(new Model(), _ => [child]);
        }

        for (int i = 0; i < 5; i++)
        {
            _ = nodes[i].Children; // force materialization
        }

        for (int i = 0; i < 5; i++)
        {
            nodes[i].Depth.Should().Be(i, $"node at level {i} should have depth {i}");
        }
    }

    // ── Hub null check ───────────────────────────────────────────────────────

    [Fact]
    public void AddChild_Throws_On_Null()
    {
        var parent = Leaf();
        var act = () => parent.AddChild(null!);
        act.Should().Throw<ArgumentNullException>();
    }

    [Fact]
    public void RemoveChild_Throws_On_Null()
    {
        var parent = Leaf();
        var act = () => parent.RemoveChild(null!);
        act.Should().Throw<ArgumentNullException>();
    }

    [Fact]
    public void ReparentChild_Throws_On_Null()
    {
        var parent = Leaf();
        var act = () => parent.ReparentChild(null!);
        act.Should().Throw<ArgumentNullException>();
    }

    // ── Batch rejection diagnostics ──────────────────────────────────────────

    [Fact]
    public void AttachMany_Selector_Failure_Rejection_Detail_Carries_The_Exception_Message()
    {
        var root = new Node(new Model(), _ => []);
        var failure = new InvalidOperationException("bad key");

        var result = root.AttachMany(
            [new Node(new Model("bad"), _ => [])],
            _ => throw failure,
            _ => BatchParentKey<string>.Root);

        var rejection = result.Rejections.Should().ContainSingle().Subject;
        rejection.Reason.Should().Be(BatchAttachRejectionReason.SelectorFailed);
        rejection.Detail.Should().Be(failure.Message);
    }

    // ── Deep chains and pre-order (no recursion; spec/13 §2 and §3) ──────────

    private const int DeepChainLevels = 10_000;

    // A chain of `levels` nodes. Each child list comes from a factory, so building
    // the chain does not touch the path caches (AddChild reads them).
    private static Node DeepChain(int levels, TestHub hub, TestDispatcher dispatcher)
    {
        Node Build(int depth)
        {
            IEnumerable<Node> Children(Node _)
            {
                if (depth + 1 < levels)
                    yield return Build(depth + 1);
            }

            return new Node(new Model(), Children, hub, dispatcher, name: $"n{depth}");
        }

        return Build(0);
    }

    // A recursive walk or invalidation of a 10,000-level chain overflows a 512 KiB
    // stack (measured), but it passed on the default thread stack (measured on net9.0,
    // Release). So each deep test runs its body on a thread with this fixed stack, and
    // a recursive implementation fails it. The 60 s budget bounds the body's run time.
    private const int DeepChainStackBytes = 512 * 1024;
    private const int DeepChainBudgetMs = 60_000;

    private static void RunOnSmallStack(Action body)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                body();
            }
            catch (Exception caught)
            {
                failure = caught;
            }
        }, DeepChainStackBytes)
        {
            IsBackground = true,
        };
        thread.Start();
        thread.Join(DeepChainBudgetMs).Should().BeTrue(
            $"the deep-chain body finishes within {DeepChainBudgetMs} ms");
        if (failure is not null)
            ExceptionDispatchInfo.Capture(failure).Throw();
    }

    [Fact]
    public void DeepChain_Walks_Find_And_Depth_Reach_The_Last_Level() => RunOnSmallStack(() =>
    {
        var root = DeepChain(DeepChainLevels, new TestHub(), new TestDispatcher());

        var nodes = Walk(root).ToList();
        var last = (Node)nodes[^1];

        nodes.Select(n => n.Name).Should().Equal(
            Enumerable.Range(0, DeepChainLevels).Select(i => $"n{i}"));
        last.Depth.Should().Be(DeepChainLevels - 1);
        last.Path.Should().HaveCount(DeepChainLevels);
        WalkExpanded(root).Count().Should().Be(DeepChainLevels);
        Find(root, n => ReferenceEquals(n, last)).Should().BeSameAs(last);
    });

    [Fact]
    public void DeepChain_Moves_Under_A_New_Parent() => RunOnSmallStack(() =>
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var root = DeepChain(DeepChainLevels, hub, dispatcher);
        // Materialize top-down in a loop, so the move itself is what recurses.
        var last = root;
        while (!last.IsLeaf)
            last = last.Children[0];
        // Cache the deepest path first, so the move has to invalidate it.
        last.Depth.Should().Be(DeepChainLevels - 1);
        var newRoot = new Node(new Model(), _ => [], hub, dispatcher, name: "new-root");

        newRoot.AddChild(root);

        root.HierarchicalParent.Should().BeSameAs(newRoot);
        last.Depth.Should().Be(DeepChainLevels);
        last.Path.Should().HaveCount(DeepChainLevels + 1);
        last.Path[0].Should().BeSameAs(newRoot);
        last.Path[1].Should().BeSameAs(root);
    });

    [Fact]
    public void Walks_Pin_Preorder_And_Child_Read_Order_On_A_Small_Tree()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var shape = new Dictionary<string, string[]>
        {
            ["root"] = ["a", "b"],
            ["a"] = ["a1", "a2"],
            ["a1"] = ["a1x"],
            ["b"] = ["b1"],
        };
        var reads = new List<string>();
        var byName = new Dictionary<string, Node>();
        foreach (var name in new[] { "root", "a", "a1", "a1x", "a2", "b", "b1" })
        {
            var self = name;
            byName[self] = new Node(
                new Model(),
                _ =>
                {
                    reads.Add(self);
                    return shape.TryGetValue(self, out var kids)
                        ? kids.Select(k => byName[k])
                        : Enumerable.Empty<Node>();
                },
                hub,
                dispatcher,
                name: self);
        }
        var root = byName["root"];
        var expected = new[] { "root", "a", "a1", "a1x", "a2", "b", "b1" };

        Walk(root).Select(n => n.Name).Should().Equal(expected);
        reads.Should().Equal(expected, "children are read in the same pre-order as the walk");
        WalkExpanded(root).Select(n => n.Name).Should().Equal(expected);
        Find(root, n => n.Name == "b1").Should().BeSameAs(byName["b1"]);
        byName["a1x"].Depth.Should().Be(3);
    }
}
