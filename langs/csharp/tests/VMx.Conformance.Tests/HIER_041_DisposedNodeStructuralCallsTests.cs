using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// HIER-041: a disposed node refuses every structural call
/// (spec/18-hierarchical-vm.md §7.1, ADR-0190).
/// </summary>
public class HIER_041_DisposedNodeStructuralCallsTests
{
    private static readonly TestDispatcher Dispatcher = new();

    private sealed class Node(string key, IMessageHub hub, Func<Node, IEnumerable<Node>>? factory = null)
        : HierarchicalVM<string, Node>(key, factory ?? (_ => []), hub, Dispatcher, key)
    {
        public override ViewModelType Type => ViewModelType.Component;
    }

    private static List<object> Recorder(MessageHub hub)
    {
        var messages = new List<object>();
        hub.Messages
            .Where(message => message is TreeStructureChangedMessage or PropertyChangedMessage<IComponentVM>)
            .Subscribe(messages.Add);
        return messages;
    }

    private static BatchAttachResult<Node> Attach(
        Node receiver,
        Node item,
        string? parentKey,
        MissingParentPolicy policy = MissingParentPolicy.Park) =>
        receiver.AttachMany(
            [item],
            node => node.Model,
            _ => parentKey is null ? BatchParentKey<string>.Root : BatchParentKey<string>.For(parentKey),
            policy);

    private static IEnumerable<string> ChildrenChanges(List<object> messages) =>
        messages.OfType<PropertyChangedMessage<IComponentVM>>()
            .Where(message => message.PropertyName == nameof(Node.Children))
            .Select(message => ((Node)message.Sender).Model);

    [Fact, Trait("Conformance", "HIER-041")]
    public void HIER_041_Disposed_Node_Refuses_Every_Structural_Call()
    {
        using var hub = new MessageHub();
        var r = new Node("r", hub);
        var a = new Node("a", hub);
        var b = new Node("b", hub);
        var aa = new Node("aa", hub);
        var d = new Node("d", hub);
        r.AddChild(a);
        r.AddChild(b);
        a.AddChild(aa);
        _ = aa.Children;
        _ = b.Children;
        r.Construct();

        a.Dispose();
        a.Status.Should().Be(ConstructionStatus.Disposed);
        var messages = Recorder(hub);

        Action[] calls =
        [
            () => a.AddChild(d),
            () => a.RemoveChild(aa),
            () => a.ReparentChild(d),
            () => a.AddChild(aa),
            () => a.RemoveChild(d),
            () => a.InvalidateChildren(),
            () => a.InvalidateSubtree(),
            () => Attach(a, d, null),
        ];
        foreach (var call in calls)
            call.Should().Throw<ObjectDisposedException>();

        a.Children.Should().Equal(aa);
        aa.HierarchicalParent.Should().BeSameAs(a);
        d.HierarchicalParent.Should().BeNull();
        messages.Should().BeEmpty();

        ((Action)(() => b.AddChild(aa))).Should().Throw<ObjectDisposedException>();
        ((Action)(() => b.ReparentChild(aa))).Should().Throw<ObjectDisposedException>();
        aa.HierarchicalParent.Should().BeSameAs(a);
        a.Children.Should().Equal(aa);
        b.Children.Should().BeEmpty();
        messages.Should().BeEmpty();

        var result = Attach(r, d, "a");
        result.Added.Should().BeEmpty();
        result.Orphans.Should().BeEmpty();
        result.Rejections.Should().ContainSingle()
            .Which.Reason.Should().Be(BatchAttachRejectionReason.AttachmentFailed);
        result.Rejections[0].Item.Should().BeSameAs(d);
        r.ParkedAttachCount.Should().Be(0);
        d.HierarchicalParent.Should().BeNull();
        a.Children.Should().Equal(aa);
        messages.Should().BeEmpty();

        r.InvalidateSubtree();
        ChildrenChanges(messages).Should().BeEquivalentTo(["aa", "b", "r"]);
        ChildrenChanges(messages).Should().NotContain("a");
        a.Children.Should().Equal(aa);
        aa.HierarchicalParent.Should().BeSameAs(a);
    }

    [Fact, Trait("Conformance", "HIER-041")]
    public void HIER_041_Disposed_Root_Refuses_AttachMany_From_A_Live_Child()
    {
        using var hub = new MessageHub();
        var root = new Node("root", hub);
        var c = new Node("c", hub);
        var item = new Node("item", hub);
        root.AddChild(c);
        root.Dispose();
        var messages = Recorder(hub);

        ((Action)(() => Attach(c, item, "missing"))).Should().Throw<ObjectDisposedException>();

        root.ParkedAttachCount.Should().Be(0);
        item.HierarchicalParent.Should().BeNull();
        messages.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "HIER-041")]
    public void HIER_041_Refused_Call_Does_Not_Materialize_A_Disposed_Lazy_Node()
    {
        using var hub = new MessageHub();
        var factoryCalls = 0;
        var lazy = new Node("lazy", hub, _ =>
        {
            factoryCalls++;
            return [];
        });
        var d = new Node("d", hub);
        lazy.Dispose();

        ((Action)(() => lazy.AddChild(d))).Should().Throw<ObjectDisposedException>();
        ((Action)(() => lazy.RemoveChild(d))).Should().Throw<ObjectDisposedException>();
        ((Action)(() => lazy.InvalidateChildren())).Should().Throw<ObjectDisposedException>();
        ((Action)(() => lazy.InvalidateSubtree())).Should().Throw<ObjectDisposedException>();

        factoryCalls.Should().Be(0);
        d.HierarchicalParent.Should().BeNull();
    }

    [Fact, Trait("Conformance", "HIER-041")]
    public void HIER_041_Live_Node_Still_Removes_Transfers_And_Invalidates_A_Disposed_Child()
    {
        using var hub = new MessageHub();
        var r = new Node("r", hub);
        var other = new Node("other", hub);
        var x = new Node("x", hub);
        var y = new Node("y", hub);
        r.AddChild(x);
        r.AddChild(y);
        x.Dispose();
        y.Dispose();

        r.RemoveChild(x);
        x.HierarchicalParent.Should().BeNull();
        other.ReparentChild(y);
        y.HierarchicalParent.Should().BeSameAs(other);
        r.Children.Should().BeEmpty();

        other.InvalidateChildren();
        y.HierarchicalParent.Should().BeNull();
    }
}
