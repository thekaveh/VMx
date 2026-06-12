using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// HIER-018: ReparentChild rejects self- and ancestor-reparenting.
/// See spec/18-hierarchical-vm.md §5 and ADR-0037 §2.3.
/// </summary>
public class HIER_018_ReparentGuard_Tests
{
    private sealed class MyModel
    {
        public string Value { get; set; } = "m";
    }

    private sealed class MyNode : HierarchicalVM<MyModel, MyNode>
    {
        public override ViewModelType Type => ViewModelType.Component;

        public MyNode(
            Func<MyNode, IEnumerable<MyNode>> childrenFactory,
            TestHub hub,
            string? name = null)
            : base(new MyModel(), childrenFactory, hub, new TestDispatcher(), name)
        { }
    }

    [Fact]
    [Trait("Conformance", "HIER-018")]
    public void HIER_018_Reparent_Rejects_Self_And_Ancestor()
    {
        var hub = new TestHub();
        MyNode? leafRef = null;
        MyNode? midRef = null;
        var leaf = new MyNode(_ => [], hub, "leaf");
        leafRef = leaf;
        var mid = new MyNode(_ => [leafRef!], hub, "mid");
        midRef = mid;
        var root = new MyNode(_ => [midRef!], hub, "root");

        // Materialize the lazy tree so parent backpointers are wired.
        root.Children.Select(c => c.Name).Should().Equal("mid");
        mid.Children.Select(c => c.Name).Should().Equal("leaf");
        leaf.Path.Select(n => n.Name).Should().Equal("root", "mid", "leaf");

        var messages = new List<TreeStructureChangedMessage>();
        using var sub = hub.Messages
            .OfType<TreeStructureChangedMessage>()
            .Subscribe(messages.Add);

        // Self-reparenting raises.
        var self = () => leaf.ReparentChild(leaf);
        self.Should().Throw<InvalidOperationException>().WithMessage("*HIER-018*");

        // Reparenting an ancestor under its own descendant raises.
        var ancestor = () => leaf.ReparentChild(root);
        ancestor.Should().Throw<InvalidOperationException>().WithMessage("*HIER-018*");

        // Tree structure unchanged; no message published.
        root.HierarchicalParent.Should().BeNull();
        mid.HierarchicalParent.Should().BeSameAs(root);
        leaf.HierarchicalParent.Should().BeSameAs(mid);
        leaf.Depth.Should().Be(2);
        messages.Should().BeEmpty();
    }
}
