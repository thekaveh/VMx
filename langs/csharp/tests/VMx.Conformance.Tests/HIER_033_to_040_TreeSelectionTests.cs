using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// HIER-033..HIER-040 — the opt-in <see cref="TreeSelection{TModel,TVM}"/>
/// helper (spec/18 §10, ADR-0164).
/// </summary>
public class HIER_033_to_040_TreeSelectionTests
{
    private sealed class Model
    {
    }

    private sealed class Node : HierarchicalVM<Model, Node>
    {
        public override ViewModelType Type => ViewModelType.Component;

        public Node(TestHub hub, Func<Node, IEnumerable<Node>>? childrenFactory = null, string? name = null)
            : base(new Model(), childrenFactory ?? (_ => []), hub, new TestDispatcher(), name)
        {
        }
    }

    private sealed class Tree
    {
        public Tree(TestHub? hub = null)
        {
            Hub = hub ?? new TestHub();
            AA = new Node(Hub, Count, "AA");
            A = new Node(Hub, _ => [AA], "A");
            B = new Node(Hub, Count, "B");
            Root = new Node(Hub, _ => [A, B], "Root");
            _ = Root.Children;
            _ = A.Children;
        }

        public TestHub Hub { get; }
        public Node Root { get; }
        public Node A { get; }
        public Node AA { get; }
        public Node B { get; }

        // Factory calls of the never-materialized nodes AA and B.
        public int FactoryCalls { get; private set; }

        public IEnumerable<Node> Count(Node _)
        {
            FactoryCalls++;
            return [];
        }
    }

    private static (TreeSelection<Model, Node> Selection, List<Node?> Seen) SelectAA(Tree tree)
    {
        var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = new List<Node?>();
        selection.CurrentChanged.Subscribe(seen.Add);
        return (selection, seen);
    }

    [Fact, Trait("Conformance", "HIER-033")]
    public void HIER_033_Reentrant_Select_Reaches_Every_Subscriber_In_Order()
    {
        var tree = new Tree();
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        using var first = selection.CurrentChanged.Subscribe(value =>
        {
            if (ReferenceEquals(value, tree.AA)) selection.Select(tree.A);
        });
        var seen = new List<Node?>();
        using var second = selection.CurrentChanged.Subscribe(seen.Add);

        selection.Select(tree.AA);

        seen.Should().Equal(tree.AA, tree.A);
        selection.Current.Should().BeSameAs(tree.A);
    }

    [Fact, Trait("Conformance", "HIER-033")]
    public void HIER_033_Select_And_Clear_Publish_Each_Change_Once()
    {
        var tree = new Tree();
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        var seen = new List<Node?>();
        using var sub = selection.CurrentChanged.Subscribe(seen.Add);

        selection.CanSelect(tree.Root).Should().BeTrue();
        selection.CanSelect(tree.A).Should().BeTrue();
        selection.CanSelect(tree.AA).Should().BeTrue();

        selection.Select(tree.AA);
        selection.Current.Should().BeSameAs(tree.AA);
        selection.Select(tree.AA);
        selection.Clear();
        selection.Current.Should().BeNull();
        selection.Clear();

        seen.Should().Equal(tree.AA, null);
    }

    [Fact, Trait("Conformance", "HIER-034")]
    public void HIER_034_Select_Rejects_A_Node_Outside_The_Materialized_Tree()
    {
        var tree = new Tree();
        var detachedCalls = 0;
        var detached = new Node(tree.Hub, _ => { detachedCalls++; return []; }, "Detached");
        var otherHub = new TestHub();
        var otherCalls = 0;
        var otherChild = new Node(otherHub, _ => { otherCalls++; return []; }, "OtherChild");
        var otherRoot = new Node(otherHub, _ => [otherChild], "OtherRoot");
        _ = otherRoot.Children;
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.A);
        tree.B.Dispose();
        var seen = new List<Node?>();
        using var sub = selection.CurrentChanged.Subscribe(seen.Add);

        foreach (var rejected in new[] { detached, otherRoot, otherChild, tree.B })
        {
            selection.CanSelect(rejected).Should().BeFalse();
            selection.Invoking(s => s.Select(rejected)).Should().Throw<InvalidOperationException>();
            selection.Current.Should().BeSameAs(tree.A);
        }

        seen.Should().BeEmpty();
        tree.FactoryCalls.Should().Be(0);
        detachedCalls.Should().Be(0);
        otherCalls.Should().Be(0);
    }

    [Fact, Trait("Conformance", "HIER-035")]
    public void HIER_035_Removing_An_Ancestor_Clears_The_Selection()
    {
        var tree = new Tree();
        var (selection, seen) = SelectAA(tree);

        tree.Root.RemoveChild(tree.A);

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
    }

    [Fact, Trait("Conformance", "HIER-035")]
    public void HIER_035_Removing_The_Current_Node_Clears_The_Selection()
    {
        var tree = new Tree();
        var (selection, seen) = SelectAA(tree);

        tree.A.RemoveChild(tree.AA);

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
    }

    [Fact, Trait("Conformance", "HIER-036")]
    public void HIER_036_A_Move_Inside_Keeps_The_Selection_And_A_Transfer_Out_Clears_It()
    {
        var tree = new Tree();
        var otherHub = new TestHub();
        var otherRoot = new Node(otherHub, name: "OtherRoot");
        var (selection, seen) = SelectAA(tree);

        tree.B.AddChild(tree.A);

        tree.A.HierarchicalParent.Should().BeSameAs(tree.B);
        selection.Current.Should().BeSameAs(tree.AA);
        seen.Should().BeEmpty();

        otherRoot.AddChild(tree.A);

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
    }

    [Fact, Trait("Conformance", "HIER-037")]
    public void HIER_037_Invalidating_An_Ancestor_Clears_The_Selection()
    {
        var tree = new Tree();
        var (selection, seen) = SelectAA(tree);

        tree.A.InvalidateChildren();

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
        tree.AA.Status.Should().NotBe(ConstructionStatus.Disposed);
        tree.AA.HierarchicalParent.Should().BeNull();
        selection.CanSelect(tree.AA).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "HIER-038")]
    public void HIER_038_Disposing_An_Ancestor_Clears_The_Selection()
    {
        var tree = new Tree();
        var (selection, seen) = SelectAA(tree);

        tree.A.Dispose();

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
        tree.A.HierarchicalParent.Should().BeSameAs(tree.Root);
        tree.Root.Children.Should().Contain(tree.A);
        selection.CanSelect(tree.AA).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "HIER-038")]
    public void HIER_038_Disposing_The_Current_Node_Clears_The_Selection()
    {
        var tree = new Tree();
        var (selection, seen) = SelectAA(tree);

        tree.AA.Dispose();

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
        selection.CanSelect(tree.AA).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "HIER-039")]
    public void HIER_039_Selection_Does_Not_Navigate()
    {
        var hub = new TestHub();
        var calls = 0;
        var a = new Node(hub, _ => { calls++; return [new Node(hub)]; }, "A");
        var root = new Node(hub, _ => [a], "Root");
        _ = root.Children;
        var messages = new List<IMessage>();
        using var hubSub = hub.Messages.Subscribe(messages.Add);
        var before = Snapshot(root, a);
        using var selection = new TreeSelection<Model, Node>(root);

        selection.Select(a);

        selection.Current.Should().BeSameAs(a);
        calls.Should().Be(0);
        Snapshot(root, a).Should().Equal(before);
        messages.Should().BeEmpty();

        selection.Clear();

        calls.Should().Be(0);
        Snapshot(root, a).Should().Equal(before);
        messages.Should().BeEmpty();
    }

    private static List<(ConstructionStatus Status, Node? Parent, bool IsCurrent)> Snapshot(params Node[] nodes)
        => nodes.Select(node => (node.Status, node.HierarchicalParent, node.IsCurrent)).ToList();

    [Fact, Trait("Conformance", "HIER-040")]
    public void HIER_040_A_Disposed_Selection_Is_Inert()
    {
        var tree = new Tree();
        var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = new List<Node?>();
        var completed = false;
        using var sub = selection.CurrentChanged.Subscribe(seen.Add, () => completed = true);

        selection.Dispose();

        completed.Should().BeTrue();
        seen.Should().BeEmpty();
        selection.Current.Should().BeNull();
        foreach (var node in new[] { tree.Root, tree.A, tree.AA, tree.B })
            selection.CanSelect(node).Should().BeFalse();

        selection.Invoking(s => s.Select(tree.A)).Should().NotThrow();
        selection.Invoking(s => s.Clear()).Should().NotThrow();
        tree.Invoking(t => t.A.RemoveChild(t.AA)).Should().NotThrow();
        tree.Invoking(t => t.Root.InvalidateChildren()).Should().NotThrow();
        tree.Invoking(t => t.A.Dispose()).Should().NotThrow();
        selection.Invoking(s => s.Dispose()).Should().NotThrow();

        selection.Current.Should().BeNull();
        seen.Should().BeEmpty();
    }
}
