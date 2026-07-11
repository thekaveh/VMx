using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public class HIER_023_to_030_BatchAttachTests
{
    private sealed class Model(string key, string? parentKey = null)
    {
        public string Key { get; } = key;
        public string? ParentKey { get; } = parentKey;
    }

    private sealed class Node(string key, string? parentKey = null)
        : HierarchicalVM<Model, Node>(
            new Model(key, parentKey),
            _ => [],
            new TestHub(),
            new TestDispatcher(),
            key)
    {
        public override ViewModelType Type => ViewModelType.Component;
    }

    private static BatchAttachResult<Node> Attach(
        Node root,
        IEnumerable<Node> items,
        MissingParentPolicy policy = MissingParentPolicy.Park) =>
        root.AttachMany(
            items,
            node => node.Model.Key,
            node => node.Model.ParentKey is null
                ? BatchParentKey<string>.Root
                : BatchParentKey<string>.For(node.Model.ParentKey),
            policy);

    [Fact]
    [Trait("Conformance", "HIER-023")]
    public void HIER_023_Child_Before_Parent_Reaches_Stable_Fixpoint()
    {
        var root = new Node("root");
        var grandchild = new Node("grandchild", "child-a");
        var childB = new Node("child-b", "parent");
        var childA = new Node("child-a", "parent");
        var parent = new Node("parent");

        var result = Attach(root, [grandchild, childB, childA, parent]);

        result.Added.Should().BeEquivalentTo([grandchild, childB, childA, parent]);
        root.Children.Should().Equal(parent);
        parent.Children.Should().Equal(childB, childA);
        childA.Children.Should().Equal(grandchild);
        grandchild.Path.Should().Equal(root, parent, childA, grandchild);
        result.Rejections.Should().BeEmpty();
    }

    [Fact]
    [Trait("Conformance", "HIER-024")]
    public void HIER_024_Root_Parent_Key_Attaches_Multiple_Roots_In_Order()
    {
        var root = new Node("root");
        var first = new Node("first");
        var second = new Node("second");
        var result = Attach(root, [first, second]);

        result.Added.Should().Equal(first, second);
        root.Children.Should().Equal(first, second);
    }

    [Fact]
    [Trait("Conformance", "HIER-025")]
    public void HIER_025_Duplicate_Keys_Never_Replace_First_Node()
    {
        var root = new Node("root");
        var existing = new Node("existing");
        root.AddChild(existing);
        var conflict = new Node("existing");
        var first = new Node("new");
        var batchConflict = new Node("new");

        var result = Attach(root, [conflict, first, batchConflict]);

        result.Added.Should().Equal(first);
        result.Duplicates.Should().Equal(conflict, batchConflict);
        result.Rejections.Select(item => item.Reason).Should().Equal(
            BatchAttachRejectionReason.DuplicateExistingKey,
            BatchAttachRejectionReason.DuplicateBatchKey);
        root.Children.Should().Equal(existing, first);
        Attach(root, [first]).Duplicates.Should().Equal(first);
        root.Children.Should().Equal(existing, first);
    }

    [Fact]
    [Trait("Conformance", "HIER-026")]
    public void HIER_026_Parked_Orphan_Resolves_Across_Batches()
    {
        var root = new Node("root");
        var child = new Node("child", "parent");
        Attach(root, [child]).Orphans.Should().Equal(child);
        root.ParkedAttachCount.Should().Be(1);

        var parent = new Node("parent");
        var result = Attach(root, [parent]);

        result.Added.Should().BeEquivalentTo([parent, child]);
        child.HierarchicalParent.Should().BeSameAs(parent);
        root.ParkedAttachCount.Should().Be(0);
    }

    [Fact]
    [Trait("Conformance", "HIER-027")]
    public void HIER_027_Reject_Policy_Does_Not_Retain_Orphan()
    {
        var root = new Node("root");
        var child = new Node("child", "parent");
        Attach(root, [child], MissingParentPolicy.Reject).Orphans.Should().Equal(child);
        root.ParkedAttachCount.Should().Be(0);

        var parent = new Node("parent");
        Attach(root, [parent]);
        child.HierarchicalParent.Should().BeNull();
        parent.Children.Should().BeEmpty();
    }

    [Fact]
    [Trait("Conformance", "HIER-028")]
    public void HIER_028_Cycles_Are_Terminal_NonThrowing_Rejections()
    {
        var root = new Node("root");
        var first = new Node("first", "second");
        var second = new Node("second", "first");
        var result = Attach(root, [first, second]);

        result.Added.Should().BeEmpty();
        result.Orphans.Should().BeEmpty();
        result.Rejections.Select(item => item.Reason).Should().Equal(
            BatchAttachRejectionReason.Cycle,
            BatchAttachRejectionReason.Cycle);
        root.ParkedAttachCount.Should().Be(0);
    }

    [Fact]
    [Trait("Conformance", "HIER-029")]
    public void HIER_029_Rejections_Are_Structured_And_Parent_Links_Stay_Atomic()
    {
        var root = new Node("root");
        var outside = new Node("outside");
        var attached = new Node("attached");
        outside.AddChild(attached);
        var detachedSameKey = new Node("attached");

        var result = Attach(root, [attached, detachedSameKey]);

        result.Rejections.Single().Item.Should().BeSameAs(attached);
        result.Rejections.Single().Reason.Should().Be(BatchAttachRejectionReason.AlreadyAttached);
        attached.HierarchicalParent.Should().BeSameAs(outside);
        outside.Children.Should().Equal(attached);
        result.Added.Should().Equal(detachedSameKey);
        root.Children.Should().Equal(detachedSameKey);

        var failed = root.AttachMany(
            [new Node("bad")],
            _ => throw new InvalidOperationException("bad key"),
            _ => BatchParentKey<string>.Root);
        failed.Rejections.Single().Reason.Should().Be(BatchAttachRejectionReason.SelectorFailed);
    }

    [Fact]
    [Trait("Conformance", "HIER-030")]
    public void HIER_030_Dispose_Clears_Root_Owned_Parked_Items()
    {
        var root = new Node("root");
        Attach(root, [new Node("child", "missing")]);
        root.ParkedAttachCount.Should().Be(1);

        root.Dispose();

        root.ParkedAttachCount.Should().Be(0);
    }
}
