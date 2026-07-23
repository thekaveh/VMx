using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public sealed class HIER_031_FactoryHydrationTests
{
    private sealed class Node : HierarchicalVM<string, Node>
    {
        public Node(
            string name,
            Func<Node, IEnumerable<Node>>? factory = null,
            TestHub? hub = null)
            : base(name, factory ?? (_ => []), hub ?? new TestHub(), new TestDispatcher(), name)
        {
        }

        public override ViewModelType Type => ViewModelType.Component;
    }

    [Fact]
    [Trait("Conformance", "HIER-031")]
    public void HIER_031_Preflights_Complete_Snapshot_Before_Mutation_And_Retries()
    {
        using var hub = new TestHub();
        var messages = new List<IMessage>();
        using var subscription = hub.Messages.Subscribe(messages.Add);
        var first = new Node("first", hub: hub);
        var second = new Node("second", hub: hub);
        var grandchild = new Node("grandchild", hub: hub);
        first.AddChild(grandchild);
        first.Path.Should().Equal(first);
        grandchild.Path.Should().Equal(first, grandchild);
        messages.Clear();
        var snapshot = new List<Node> { first, first };
        var root = new Node("root", _ => snapshot, hub);

        var read = () => root.Children;
        read.Should().Throw<InvalidOperationException>().WithMessage("*factory*");
        first.HierarchicalParent.Should().BeNull();
        messages.Should().BeEmpty();

        snapshot.Clear();
        snapshot.AddRange([first, second]);
        root.Children.Should().Equal(first, second);
        first.HierarchicalParent.Should().BeSameAs(root);
        second.HierarchicalParent.Should().BeSameAs(root);
        first.Path.Should().Equal(root, first);
        grandchild.Path.Should().Equal(root, first, grandchild);
        messages.Should().BeEmpty();
    }

    [Fact]
    [Trait("Conformance", "HIER-031")]
    public void HIER_031_Rejects_Self_Ancestor_And_Already_Parented_Output()
    {
        var nullRoot = new Node("null", _ => [null!]);
        var nullRead = () => nullRoot.Children;
        nullRead.Should().Throw<InvalidOperationException>().WithMessage("*factory*");
        nullRoot.HierarchicalParent.Should().BeNull();

        Node? self = null;
        self = new Node("self", _ => [self!]);
        var selfRead = () => self.Children;
        selfRead.Should().Throw<InvalidOperationException>().WithMessage("*factory*");
        self.HierarchicalParent.Should().BeNull();

        var ancestor = new Node("ancestor");
        var descendant = new Node("descendant", _ => [ancestor]);
        ancestor.AddChild(descendant);
        var ancestorRead = () => descendant.Children;
        ancestorRead.Should().Throw<InvalidOperationException>().WithMessage("*factory*");
        descendant.HierarchicalParent.Should().BeSameAs(ancestor);

        var oldParent = new Node("old");
        var attached = new Node("attached");
        oldParent.AddChild(attached);
        var newParent = new Node("new", _ => [attached]);
        var attachedRead = () => newParent.Children;
        attachedRead.Should().Throw<InvalidOperationException>().WithMessage("*factory*");
        attached.HierarchicalParent.Should().BeSameAs(oldParent);
    }

    [Theory]
    [InlineData("add")]
    [InlineData("remove")]
    [InlineData("reparent")]
    [InlineData("attach")]
    [InlineData("invalidate-children")]
    [InlineData("invalidate-subtree")]
    [Trait("Conformance", "HIER-032")]
    public void HIER_032_Rejects_Structural_Reentry_And_Permits_Retry(string operation)
    {
        using var hub = new TestHub();
        var messages = new List<IMessage>();
        using var subscription = hub.Messages.Subscribe(messages.Add);
        var child = new Node("child", hub: hub);
        var firstAttempt = true;
        var root = new Node("root", parent =>
        {
            if (firstAttempt)
            {
                firstAttempt = false;
                if (operation == "add") parent.AddChild(child);
                else if (operation == "remove") parent.RemoveChild(child);
                else if (operation == "reparent") parent.ReparentChild(child);
                else if (operation == "attach")
                    parent.AttachMany(
                        [child],
                        node => node.Model,
                        _ => BatchParentKey<string>.Root);
                else if (operation == "invalidate-children") parent.InvalidateChildren();
                else parent.InvalidateSubtree();
            }
            return [child];
        }, hub);

        var firstRead = () => root.Children;
        firstRead.Should().Throw<InvalidOperationException>().WithMessage("*factory*");
        root.Children.Should().Equal(child);
        child.HierarchicalParent.Should().BeSameAs(root);
        messages.Should().BeEmpty();
    }
}
