using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// The container construct walk counts members only (spec/06 §5.1, spec/07
/// §4, ADR-0186): COMP-047 and GRP-015. The walk checks membership before it
/// starts or joins a child, and again after the child settles. A child that a
/// removal or a failed add takes out during the walk does not change the
/// container, which still reaches Constructed.
/// </summary>
public class COMP_047_GRP_015_ConstructWalkMembership_Tests
{
    /// <summary>Queues background work; the foreground runs inline.</summary>
    private sealed class QueueDispatcher : IDispatcher, IScheduler
    {
        private readonly object _gate = new();
        private readonly List<Action> _work = new();

        public IScheduler Foreground => ImmediateScheduler.Instance;
        public IScheduler Background => this;
        public DateTimeOffset Now => DateTimeOffset.UtcNow;

        public IDisposable Schedule<TState>(TState state, Func<IScheduler, TState, IDisposable> action)
        {
            lock (_gate) _work.Add(() => action(this, state));
            return Disposable.Empty;
        }

        public IDisposable Schedule<TState>(
            TState state, TimeSpan dueTime, Func<IScheduler, TState, IDisposable> action)
            => Schedule(state, action);

        public IDisposable Schedule<TState>(
            TState state, DateTimeOffset dueTime, Func<IScheduler, TState, IDisposable> action)
            => Schedule(state, action);

        public void RunFirst() => Run(first: true);

        public void RunLast() => Run(first: false);

        public void RunAll()
        {
            while (true)
            {
                lock (_gate)
                {
                    if (_work.Count == 0) return;
                }
                RunFirst();
            }
        }

        private void Run(bool first)
        {
            Action work;
            lock (_gate)
            {
                work = first ? _work[0] : _work[^1];
                _work.Remove(work);
            }
            // A failing background hook rethrows here after its rollback.
            try { work(); }
            catch (InvalidOperationException) { }
        }
    }

    private sealed record Rig(
        QueueDispatcher Dispatcher,
        TestHub Hub,
        IComponentVM Root,
        Action<ComponentVM> Add,
        Func<ComponentVM, bool> Remove,
        Func<IReadOnlyList<ComponentVM>> Snapshot,
        LateChildStarts LateStarts);

    private static Rig Create(string kind)
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        if (kind == "composite")
        {
            var composite = CompositeVM<ComponentVM>.Builder()
                .Name("p").Services(hub, dispatcher)
                .Children(() => Array.Empty<ComponentVM>())
                .AutoConstructOnAdd(true).Build();
            return new Rig(dispatcher, hub, composite, composite.Add, composite.Remove, composite.Snapshot,
                composite.LateStartsForTesting);
        }
        var group = GroupVM<ComponentVM>.Builder()
            .Name("g").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM>())
            .AutoConstructOnAdd(true).Build();
        return new Rig(dispatcher, hub, group, group.Add, group.Remove, group.Snapshot,
            group.LateStartsForTesting);
    }

    private static ComponentVM Child(Rig rig, string name, bool background, Action? onConstruct = null)
    {
        var builder = ComponentVM.Builder().Name(name).Services(rig.Hub, rig.Dispatcher).Background(background);
        if (onConstruct is not null) builder = builder.OnConstruct(onConstruct);
        return builder.Build();
    }

    private static Action Failing(string name, Action? counted = null) => () =>
    {
        counted?.Invoke();
        throw new InvalidOperationException($"{name} failed");
    };

    private static void ShouldConstruct(Rig rig, Task construct)
    {
        construct.Wait(Liveness.HangGuard).Should().BeTrue("the container's construct completes");
        construct.IsCompletedSuccessfully.Should().BeTrue("a removed child does not fail the container");
        rig.Root.Status.Should().Be(ConstructionStatus.Constructed);
    }

    private static void ShouldBeRemoved(Rig rig, ComponentVM child)
    {
        child.Status.Should().Be(ConstructionStatus.Destructed);
        rig.Snapshot().Should().NotContain(child);
        ((IComponentVMInternals)child).Parent.Should().BeNull();
    }

    // Case 1: a snapshot child removed before the walk reaches it is never started.
    private static void SnapshotChildRemovedBeforeTheWalkReachesIt(string kind)
    {
        var rig = Create(kind);
        var runs = 0;
        var anchor = Child(rig, "a", background: true);
        var s = Child(rig, "s", background: false, Failing("s", () => Interlocked.Increment(ref runs)));
        rig.Add(anchor);
        rig.Add(s);

        var construct = rig.Root.ConstructAsync();
        rig.Root.Status.Should().Be(ConstructionStatus.Constructing, "the walk waits on the anchor");
        rig.Remove(s).Should().BeTrue();
        rig.Dispatcher.RunAll();

        ShouldConstruct(rig, construct);
        ShouldBeRemoved(rig, s);
        Volatile.Read(ref runs).Should().Be(0, "the walk never starts a removed snapshot child");
        anchor.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // Case 2: a snapshot child removed while the walk waits on it is ignored.
    private static void SnapshotChildRemovedWhileTheWalkWaitsOnIt(string kind)
    {
        var rig = Create(kind);
        var a = Child(rig, "a", background: true, Failing("a"));
        rig.Add(a);

        var construct = rig.Root.ConstructAsync();
        a.Status.Should().Be(ConstructionStatus.Constructing);
        ((ComponentVMBase)a).LifecycleWaiterCountForTesting.Should().Be(1, "the walk waits on a");
        rig.Remove(a).Should().BeTrue();
        rig.Dispatcher.RunAll(); // a's hook fails after the removal

        ShouldConstruct(rig, construct);
        ShouldBeRemoved(rig, a);
    }

    // Case 3: a late child the walk joined, then removed while the walk waits on it.
    private static void LateChildRemovedWhileTheWalkWaitsOnIt(string kind)
    {
        var rig = Create(kind);
        var anchor = Child(rig, "a", background: true);
        rig.Add(anchor);
        var construct = rig.Root.ConstructAsync();
        var late = Child(rig, "l", background: true, Failing("l"));
        rig.Add(late);
        late.Status.Should().Be(ConstructionStatus.Constructing, "the add started the late child");

        rig.Dispatcher.RunFirst(); // the anchor settles; the walk joins the late child
        SpinWait.SpinUntil(
            () => ((ComponentVMBase)late).LifecycleWaiterCountForTesting == 1, Liveness.HangGuard)
            .Should().BeTrue("the walk joins the late child");
        rig.Remove(late).Should().BeTrue();
        rig.Dispatcher.RunAll(); // the late child's hook fails after the removal

        ShouldConstruct(rig, construct);
        ShouldBeRemoved(rig, late);
    }

    // Case 4: a late child removed before the walk reaches it is skipped.
    private static void LateChildRemovedBeforeTheWalkReachesIt(string kind)
    {
        var rig = Create(kind);
        var anchor = Child(rig, "a", background: true);
        rig.Add(anchor);
        var construct = rig.Root.ConstructAsync();
        var late = Child(rig, "l", background: true, Failing("l"));
        rig.Add(late);
        rig.Remove(late).Should().BeTrue();
        rig.Dispatcher.RunLast(); // the late child fails first
        rig.Dispatcher.RunAll(); // then the anchor settles

        ShouldConstruct(rig, construct);
        ShouldBeRemoved(rig, late);
    }

    // A late child whose own add fails is undone; the container still constructs.
    // The walk waits on the add's start attempt while the child's hook fails.
    private static void FailedLateAddIsUndone(string kind)
    {
        var rig = Create(kind);
        var anchor = Child(rig, "a", background: true);
        rig.Add(anchor);
        var construct = rig.Root.ConstructAsync();
        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        using var walkWaiting = new ManualResetEventSlim();
        var failing = Child(rig, "f", background: false, Failing("f", () =>
        {
            entered.Set();
            release.Wait(Liveness.HangGuard).Should().BeTrue("the test releases the hook");
        }));
        rig.LateStarts.ProbeForTesting = (child, stage) =>
        {
            if (ReferenceEquals(child, failing) && stage == LateChildStage.WalkWaitingOnAdd) walkWaiting.Set();
        };
        Exception? addError = null;
        var adder = new Thread(() =>
        {
            try { rig.Add(failing); }
            catch (Exception error) { addError = error; }
        })
        { IsBackground = true };
        adder.Start();
        try
        {
            entered.Wait(Liveness.HangGuard).Should().BeTrue("the add starts the late child");
            rig.Dispatcher.RunFirst(); // the anchor settles; the walk reaches the late child
            walkWaiting.Wait(Liveness.HangGuard).Should().BeTrue("the walk waits on the add's attempt");
            rig.Root.Status.Should().Be(ConstructionStatus.Constructing);
        }
        finally
        {
            release.Set(); // the late child's hook fails now
            adder.Join(Liveness.HangGuard).Should().BeTrue("the failed add completes");
        }
        addError.Should().BeOfType<InvalidOperationException>("the add's own construct failed");
        rig.Snapshot().Should().NotContain(failing, "the failed add is undone");
        rig.Dispatcher.RunAll();

        ShouldConstruct(rig, construct);
        ShouldBeRemoved(rig, failing);
    }

    [Fact]
    [Trait("Conformance", "COMP-047")]
    public void Composite_Snapshot_Child_Removed_Before_The_Walk_Reaches_It_Is_Never_Started()
        => SnapshotChildRemovedBeforeTheWalkReachesIt("composite");

    [Fact]
    [Trait("Conformance", "COMP-047")]
    public void Composite_Snapshot_Child_Removed_While_The_Walk_Waits_On_It_Is_Ignored()
        => SnapshotChildRemovedWhileTheWalkWaitsOnIt("composite");

    [Fact]
    [Trait("Conformance", "COMP-047")]
    public void Composite_Late_Child_Removed_While_The_Walk_Waits_On_It_Is_Ignored()
        => LateChildRemovedWhileTheWalkWaitsOnIt("composite");

    [Fact]
    [Trait("Conformance", "COMP-047")]
    public void Composite_Late_Child_Removed_Before_The_Walk_Reaches_It_Is_Skipped()
        => LateChildRemovedBeforeTheWalkReachesIt("composite");

    [Fact]
    [Trait("Conformance", "COMP-047")]
    public void Composite_Failed_Late_Add_Is_Undone_And_The_Composite_Constructs()
        => FailedLateAddIsUndone("composite");

    [Fact]
    [Trait("Conformance", "GRP-015")]
    public void Group_Snapshot_Child_Removed_Before_The_Walk_Reaches_It_Is_Never_Started()
        => SnapshotChildRemovedBeforeTheWalkReachesIt("group");

    [Fact]
    [Trait("Conformance", "GRP-015")]
    public void Group_Snapshot_Child_Removed_While_The_Walk_Waits_On_It_Is_Ignored()
        => SnapshotChildRemovedWhileTheWalkWaitsOnIt("group");

    [Fact]
    [Trait("Conformance", "GRP-015")]
    public void Group_Late_Child_Removed_While_The_Walk_Waits_On_It_Is_Ignored()
        => LateChildRemovedWhileTheWalkWaitsOnIt("group");

    [Fact]
    [Trait("Conformance", "GRP-015")]
    public void Group_Late_Child_Removed_Before_The_Walk_Reaches_It_Is_Skipped()
        => LateChildRemovedBeforeTheWalkReachesIt("group");

    [Fact]
    [Trait("Conformance", "GRP-015")]
    public void Group_Failed_Late_Add_Is_Undone_And_The_Group_Constructs()
        => FailedLateAddIsUndone("group");
}
