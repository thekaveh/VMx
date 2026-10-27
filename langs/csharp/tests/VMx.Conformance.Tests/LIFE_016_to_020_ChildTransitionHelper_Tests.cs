using System.Collections.Concurrent;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// LIFE-016..LIFE-020 — the supported child-transition helper
/// (<c>CompleteLifecycleHookAfter(TransitionChildrenAsync(...))</c>) and
/// depth-first member disposal (<c>OwnMember</c>) for a leaf view-model
/// subclassed outside the library. See spec/02 §6.1 and §7.1 (ADR-0162).
/// </summary>
public class LIFE_016_to_020_ChildTransitionHelper_Tests
{
    /// <summary>A consumer leaf VM that drives its members through the helper.</summary>
    private sealed class LeafVM(string name, IMessageHub hub, IDispatcher dispatcher)
        : ComponentVMBase(name, hub, dispatcher)
    {
        public IReadOnlyList<IComponentVM> ConstructMembers { get; set; } = [];
        public IReadOnlyList<IComponentVM> DestructMembers { get; set; } = [];
        public Action? After { get; set; }

        public override ViewModelType Type => ViewModelType.Component;

        public T Member<T>(T member) where T : IComponentVM => OwnMember(member);

        protected override void OnConstruct()
            => CompleteLifecycleHookAfter(TransitionChildrenAsync(ConstructMembers, construct: true, After));

        protected override void OnDestruct()
            => CompleteLifecycleHookAfter(TransitionChildrenAsync(DestructMembers, construct: false));
    }

    /// <summary>A member whose disposal hook raises.</summary>
    private sealed class FailingDisposeVM(string name, IMessageHub hub, Exception failure)
        : ComponentVMBase(name, hub, NullDispatcher.Instance)
    {
        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnDispose() => throw failure;
    }

    private static ComponentVM Leaf(string name, IMessageHub hub, IDispatcher? dispatcher = null,
        bool background = false, Action? onConstruct = null)
    {
        var builder = ComponentVM.Builder()
            .Name(name)
            .Services(hub, dispatcher ?? NullDispatcher.Instance)
            .Background(background);
        if (onConstruct is not null) builder = builder.OnConstruct(onConstruct);
        return builder.Build();
    }

    private static ConcurrentQueue<string> RecordStatuses(TestHub hub, params ConstructionStatus[] statuses)
    {
        var recorded = new ConcurrentQueue<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is ConstructionStatusChangedMessage changed && statuses.Contains(changed.Status))
                recorded.Enqueue($"{changed.SenderName} {changed.Status}");
        });
        return recorded;
    }

    /// <summary>Runs the child's background hook and its marshalled terminal status.</summary>
    private static void Drain(TestDispatcher dispatcher)
    {
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        dispatcher.ForegroundScheduler.AdvanceBy(1);
    }

    // LIFE-016 — the helper waits for a background child, then runs the next
    // child and `after` before the parent publishes Constructed.
    [Fact, Trait("Conformance", "LIFE-016")]
    public async Task LIFE_016_Helper_Waits_For_A_Background_Child()
    {
        using var hub = new TestHub();
        var childDispatcher = new TestDispatcher();
        var recorded = RecordStatuses(hub, ConstructionStatus.Constructed);
        var a = Leaf("a", hub, childDispatcher, background: true);
        var b = Leaf("b", hub);
        var afterRuns = 0;
        var parent = new LeafVM("parent", hub, NullDispatcher.Instance)
        {
            ConstructMembers = [a, b],
            After = () =>
            {
                Interlocked.Increment(ref afterRuns);
                recorded.Enqueue("after");
            },
        };

        var construct = parent.ConstructAsync();

        parent.Status.Should().Be(ConstructionStatus.Constructing);
        a.Status.Should().Be(ConstructionStatus.Constructing);
        b.Status.Should().Be(ConstructionStatus.Destructed);
        Volatile.Read(ref afterRuns).Should().Be(0);

        Drain(childDispatcher);
        await construct.WaitAsync(Liveness.HangGuard);

        a.Status.Should().Be(ConstructionStatus.Constructed);
        b.Status.Should().Be(ConstructionStatus.Constructed);
        parent.Status.Should().Be(ConstructionStatus.Constructed);
        Volatile.Read(ref afterRuns).Should().Be(1);
        recorded.Should().Equal("a Constructed", "b Constructed", "after", "parent Constructed");
    }

    // LIFE-017 — a failing child surfaces from construct(), rolls the parent
    // back, keeps the already-constructed sibling, and never starts the rest.
    [Fact, Trait("Conformance", "LIFE-017")]
    public void LIFE_017_Child_Failure_Rolls_The_Parent_Back()
    {
        using var hub = new TestHub();
        var failure = new InvalidOperationException("b construct failed");
        var a = Leaf("a", hub);
        var b = Leaf("b", hub, onConstruct: () => throw failure);
        var cHookRuns = 0;
        var c = Leaf("c", hub, onConstruct: () => cHookRuns++);
        var parent = new LeafVM("parent", hub, NullDispatcher.Instance) { ConstructMembers = [a, b, c] };
        var recorded = RecordStatuses(hub, ConstructionStatus.Constructing);

        Assert.Same(failure, Assert.Throws<InvalidOperationException>(parent.Construct));

        recorded.Should().NotContain("c Constructing", "the helper never started c");
        cHookRuns.Should().Be(0);

        parent.Status.Should().Be(ConstructionStatus.Destructed);
        a.Status.Should().Be(ConstructionStatus.Constructed);
        b.Status.Should().Be(ConstructionStatus.Destructed);
        c.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // LIFE-018 — registered members are disposed in registration order, each
    // depth-first, before the parent publishes Disposed.
    [Fact, Trait("Conformance", "LIFE-018")]
    public void LIFE_018_Members_Are_Disposed_Depth_First_Before_The_Parent()
    {
        using var hub = new TestHub();
        var grandchild = Leaf("first-child", hub);
        var first = CompositeVM<IComponentVM>.Builder()
            .Name("first")
            .Services(hub, NullDispatcher.Instance)
            .Children(() => [grandchild])
            .Build();
        var parent = new LeafVM("parent", hub, NullDispatcher.Instance);
        var second = Leaf("second", hub);
        parent.Member(first);
        parent.Member(second);
        parent.ConstructMembers = [first, second];
        parent.Construct();
        parent.Status.Should().Be(ConstructionStatus.Constructed);
        grandchild.Status.Should().Be(ConstructionStatus.Constructed);
        var disposed = RecordStatuses(hub, ConstructionStatus.Disposed);

        parent.Dispose();

        disposed.Should().Equal(
            "first-child Disposed", "first Disposed", "second Disposed", "parent Disposed");
    }

    [Fact, Trait("Conformance", "LIFE-018")]
    public void LIFE_018_A_Failing_Member_Does_Not_Strand_The_Rest()
    {
        using var hub = new TestHub();
        var failure = new InvalidOperationException("first member dispose failed");
        var parent = new LeafVM("parent", hub, NullDispatcher.Instance);
        var first = parent.Member(new FailingDisposeVM("first", hub, failure));
        var second = parent.Member(Leaf("second", hub));
        parent.Construct();

        Assert.Same(failure, Assert.Throws<InvalidOperationException>(parent.Dispose));

        first.Status.Should().Be(ConstructionStatus.Disposed);
        second.Status.Should().Be(ConstructionStatus.Disposed);
        parent.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact, Trait("Conformance", "LIFE-018")]
    public void LIFE_018_A_Member_Registered_After_Disposed_Is_Disposed_At_Once()
    {
        using var hub = new TestHub();
        var parent = new LeafVM("parent", hub, NullDispatcher.Instance);
        parent.Dispose();
        var late = Leaf("late", hub);

        parent.Member(late).Should().BeSameAs(late);

        late.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // LIFE-019 — the helper destructs in the caller's order, one child at a time.
    [Fact, Trait("Conformance", "LIFE-019")]
    public void LIFE_019_Helper_Destructs_In_The_Order_The_Caller_Passes()
    {
        using var hub = new TestHub();
        var a = Leaf("a", hub);
        var b = Leaf("b", hub);
        var c = Leaf("c", hub);
        var parent = new LeafVM("parent", hub, NullDispatcher.Instance)
        {
            ConstructMembers = [a, b, c],
            DestructMembers = [c, b, a],
        };
        parent.Construct();
        var recorded = RecordStatuses(hub, ConstructionStatus.Destructing, ConstructionStatus.Destructed);

        parent.Destruct();

        recorded.Should().Equal(
            "parent Destructing",
            "c Destructing", "c Destructed",
            "b Destructing", "b Destructed",
            "a Destructing", "a Destructed",
            "parent Destructed");
    }

    // LIFE-020 — a child already Constructing is joined, not restarted.
    [Fact, Trait("Conformance", "LIFE-020")]
    public async Task LIFE_020_Helper_Joins_A_Child_Already_In_Transit()
    {
        using var hub = new TestHub();
        var childDispatcher = new TestDispatcher();
        var hookRuns = 0;
        var a = Leaf("a", hub, childDispatcher, background: true,
            onConstruct: () => Interlocked.Increment(ref hookRuns));
        var parent = new LeafVM("parent", hub, NullDispatcher.Instance) { ConstructMembers = [a] };
        a.Construct();
        a.Status.Should().Be(ConstructionStatus.Constructing);
        var recorded = RecordStatuses(hub, ConstructionStatus.Constructed);

        var construct = parent.ConstructAsync();

        parent.Status.Should().Be(ConstructionStatus.Constructing);
        Drain(childDispatcher);
        await construct.WaitAsync(Liveness.HangGuard);

        a.Status.Should().Be(ConstructionStatus.Constructed);
        parent.Status.Should().Be(ConstructionStatus.Constructed);
        Volatile.Read(ref hookRuns).Should().Be(1);
        recorded.Should().Equal("a Constructed", "parent Constructed");
    }
}
