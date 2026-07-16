using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public class HIER_019_to_022_Invalidation_Tests
{
    private sealed class Model
    {
    }

    private sealed class Node : HierarchicalVM<Model, Node>
    {
        public override ViewModelType Type => ViewModelType.Component;

        public Node(Func<Node, IEnumerable<Node>>? childrenFactory = null, TestHub? hub = null)
            : base(
                new Model(),
                childrenFactory ?? (_ => []),
                hub ?? new TestHub(),
                new TestDispatcher())
        {
        }
    }

    [Fact, Trait("Conformance", "HIER-019")]
    public void HIER_019_InvalidateChildren_Reloads_On_Next_Access()
    {
        var calls = 0;
        var root = new Node(_ =>
        {
            calls++;
            return [new Node()];
        });
        var first = root.Children[0];

        root.InvalidateChildren();
        var second = root.Children[0];

        calls.Should().Be(2);
        second.Should().NotBeSameAs(first);
    }

    [Fact]
    public void InvalidateChildren_Detaches_Discarded_Children()
    {
        var root = new Node(_ => [new Node()]);
        var discarded = root.Children[0];

        root.InvalidateChildren();
        var replacement = root.Children[0];

        replacement.Should().NotBeSameAs(discarded);
        discarded.HierarchicalParent.Should().BeNull();
        discarded.IsRoot.Should().BeTrue();
        root.AddChild(discarded);
        root.Children.Should().Contain(discarded);
    }

    [Fact, Trait("Conformance", "HIER-020")]
    public void HIER_020_InvalidateChildren_Unmaterialized_Is_Noop()
    {
        var calls = 0;
        var root = new Node(_ =>
        {
            calls++;
            return [];
        });

        root.InvalidateChildren();

        calls.Should().Be(0);
    }

    [Fact, Trait("Conformance", "HIER-021")]
    public void HIER_021_InvalidateSubtree_Reloads_Materialized_Descendants()
    {
        var grandchildCalls = 0;
        var child = new Node(_ =>
        {
            grandchildCalls++;
            return [new Node()];
        });
        var root = new Node(_ => [child]);
        _ = root.Children;
        var firstGrandchild = child.Children[0];

        root.InvalidateSubtree();
        var reloadedChild = root.Children[0];
        var secondGrandchild = reloadedChild.Children[0];

        grandchildCalls.Should().Be(2);
        secondGrandchild.Should().NotBeSameAs(firstGrandchild);
    }

    [Fact, Trait("Conformance", "HIER-022")]
    public void HIER_022_InvalidateChildren_Publishes_Children_PropertyChanged()
    {
        using var hub = new TestHub();
        var seen = new List<PropertyChangedMessage<IComponentVM>>();
        using var sub = hub.Messages.Subscribe(message =>
        {
            if (message is PropertyChangedMessage<IComponentVM> propertyChanged)
                seen.Add(propertyChanged);
        });
        var root = new Node(_ => [new Node()], hub);
        _ = root.Children;

        root.InvalidateChildren();

        seen.Should().Contain(m => ReferenceEquals(m.Sender, root) && m.PropertyName == nameof(root.Children));
    }
}
