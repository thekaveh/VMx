using System.Collections.Specialized;
using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using static VMx.Tree.Tree;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for <see cref="VMx.Composites.CompositeVMBase{VM}.BatchUpdate"/>
/// (COMP-012, COMP-013, GRP-005, GRP-006) and the <c>VMx.Tree</c> utilities
/// (UTIL-001..003). See spec/06-composite-vm.md, spec/07-group-vm.md,
/// spec/13-tree-utilities.md, and spec/12-conformance.md.
/// </summary>
public class BatchUpdateAndTreeUtilitiesConformanceTests
{
    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (TestHub hub, TestDispatcher dispatcher) MakeServices()
        => (new TestHub(), new TestDispatcher());

    private static ComponentVM<string> MakeChild(TestHub hub, TestDispatcher dispatcher, string name = "child")
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, dispatcher).Model("m").Build();

    private static CompositeVM<ComponentVM<string>> MakeComposite(
        TestHub hub, TestDispatcher dispatcher,
        string name = "root",
        bool autoConstructOnAdd = false)
        => CompositeVM<ComponentVM<string>>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .AutoConstructOnAdd(autoConstructOnAdd)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();

    private static GroupVM<ComponentVM<string>> MakeGroup(
        TestHub hub, TestDispatcher dispatcher,
        string name = "root",
        bool autoConstructOnAdd = false)
        => GroupVM<ComponentVM<string>>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .AutoConstructOnAdd(autoConstructOnAdd)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();

    // ── COMP-012 — AutoConstructOnAdd(true) auto-constructs late children ────

    /// <summary>
    /// COMP-012: A CompositeVM built with AutoConstructOnAdd(true) must call
    /// construct() on any child added via Add after the composite is Constructed,
    /// completing the transition to Constructed BEFORE CollectionChanged fires.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-012")]
    public void COMP_012_AutoConstructOnAdd_Constructs_Child_Before_CollectionChanged()
    {
        var (hub, dispatcher) = MakeServices();
        var composite = MakeComposite(hub, dispatcher, autoConstructOnAdd: true);
        composite.Construct();

        var child = MakeChild(hub, dispatcher);
        child.Status.Should().Be(ConstructionStatus.Destructed,
            "child must start Destructed");

        ConstructionStatus? statusAtEvent = null;
        composite.CollectionChanged += (_, e) =>
        {
            if (e.Action == NotifyCollectionChangedAction.Add)
                statusAtEvent = child.Status;
        };

        composite.Add(child);

        statusAtEvent.Should().Be(ConstructionStatus.Constructed,
            "child must be Constructed before the CollectionChanged(Add) event fires");
        child.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── COMP-013 — BatchUpdate suppresses events and emits one Reset ─────────

    /// <summary>
    /// COMP-013: BatchUpdate() suppresses per-mutation CollectionChanged events.
    /// A single Reset is emitted when the outermost batch is disposed.
    /// No events are raised from within the batch.
    /// </summary>
    [Fact, Trait("Conformance", "COMP-013")]
    public void COMP_013_BatchUpdate_Suppresses_Events_Emits_One_Reset()
    {
        var (hub, dispatcher) = MakeServices();
        var composite = MakeComposite(hub, dispatcher);
        composite.Construct();

        var c1 = MakeChild(hub, dispatcher, "c1");
        var c2 = MakeChild(hub, dispatcher, "c2");
        var c3 = MakeChild(hub, dispatcher, "c3");
        c1.Construct();
        c2.Construct();
        c3.Construct();

        var events = new List<NotifyCollectionChangedAction>();
        composite.CollectionChanged += (_, e) => events.Add(e.Action);

        using (composite.BatchUpdate())
        {
            composite.Add(c1);
            composite.Add(c2);
            composite.Add(c3);
            composite.Remove(c2);

            // No events should have been raised yet.
            events.Should().BeEmpty("no events may fire while a batch is open");
        }

        // After the batch closes exactly one Reset must have fired.
        events.Should().ContainSingle()
            .Which.Should().Be(NotifyCollectionChangedAction.Reset,
                "the outermost batch dispose must fire exactly one Reset");

        // The collection must reflect post-batch state.
        composite.Count.Should().Be(2);
        composite.Should().Contain(c1);
        composite.Should().Contain(c3);
    }

    // ── GRP-005 — AutoConstructOnAdd(true) auto-constructs late children ────

    /// <summary>
    /// GRP-005: A GroupVM built with AutoConstructOnAdd(true) must call
    /// construct() on any child added via Add after the group is Constructed,
    /// completing the transition BEFORE CollectionChanged fires.
    /// </summary>
    [Fact, Trait("Conformance", "GRP-005")]
    public void GRP_005_AutoConstructOnAdd_Constructs_Child_Before_CollectionChanged()
    {
        var (hub, dispatcher) = MakeServices();
        var group = MakeGroup(hub, dispatcher, autoConstructOnAdd: true);
        group.Construct();

        var child = MakeChild(hub, dispatcher);
        child.Status.Should().Be(ConstructionStatus.Destructed,
            "child must start Destructed");

        ConstructionStatus? statusAtEvent = null;
        group.CollectionChanged += (_, e) =>
        {
            if (e.Action == NotifyCollectionChangedAction.Add)
                statusAtEvent = child.Status;
        };

        group.Add(child);

        statusAtEvent.Should().Be(ConstructionStatus.Constructed,
            "child must be Constructed before the CollectionChanged(Add) event fires");
        child.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── GRP-006 — BatchUpdate suppresses events and emits one Reset ──────────

    /// <summary>
    /// GRP-006: GroupVM.BatchUpdate() suppresses per-mutation CollectionChanged events.
    /// A single Reset is emitted when the outermost batch is disposed.
    /// </summary>
    [Fact, Trait("Conformance", "GRP-006")]
    public void GRP_006_BatchUpdate_Suppresses_Events_Emits_One_Reset()
    {
        var (hub, dispatcher) = MakeServices();
        var group = MakeGroup(hub, dispatcher);
        group.Construct();

        var c1 = MakeChild(hub, dispatcher, "c1");
        var c2 = MakeChild(hub, dispatcher, "c2");
        c1.Construct();
        c2.Construct();

        var events = new List<NotifyCollectionChangedAction>();
        group.CollectionChanged += (_, e) => events.Add(e.Action);

        using (group.BatchUpdate())
        {
            group.Add(c1);
            group.Add(c2);
            group.Remove(c1);

            events.Should().BeEmpty("no events may fire while a batch is open");
        }

        events.Should().ContainSingle()
            .Which.Should().Be(NotifyCollectionChangedAction.Reset,
                "the outermost batch dispose must fire exactly one Reset");

        group.Count.Should().Be(1);
        group.Should().Contain(c2);
    }

    // ── UTIL-001 — walk yields root then descendants in DFS pre-order ────────

    /// <summary>
    /// UTIL-001: Walk yields root then every descendant in DFS pre-order.
    /// Tree shape:
    ///   root (CompositeVM)
    ///     ├── a (ComponentVM)
    ///     └── b (CompositeVM)
    ///           ├── b1 (ComponentVM)
    ///           └── b2 (ComponentVM)
    /// Expected: [root, a, b, b1, b2]
    /// </summary>
    [Fact, Trait("Conformance", "UTIL-001")]
    public void UTIL_001_Walk_Yields_Root_Then_Descendants_In_DFS_PreOrder()
    {
        var (hub, dispatcher) = MakeServices();

        var b1 = MakeChild(hub, dispatcher, "b1");
        var b2 = MakeChild(hub, dispatcher, "b2");
        var a = MakeChild(hub, dispatcher, "a");

        var b = CompositeVM<ComponentVM<string>>.Builder()
            .Name("b").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        b.Add(b1);
        b.Add(b2);

        var root = CompositeVM<IComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher)
            .Children(() => Array.Empty<IComponentVM>())
            .Build();
        root.Add(a);
        root.Add(b);

        var walked = Walk(root).ToList();

        walked.Should().HaveCount(5);
        walked[0].Should().BeSameAs(root);
        walked[1].Should().BeSameAs(a);
        walked[2].Should().BeSameAs(b);
        walked[3].Should().BeSameAs(b1);
        walked[4].Should().BeSameAs(b2);
    }

    // ── UTIL-002 — walk skips empty aggregate slots ──────────────────────────

    /// <summary>
    /// UTIL-002: Walk skips null aggregate slots.
    /// Before construct(), all ComponentN slots are null — Walk yields only the aggregate itself.
    /// After construct(), populated slots appear; the walker never yields null entries.
    /// </summary>
    [Fact, Trait("Conformance", "UTIL-002")]
    public void UTIL_002_Walk_Skips_Empty_Aggregate_Slots()
    {
        var (hub, dispatcher) = MakeServices();

        var comp1 = MakeChild(hub, dispatcher, "c1");
        var comp2 = MakeChild(hub, dispatcher, "c2");

        var agg = AggregateVM2<
            ComponentVM<string>,
            ComponentVM<string>>.Builder()
            .Name("agg").Services(hub, dispatcher)
            .Component1(() => comp1)
            .Component2(() => comp2)
            .Build();

        // Pre-construct: both slots are null — walk must yield only the aggregate.
        var preWalked = Walk(agg).ToList();
        preWalked.Should().ContainSingle("before construct all component slots are null");
        preWalked[0].Should().BeSameAs(agg);
        preWalked.Should().NotContainNulls("null slots must be skipped");

        agg.Construct();

        // Post-construct: both slots populated — walk yields [agg, comp1, comp2].
        var postWalked = Walk(agg).ToList();
        postWalked.Should().NotContainNulls("null slots must always be skipped");
        postWalked.Should().HaveCount(3);
        postWalked[0].Should().BeSameAs(agg);
        postWalked[1].Should().BeSameAs(comp1);
        postWalked[2].Should().BeSameAs(comp2);
    }

    // ── UTIL-003 — find returns first matching node and short-circuits ────────

    /// <summary>
    /// UTIL-003: Find returns the first matching node and short-circuits —
    /// the predicate is invoked at most for [root, a, b, b1] and never for b2.
    /// Tree shape same as UTIL-001.
    /// </summary>
    [Fact, Trait("Conformance", "UTIL-003")]
    public void UTIL_003_Find_Returns_First_Match_And_Short_Circuits()
    {
        var (hub, dispatcher) = MakeServices();

        var b1 = MakeChild(hub, dispatcher, "b1");
        var b2 = MakeChild(hub, dispatcher, "b2");
        var a = MakeChild(hub, dispatcher, "a");

        var b = CompositeVM<ComponentVM<string>>.Builder()
            .Name("b").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        b.Add(b1);
        b.Add(b2);

        var root = CompositeVM<IComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher)
            .Children(() => Array.Empty<IComponentVM>())
            .Build();
        root.Add(a);
        root.Add(b);

        var visited = new List<string>();
        var result = Find(root, vm =>
        {
            visited.Add(vm.Name);
            return vm.Name == "b1";
        });

        result.Should().BeSameAs(b1, "Find must return the first node matching the predicate");
        visited.Should().NotContain("b2",
            "the predicate must not be invoked for nodes after the first match");
        visited.Should().ContainInOrder("root", "a", "b", "b1");
    }
}
