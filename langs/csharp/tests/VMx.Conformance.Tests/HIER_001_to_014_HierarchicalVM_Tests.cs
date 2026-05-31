using System.Reactive.Linq;
using FluentAssertions;
using VMx.Capabilities;
using VMx.Commands;
using VMx.Components;
using VMx.Hierarchical;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;
using TreeHelper = VMx.Tree.Tree;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: HIER-001..HIER-014 — HierarchicalVM recursive tree VM.
/// See spec/18-hierarchical-vm.md and ADR-0028.
/// </summary>
public class HIER_001_to_014_HierarchicalVM_Tests
{
    // ── Shared test doubles ──────────────────────────────────────────────────

    private sealed class MyModel
    {
        public string Value { get; }
        public MyModel(string value = "m") => Value = value;
    }

    /// <summary>Concrete subclass — proves the recursive constraint compiles.</summary>
    private sealed class MyNode : HierarchicalVM<MyModel, MyNode>
    {
        public override ViewModelType Type => ViewModelType.Component;

        public MyNode(
            MyModel model,
            Func<MyNode, IEnumerable<MyNode>> childrenFactory,
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

    private static MyNode LeafNode(
        string? name = null,
        TestHub? hub = null,
        TestDispatcher? dispatcher = null)
        => new(new MyModel(), _ => [], hub, dispatcher, name);

    private static MyNode NodeWithChildren(
        IEnumerable<MyNode> children,
        TestHub? hub = null,
        TestDispatcher? dispatcher = null,
        string? name = null,
        bool eagerChildren = false)
    {
        var childList = children.ToList();
        return new MyNode(new MyModel(), _ => childList, hub, dispatcher, name, eagerChildren);
    }

    // ── HIER-001 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-001: A concrete subclass with the recursive generic constraint
    /// compiles and constructs without errors.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-001")]
    public void HIER_001_Recursive_Generic_Constraint_Compiles()
    {
        // If this file compiles, the `where TVM : HierarchicalVM<TModel, TVM>` constraint is honored.
        var node = LeafNode();
        node.Should().NotBeNull();
        node.IsRoot.Should().BeTrue();
        node.Depth.Should().Be(0);
    }

    // ── HIER-002 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-002: HierarchicalParent is null for the root node and non-null for non-root nodes.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-002")]
    public void HIER_002_Parent_Null_For_Root_NonNull_For_Child()
    {
        var child = LeafNode();
        var root = NodeWithChildren([child]);

        // Force materialization.
        _ = root.Children;

        root.HierarchicalParent.Should().BeNull("root has no parent");
        child.HierarchicalParent.Should().BeSameAs(root, "child's parent is root");
    }

    // ── HIER-003 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-003: Depth is 0 for root, parent.Depth + 1 for each child level.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-003")]
    public void HIER_003_Depth_Derivation()
    {
        var grandchild = LeafNode();
        var child = NodeWithChildren([grandchild]);
        var root = NodeWithChildren([child]);

        // Force materialization top-down.
        _ = root.Children;
        _ = child.Children;

        root.Depth.Should().Be(0);
        child.Depth.Should().Be(1);
        grandchild.Depth.Should().Be(2);
    }

    // ── HIER-004 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-004: Path returns root-first snapshot; same reference is returned on
    /// repeated calls (cached); path is recomputed after a parent change.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-004")]
    public void HIER_004_Path_Materialization_And_Cache()
    {
        var grandchild = LeafNode();
        var child = NodeWithChildren([grandchild]);
        var root = NodeWithChildren([child]);

        _ = root.Children;
        _ = child.Children;

        // 1. Path is root → child → grandchild.
        var path = grandchild.Path;
        path.Should().Equal(root, child, grandchild);

        // 2. Same object returned on second call (cached).
        grandchild.Path.Should().BeSameAs(path);

        // 3. After reparent, path cache is invalidated.
        var newRoot = LeafNode();
        newRoot.AddChild(grandchild); // grandchild gains a new parent
        grandchild.Path.Should().NotBeSameAs(path);
        grandchild.Path.Should().HaveCount(2); // newRoot → grandchild
        grandchild.Path[0].Should().BeSameAs(newRoot);
        grandchild.Path[1].Should().BeSameAs(grandchild);
    }

    // ── HIER-005 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-005: IsLeaf and IsRoot derivation match Parent/Children state.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-005")]
    public void HIER_005_IsLeaf_And_IsRoot_Derivation()
    {
        var leaf = LeafNode();
        var root = NodeWithChildren([leaf]);

        _ = root.Children;

        root.IsRoot.Should().BeTrue();
        root.IsLeaf.Should().BeFalse();

        leaf.IsRoot.Should().BeFalse();
        leaf.IsLeaf.Should().BeTrue();
    }

    // ── HIER-006 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-006: IsFirst and IsLast position predicates.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-006")]
    public void HIER_006_IsFirst_And_IsLast_Position_Predicates()
    {
        var c1 = LeafNode("c1");
        var c2 = LeafNode("c2");
        var c3 = LeafNode("c3");
        var root = NodeWithChildren([c1, c2, c3]);

        _ = root.Children;

        c1.IsFirst.Should().BeTrue();
        c1.IsLast.Should().BeFalse();

        c2.IsFirst.Should().BeFalse();
        c2.IsLast.Should().BeFalse();

        c3.IsFirst.Should().BeFalse();
        c3.IsLast.Should().BeTrue();

        // Root has no parent so both false.
        root.IsFirst.Should().BeFalse();
        root.IsLast.Should().BeFalse();
    }

    // ── HIER-007 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-007: Default lazy child loading — the children factory is NOT invoked
    /// until Children is first accessed.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-007")]
    public void HIER_007_Default_Lazy_Child_Loading()
    {
        var factoryInvoked = false;
        var root = new MyNode(
            new MyModel(),
            _ =>
            {
                factoryInvoked = true;
                return [LeafNode()];
            });

        // Factory must NOT have been called yet.
        factoryInvoked.Should().BeFalse("lazy — factory not called before Children is accessed");

        // First access triggers materialization.
        _ = root.Children;
        factoryInvoked.Should().BeTrue("factory called on first Children access");

        // Second access does NOT invoke factory again.
        factoryInvoked = false;
        _ = root.Children;
        factoryInvoked.Should().BeFalse("factory NOT called on subsequent accesses (cached)");
    }

    // ── HIER-008 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-008: Eager child loading — passing eagerChildren=true materializes the
    /// full subtree at Construct() time.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-008")]
    public void HIER_008_Eager_Child_Loading_Via_Constructor_Option()
    {
        var factoryInvoked = false;

        var leaf = LeafNode();
        var root = new MyNode(
            new MyModel(),
            _ =>
            {
                factoryInvoked = true;
                return [leaf];
            },
            eagerChildren: true);

        // Before Construct, factory still not called.
        factoryInvoked.Should().BeFalse("eager mode: factory not called before Construct()");

        root.Construct();

        // After Construct, factory must have been invoked (eager).
        factoryInvoked.Should().BeTrue("eager mode: factory invoked during Construct()");
        root.Children.Should().ContainSingle().Which.Should().BeSameAs(leaf);
    }

    // ── HIER-009 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-009: In eager mode, depth-first construction: deepest leaf reaches
    /// Constructed before the root does.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-009")]
    public void HIER_009_Depth_First_Construction_Order()
    {
        var order = new List<string>();

        // grandchild — records when it reaches Constructed.
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var grandchild = new MyNode(
            new MyModel(),
            _ => [],
            hub: hub,
            dispatcher: dispatcher,
            name: "grandchild",
            eagerChildren: true);

        var child = new MyNode(
            new MyModel(),
            _ => [grandchild],
            hub: hub,
            dispatcher: dispatcher,
            name: "child",
            eagerChildren: true);

        var root = new MyNode(
            new MyModel(),
            _ => [child],
            hub: hub,
            dispatcher: dispatcher,
            name: "root",
            eagerChildren: true);

        hub.Messages
           .OfType<ConstructionStatusChangedMessage>()
           .Where(m => m.Status == VMx.Lifecycle.ConstructionStatus.Constructed)
           .Subscribe(m => order.Add(m.SenderName));

        root.Construct();

        // Depth-first: grandchild → child → root.
        order.Should().Equal("grandchild", "child", "root");
    }

    // ── HIER-010 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-010: A PropertyChangedMessage for "HierarchicalParent" is published on
    /// the hub when the parent reference changes.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-010")]
    public void HIER_010_PropertyChangedMessage_On_Parent_Change()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();

        var child = new MyNode(new MyModel(), _ => [], hub: hub, dispatcher: dispatcher);
        var parent = new MyNode(new MyModel(), _ => [], hub: hub, dispatcher: dispatcher);

        var messages = new List<PropertyChangedMessage<IComponentVM>>();
        hub.Messages
           .OfType<PropertyChangedMessage<IComponentVM>>()
           .Subscribe(m => messages.Add(m));

        parent.AddChild(child);

        messages.Should().ContainSingle(
            m => m.PropertyName == nameof(HierarchicalVM<MyModel, MyNode>.HierarchicalParent) &&
                 ReferenceEquals(m.Sender, child),
            "AddChild must publish PropertyChangedMessage(HierarchicalParent) on the child");
    }

    // ── HIER-011 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-011: TreeStructureChangedMessage is published on add, remove, and reparent.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-011")]
    public void HIER_011_TreeStructureChangedMessage_On_Structural_Mutations()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var parent = new MyNode(new MyModel(), _ => [], hub: hub, dispatcher: dispatcher);
        var child = new MyNode(new MyModel(), _ => [], hub: hub, dispatcher: dispatcher);

        var messages = new List<TreeStructureChangedMessage>();
        hub.Messages.OfType<TreeStructureChangedMessage>().Subscribe(m => messages.Add(m));

        // Add
        parent.AddChild(child);
        messages.Should().ContainSingle(m =>
            m.Change == TreeStructureChange.Added &&
            ReferenceEquals(m.Source, parent) &&
            ReferenceEquals(m.Affected, child) &&
            m.Index == 0);

        messages.Clear();

        // Remove
        parent.RemoveChild(child);
        messages.Should().ContainSingle(m =>
            m.Change == TreeStructureChange.Removed &&
            ReferenceEquals(m.Source, parent) &&
            ReferenceEquals(m.Affected, child) &&
            m.Index == 0);

        messages.Clear();

        // Reparent: re-add to parent, then reparent to a new parent.
        parent.AddChild(child);
        messages.Clear();
        var newParent = new MyNode(new MyModel(), _ => [], hub: hub, dispatcher: dispatcher);
        newParent.ReparentChild(child);
        messages.Should().ContainSingle(m =>
            m.Change == TreeStructureChange.Reparented &&
            ReferenceEquals(m.Source, newParent) &&
            ReferenceEquals(m.Affected, child) &&
            m.Index == -1);
    }

    // ── HIER-012 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-012: Tree.WalkExpanded honors the lazy boundary: when a HierarchicalVM
    /// node is composed with ExpandableState and IsExpanded == false, its children
    /// are NOT yielded by WalkExpanded.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-012")]
    public void HIER_012_WalkExpanded_Honors_ExpandableState_Lazy_Boundary()
    {
        // Build a node with children but that also implements IExpandable via composition.
        var expandable = new ExpandableNode(new MyModel(), collapsed: true);
        _ = expandable.Children; // materialize

        var walked = TreeHelper.WalkExpanded(expandable).ToList();

        // The collapsed root itself is yielded; its children are NOT.
        walked.Should().ContainSingle().Which.Should().BeSameAs(expandable);

        // Expand and walk again.
        expandable.Expansion.Expand();
        var walkedExpanded = TreeHelper.WalkExpanded(expandable).ToList();
        walkedExpanded.Should().HaveCount(2); // root + 1 leaf child
    }

    // ── HIER-013 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-013: SearchableState composition filters the materialized portion
    /// of the tree (children).
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-013")]
    public void HIER_013_SearchableState_Composition_Filters_Materialized_Portion()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();

        var apple = new MyNode(new MyModel("apple"), _ => [], hub, dispatcher);
        var banana = new MyNode(new MyModel("banana"), _ => [], hub, dispatcher);
        var cherry = new MyNode(new MyModel("cherry"), _ => [], hub, dispatcher);
        var root = NodeWithChildren([apple, banana, cherry], hub, dispatcher);

        // Compose SearchableState filtering by model value.
        var search = new SearchableState<MyNode>(
            items: () => root.Children.Cast<MyNode>(),
            predicate: (node, term) => node.Model.Value.Contains(term, StringComparison.OrdinalIgnoreCase),
            debounce: TimeSpan.Zero);

        IReadOnlyList<MyNode> result = [];
        search.Filtered.Subscribe(r => result = r.ToList().AsReadOnly());

        search.SearchTerm = "an";
        search.Search(); // force immediate apply

        result.Should().ContainSingle(n => n.Model.Value == "banana");
    }

    // ── HIER-014 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// HIER-014: ModeledCrudCommands composition mutates the tree via AddChild /
    /// RemoveChild delegated through the command callbacks.
    /// </summary>
    [Fact]
    [Trait("Conformance", "HIER-014")]
    public void HIER_014_ModeledCrudCommands_Composition_Mutates_Tree()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var root = new MyNode(new MyModel(), _ => [], hub, dispatcher);
        MyNode? current = null;

        var crud = new ModeledCrudCommands<MyModel, MyNode>(
            current: () => current,
            createNew: () =>
            {
                var child = new MyNode(new MyModel("created"), _ => [], hub, dispatcher);
                root.AddChild(child);
                current = child;
            },
            updateCurrent: node => { /* no-op for this test */ },
            deleteCurrent: node =>
            {
                root.RemoveChild(node);
                current = null;
            });

        // Create
        crud.CreateNewCommand.Execute(null);
        root.Children.Should().ContainSingle("CreateNewCommand adds one child");
        current.Should().NotBeNull();

        // Delete
        crud.DeleteCurrentCommand.Execute(null);
        root.Children.Should().BeEmpty("DeleteCurrentCommand removes the child");
        current.Should().BeNull();

        crud.Dispose();
    }

    // ── Private test helpers ─────────────────────────────────────────────────

    /// <summary>
    /// Expandable node for HIER-012: HierarchicalVM + composed ExpandableState.
    /// HierarchicalVM does NOT auto-implement IExpandable (ADR-0028 §3.6).
    /// </summary>
    private sealed class ExpandableNode : HierarchicalVM<MyModel, ExpandableNode>, IExpandable
    {
        private static readonly TestHub SharedHub = new();
        private static readonly TestDispatcher SharedDispatcher = new();

        public override ViewModelType Type => ViewModelType.Component;
        public ExpandableState Expansion { get; }

        public ExpandableNode(MyModel model, bool collapsed = true)
            : base(
                model,
                _ => [new ExpandableNode(new MyModel("child"))],
                SharedHub,
                SharedDispatcher)
        {
            Expansion = new ExpandableState(initiallyExpanded: !collapsed);
        }

        private ExpandableNode(MyModel model)
            : base(model, _ => [], SharedHub, SharedDispatcher)
        {
            Expansion = new ExpandableState(initiallyExpanded: false);
        }

        public bool IsExpanded => Expansion.IsExpanded;
        public bool CanExpand() => Expansion.CanExpand();
        public void Expand() => Expansion.Expand();
    }
}
