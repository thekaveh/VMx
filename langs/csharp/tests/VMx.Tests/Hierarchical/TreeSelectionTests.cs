using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Hierarchical;

/// <summary>
/// Unit tests for <see cref="TreeSelection{TModel,TVM}"/> beyond the
/// HIER-033..HIER-040 conformance scenarios.
/// </summary>
public class TreeSelectionTests
{
    // ── Test doubles ─────────────────────────────────────────────────────────

    private sealed class Model
    {
    }

    private sealed class Node : HierarchicalVM<Model, Node>
    {
        public override ViewModelType Type => ViewModelType.Component;

        public Node(IMessageHub hub, Func<Node, IEnumerable<Node>>? childrenFactory = null, string? name = null)
            : base(new Model(), childrenFactory ?? (_ => []), hub, new TestDispatcher(), name)
        {
        }
    }

    /// <summary>Hub that counts its live subscriptions.</summary>
    private sealed class CountingHub : IMessageHub, IDisposable
    {
        private readonly Subject<IMessage> _subject = new();

        public int ActiveSubscriptions { get; private set; }

        public IObservable<IMessage> Messages => new Counted(this);

        public void Send<TMessage>(TMessage message) where TMessage : IMessage
            => _subject.OnNext(message);

        public void Dispose() => _subject.Dispose();

        private sealed class Counted(CountingHub hub) : IObservable<IMessage>
        {
            public IDisposable Subscribe(IObserver<IMessage> observer)
            {
                var inner = hub._subject.Subscribe(observer);
                hub.ActiveSubscriptions++;
                var released = false;
                return System.Reactive.Disposables.Disposable.Create(() =>
                {
                    if (released) return;
                    released = true;
                    hub.ActiveSubscriptions--;
                    inner.Dispose();
                });
            }
        }
    }

    /// <summary>A VM that owns a selection and forwards its changes (spec/14 rule 6).</summary>
    private sealed class OwnerVM : ComponentVMBase
    {
        private readonly TreeSelection<Model, Node> _selection;

        public OwnerVM(Node root, IMessageHub hub)
            : base(nameof(OwnerVM), hub, new TestDispatcher())
        {
            _selection = Own(new TreeSelection<Model, Node>(root));
            Own(_selection.CurrentChanged.Subscribe(_ => NotifyPropertyChanged(nameof(SelectedNode))));
        }

        public override ViewModelType Type => ViewModelType.Component;

        public TreeSelection<Model, Node> Selection => _selection;

        public Node? SelectedNode => _selection.Current;
    }

    private sealed class Tree
    {
        public Tree(IMessageHub? rootHub = null, IMessageHub? aHub = null, IMessageHub? bHub = null)
        {
            var hub = rootHub ?? new TestHub();
            AA = new Node(aHub ?? hub, name: "AA");
            A = new Node(aHub ?? hub, _ => [AA], "A");
            B = new Node(bHub ?? hub, name: "B");
            Root = new Node(hub, _ => [A, B], "Root");
            _ = Root.Children;
            _ = A.Children;
        }

        public Node Root { get; }
        public Node A { get; }
        public Node AA { get; }
        public Node B { get; }
    }

    private static List<Node?> Record(TreeSelection<Model, Node> selection)
    {
        var seen = new List<Node?>();
        selection.CurrentChanged.Subscribe(seen.Add);
        return seen;
    }

    // ── Membership ───────────────────────────────────────────────────────────

    [Fact]
    public void The_Root_Itself_Is_Selectable()
    {
        var tree = new Tree();
        using var selection = new TreeSelection<Model, Node>(tree.Root);

        selection.Select(tree.Root);

        selection.Current.Should().BeSameAs(tree.Root);
    }

    [Fact]
    public void A_Non_Structural_Root_Bounds_The_Selectable_Tree()
    {
        var tree = new Tree();
        using var selection = new TreeSelection<Model, Node>(tree.A);

        selection.CanSelect(tree.AA).Should().BeTrue();
        selection.CanSelect(tree.Root).Should().BeFalse();
        selection.CanSelect(tree.B).Should().BeFalse();
    }

    [Fact]
    public void Attaching_The_Root_Under_An_Outside_Parent_Keeps_The_Selection()
    {
        var tree = new Tree();
        var outside = new Node(new TestHub(), name: "Outside");
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        outside.AddChild(tree.Root);

        selection.Current.Should().BeSameAs(tree.AA);
        seen.Should().BeEmpty();
    }

    [Fact]
    public void Removing_A_Sibling_Keeps_The_Selection()
    {
        var tree = new Tree();
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        tree.Root.RemoveChild(tree.B);

        selection.Current.Should().BeSameAs(tree.AA);
        seen.Should().BeEmpty();
    }

    // ── Leaving the tree ─────────────────────────────────────────────────────

    [Fact]
    public void A_Move_Inside_Then_Removal_From_The_New_Location_Clears()
    {
        // B publishes on its own hub: only a re-watched path observes it.
        var tree = new Tree(bHub: new TestHub());
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        tree.B.AddChild(tree.A);
        seen.Should().BeEmpty();
        tree.Root.RemoveChild(tree.B);

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
    }

    [Fact]
    public void A_Move_Inside_Then_Disposal_Of_The_New_Ancestor_Clears()
    {
        // B's disposal is published only on B's hub, which the selection
        // watches only after it re-watched the new path.
        var tree = new Tree(bHub: new TestHub());
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        tree.B.AddChild(tree.A);
        tree.B.Dispose();

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
    }

    [Fact]
    public void Removing_An_Ancestor_That_Publishes_On_Another_Hub_Clears()
    {
        var tree = new Tree(aHub: new TestHub());
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        tree.Root.RemoveChild(tree.A);

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
    }

    [Fact]
    public void Invalidating_An_Ancestor_That_Publishes_On_Another_Hub_Clears()
    {
        var tree = new Tree(aHub: new TestHub());
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        tree.A.InvalidateChildren();

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
    }

    [Fact]
    public void InvalidateSubtree_On_The_Root_Clears()
    {
        var tree = new Tree();
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        tree.Root.InvalidateSubtree();

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
    }

    [Fact]
    public void Disposing_The_Root_Clears()
    {
        var tree = new Tree();
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        tree.Root.Dispose();

        selection.Current.Should().BeNull();
        seen.Should().Equal([null]);
        selection.CanSelect(tree.Root).Should().BeFalse();
    }

    [Fact]
    public void The_Default_MessageHub_Delivers_Leave_Events()
    {
        using var hub = new MessageHub();
        var tree = new Tree(rootHub: hub);
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        tree.AA.Dispose();
        selection.Current.Should().BeNull();
        selection.Select(tree.A);
        tree.Root.RemoveChild(tree.A);

        selection.Current.Should().BeNull();
        seen.Should().Equal(null, tree.A, null);
    }

    // ── Change stream ────────────────────────────────────────────────────────

    [Fact]
    public void A_Subscriber_May_Select_Re_Entrantly()
    {
        var tree = new Tree();
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = new List<Node?>();
        selection.CurrentChanged.Subscribe(node =>
        {
            seen.Add(node);
            if (node is null && seen.Count == 1) selection.Select(tree.B);
        });

        tree.Root.RemoveChild(tree.A);

        selection.Current.Should().BeSameAs(tree.B);
        seen.Should().Equal(null, tree.B);

        // The re-entrant selection is watched like any other.
        tree.Root.RemoveChild(tree.B);
        selection.Current.Should().BeNull();
        seen.Should().Equal(null, tree.B, null);
    }

    [Fact]
    public void An_Owner_Forwards_CurrentChanged_To_Its_Property_Notification()
    {
        var tree = new Tree();
        var ownerHub = new TestHub();
        var owner = new OwnerVM(tree.Root, ownerHub);
        var localChanges = new List<string?>();
        owner.PropertyChanged += (_, e) => localChanges.Add(e.PropertyName);
        var hubChanges = new List<string>();
        using var sub = ownerHub.Messages.Subscribe(message =>
        {
            if (message is IPropertyChangedMessage<IComponentVM> changed && ReferenceEquals(changed.SenderObject, owner))
                hubChanges.Add(changed.PropertyName);
        });

        owner.Selection.Select(tree.AA);
        owner.SelectedNode.Should().BeSameAs(tree.AA);
        tree.Root.RemoveChild(tree.A);
        owner.SelectedNode.Should().BeNull();

        localChanges.Should().Equal(nameof(OwnerVM.SelectedNode), nameof(OwnerVM.SelectedNode));
        hubChanges.Should().Equal(nameof(OwnerVM.SelectedNode), nameof(OwnerVM.SelectedNode));

        owner.Dispose();
        owner.Selection.CanSelect(tree.Root).Should().BeFalse("the owner disposes the helper it owns");
        tree.Root.Status.Should().NotBe(VMx.Lifecycle.ConstructionStatus.Disposed);
    }

    // ── Arguments ────────────────────────────────────────────────────────────

    [Fact]
    public void Null_Arguments_Are_Rejected()
    {
        var tree = new Tree();
        var construct = () => new TreeSelection<Model, Node>(null!);
        construct.Should().Throw<ArgumentNullException>().WithParameterName("root");

        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.CanSelect(null).Should().BeFalse();
        selection.Invoking(s => s.Select(null!)).Should().Throw<ArgumentNullException>().WithParameterName("node");

        selection.Dispose();
        selection.Invoking(s => s.Select(null!)).Should().NotThrow("a disposed selection is inert");
    }

    // ── Subscriptions ────────────────────────────────────────────────────────

    [Fact]
    public void One_Subscription_Per_Distinct_Hub_Is_Held_Only_While_A_Node_Is_Current()
    {
        var hub = new CountingHub();
        var otherHub = new CountingHub();
        var tree = new Tree(rootHub: hub, aHub: otherHub);
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        hub.ActiveSubscriptions.Should().Be(0);

        selection.Select(tree.AA);
        hub.ActiveSubscriptions.Should().Be(1);
        otherHub.ActiveSubscriptions.Should().Be(1);

        selection.Select(tree.B);
        hub.ActiveSubscriptions.Should().Be(1);
        otherHub.ActiveSubscriptions.Should().Be(0);

        selection.Clear();
        hub.ActiveSubscriptions.Should().Be(0);
    }

    [Fact]
    public void Dispose_Releases_The_Hub_Subscriptions()
    {
        var hub = new CountingHub();
        var tree = new Tree(rootHub: hub);
        var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        selection.Dispose();

        hub.ActiveSubscriptions.Should().Be(0);
        tree.Root.RemoveChild(tree.A);
        seen.Should().BeEmpty();
    }

    [Fact]
    public void A_Leave_Event_Releases_The_Hub_Subscriptions()
    {
        var hub = new CountingHub();
        var tree = new Tree(rootHub: hub);
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);

        tree.Root.RemoveChild(tree.A);

        selection.Current.Should().BeNull();
        hub.ActiveSubscriptions.Should().Be(0);
    }

    [Fact]
    public void Dispose_Runs_Every_Step_And_Rethrows_The_First_Failure()
    {
        var hub = new CountingHub();
        var tree = new Tree(rootHub: hub);
        var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var boom = new InvalidOperationException("boom");
        selection.CurrentChanged.Subscribe(_ => { }, () => throw boom);

        var act = () => selection.Dispose();

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(boom);
        hub.ActiveSubscriptions.Should().Be(0);
        selection.Invoking(s => s.CurrentChanged.Subscribe(_ => { }))
            .Should().Throw<ObjectDisposedException>("the step after the failing one still runs");
        selection.Invoking(s => s.Dispose()).Should().NotThrow("a second Dispose is a no-op");
    }

    [Fact]
    public void A_Rejected_Select_Keeps_The_Current_Watch()
    {
        var hub = new CountingHub();
        var tree = new Tree(rootHub: hub);
        using var selection = new TreeSelection<Model, Node>(tree.Root);
        selection.Select(tree.AA);
        var seen = Record(selection);

        selection.Invoking(s => s.Select(new Node(new TestHub())))
            .Should().Throw<InvalidOperationException>();
        tree.Root.RemoveChild(tree.A);

        seen.Should().Equal([null]);
    }
}
