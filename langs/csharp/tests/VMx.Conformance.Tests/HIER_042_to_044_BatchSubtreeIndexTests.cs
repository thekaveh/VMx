using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// HIER-042..044 — <c>AttachMany</c> indexes the materialized subtree of a
/// candidate (spec/18 §6, ADR-0212).
/// </summary>
public class HIER_042_to_044_BatchSubtreeIndexTests
{
    private sealed class Model(string key, string? parentKey = null)
    {
        public string Key { get; } = key;
        public string? ParentKey { get; } = parentKey;
    }

    private sealed class Node(
        string key,
        string? parentKey = null,
        Func<Node, IEnumerable<Node>>? factory = null)
        : HierarchicalVM<Model, Node>(
            new Model(key, parentKey),
            factory ?? (_ => []),
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
    [Trait("Conformance", "HIER-042")]
    public void HIER_042_Candidate_Attaches_Below_A_Node_Of_An_Attached_Subtree()
    {
        var root = new Node("root");
        var p = new Node("p");
        var c = new Node("c");
        p.AddChild(c);
        var x = new Node("x", "c");

        var result = Attach(root, [p, x]);

        result.Added.Should().Equal(p, x);
        result.Rejections.Should().BeEmpty();
        result.Orphans.Should().BeEmpty();
        result.Duplicates.Should().BeEmpty();
        root.Children.Should().Equal(p);
        p.Children.Should().Equal(c);
        c.Children.Should().Equal(x);
        x.Path.Should().Equal(root, p, c, x);
        root.ParkedAttachCount.Should().Be(0);
    }

    [Fact]
    [Trait("Conformance", "HIER-042")]
    public void HIER_042_Parent_Key_Naming_Own_Descendant_Is_A_Cycle()
    {
        var calls = 0;
        var root = new Node("root");
        var q = new Node("q", "d");
        var d = new Node("d", factory: _ =>
        {
            calls++;
            return [];
        });
        q.AddChild(d);

        var result = Attach(root, [q], MissingParentPolicy.Park);

        calls.Should().Be(0, "reading subtree keys must not run a children factory");
        result.Added.Should().BeEmpty();
        result.Orphans.Should().BeEmpty();
        result.Rejections.Should().ContainSingle();
        result.Rejections[0].Item.Should().BeSameAs(q);
        result.Rejections[0].Reason.Should().Be(BatchAttachRejectionReason.Cycle);
        root.ParkedAttachCount.Should().Be(0);
        q.HierarchicalParent.Should().BeNull();
    }

    [Fact]
    [Trait("Conformance", "HIER-043")]
    public void HIER_043_Descendant_Key_In_The_Index_Rejects_The_Candidate()
    {
        var root = new Node("root");
        var existing = new Node("c");
        root.AddChild(existing);
        var p = new Node("p");
        var inner = new Node("c");
        p.AddChild(inner);

        var result = Attach(root, [p]);

        result.Added.Should().BeEmpty();
        result.Duplicates.Should().Equal(p);
        result.Rejections.Should().ContainSingle();
        result.Rejections[0].Item.Should().BeSameAs(p);
        result.Rejections[0].Reason.Should().Be(BatchAttachRejectionReason.DuplicateExistingKey);
        p.HierarchicalParent.Should().BeNull();
        p.Children.Should().Equal(inner);
        root.Children.Should().Equal(existing);
    }

    [Fact]
    [Trait("Conformance", "HIER-043")]
    public void HIER_043_Descendant_Key_Claimed_First_Rejects_A_Later_Candidate()
    {
        var root = new Node("root");
        var p = new Node("p");
        var c = new Node("c");
        p.AddChild(c);
        var c2 = new Node("c", "p");

        var result = Attach(root, [p, c2]);

        result.Added.Should().Equal(p);
        result.Duplicates.Should().Equal(c2);
        result.Rejections.Should().ContainSingle();
        result.Rejections[0].Item.Should().BeSameAs(c2);
        result.Rejections[0].Reason.Should().Be(BatchAttachRejectionReason.DuplicateBatchKey);
        p.Children.Should().Equal(c);
        c2.HierarchicalParent.Should().BeNull();
    }

    [Fact]
    [Trait("Conformance", "HIER-043")]
    public void HIER_043_Earlier_Candidate_Key_Rejects_A_Subtree_That_Repeats_It()
    {
        var root = new Node("root");
        var p = new Node("p");
        var c = new Node("c");
        p.AddChild(c);
        var c2 = new Node("c", "p");

        var result = Attach(root, [c2, p]);

        result.Added.Should().BeEmpty();
        result.Duplicates.Should().Equal(p);
        result.Orphans.Should().Equal(c2);
        result.Rejections.Should().HaveCount(2);
        result.Rejections.Should().Contain(r =>
            ReferenceEquals(r.Item, p) && r.Reason == BatchAttachRejectionReason.DuplicateBatchKey);
        result.Rejections.Should().Contain(r =>
            ReferenceEquals(r.Item, c2) && r.Reason == BatchAttachRejectionReason.MissingParent);
        p.HierarchicalParent.Should().BeNull();
        c2.HierarchicalParent.Should().BeNull();
        p.Children.Should().Equal(c);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    [Trait("Conformance", "HIER-043")]
    public void HIER_043_Node_Of_An_Earlier_Subtree_Is_Already_Attached(bool childFirst)
    {
        var root = new Node("root");
        var p = new Node("p");
        var c = new Node("c");
        p.AddChild(c);

        var result = Attach(root, childFirst ? [c, p] : [p, c]);

        result.Added.Should().Equal(p);
        result.Duplicates.Should().BeEmpty();
        result.Rejections.Should().ContainSingle();
        result.Rejections[0].Item.Should().BeSameAs(c);
        result.Rejections[0].Reason.Should().Be(BatchAttachRejectionReason.AlreadyAttached);
        c.HierarchicalParent.Should().BeSameAs(p);
        p.Children.Should().Equal(c);
    }

    [Fact]
    [Trait("Conformance", "HIER-043")]
    public void HIER_043_Duplicate_Key_Inside_One_Subtree_Rejects_The_Candidate()
    {
        var root = new Node("root");
        var p = new Node("p");
        var d1 = new Node("d");
        var d2 = new Node("d");
        p.AddChild(d1);
        p.AddChild(d2);

        var result = Attach(root, [p]);

        result.Added.Should().BeEmpty();
        result.Duplicates.Should().Equal(p);
        result.Rejections.Should().ContainSingle();
        result.Rejections[0].Item.Should().BeSameAs(p);
        result.Rejections[0].Reason.Should().Be(BatchAttachRejectionReason.DuplicateBatchKey);
        p.HierarchicalParent.Should().BeNull();
        p.Children.Should().Equal(d1, d2);
    }

    [Fact]
    [Trait("Conformance", "HIER-043")]
    public void HIER_043_Descendant_Selector_Failure_Keeps_A_Parked_Candidate_Parked()
    {
        static BatchAttachResult<Node> AttachFailing(Node root, IEnumerable<Node> items) =>
            root.AttachMany(
                items,
                node => node.Model.Key == "bad"
                    ? throw new InvalidOperationException("keyOf failed")
                    : node.Model.Key,
                node => node.Model.ParentKey is null
                    ? BatchParentKey<string>.Root
                    : BatchParentKey<string>.For(node.Model.ParentKey),
                MissingParentPolicy.Park);
        var root = new Node("root");
        var p = new Node("p", "m");
        var parked = AttachFailing(root, [p]);
        parked.Orphans.Should().Equal(p);
        root.ParkedAttachCount.Should().Be(1);
        p.AddChild(new Node("bad"));

        var result = AttachFailing(root, []);

        result.Added.Should().BeEmpty();
        result.Duplicates.Should().BeEmpty();
        result.Rejections.Should().ContainSingle();
        result.Rejections[0].Item.Should().BeSameAs(p);
        result.Rejections[0].Reason.Should().Be(BatchAttachRejectionReason.SelectorFailed);
        root.ParkedAttachCount.Should().Be(1);
        p.HierarchicalParent.Should().BeNull();
    }

    [Fact]
    [Trait("Conformance", "HIER-044")]
    public void HIER_044_Factory_Children_Join_The_Index_Only_In_The_Next_Batch()
    {
        var root = new Node("root");
        var f = new Node("f");
        var lazy = new Node("L", factory: _ => [f]);
        root.AddChild(lazy);
        var y = new Node("y", "L");
        var z = new Node("z", "f");

        var first = Attach(root, [y, z], MissingParentPolicy.Park);

        first.Added.Should().Equal(y);
        lazy.Children.Should().Equal(f, y);
        first.Orphans.Should().Equal(z);
        first.Rejections.Should().ContainSingle();
        first.Rejections[0].Item.Should().BeSameAs(z);
        first.Rejections[0].Reason.Should().Be(BatchAttachRejectionReason.MissingParent);
        root.ParkedAttachCount.Should().Be(1);

        var second = Attach(root, []);

        second.Added.Should().Equal(z);
        second.Rejections.Should().BeEmpty();
        z.HierarchicalParent.Should().BeSameAs(f);
        root.ParkedAttachCount.Should().Be(0);
    }
}
