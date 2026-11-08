using System.Collections.Concurrent;
using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Conformance.Tests;

/// <summary>
/// LIFE-021 — a lifecycle call during the inline dispose cascade fails. See
/// spec/02 §7.2 and ADR-0175. A <c>Construct()</c>, <c>Destruct()</c> or
/// <c>Reconstruct()</c> call (or its async form) that starts while a VM
/// disposes its children or members throws
/// <see cref="StatusTransitionException"/> for <c>Disposed</c> and publishes
/// nothing, and no status other than <c>Disposed</c> commits once the cascade
/// has started.
/// </summary>
public class LIFE_021_InlineDisposeCascade_Tests
{
    public enum Container
    {
        Composite,
        Group,
        Aggregate1,
    }

    public enum Operation
    {
        Construct,
        Destruct,
        Reconstruct,
        ConstructAsync,
        DestructAsync,
        ReconstructAsync,
    }

    /// <summary>A child or member whose dispose hook runs a test action.</summary>
    private sealed class HookedVM(string name, IMessageHub hub)
        : ComponentVMBase(name, hub, NullDispatcher.Instance)
    {
        public Action? DisposeHook { get; set; }

        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnDispose() => DisposeHook?.Invoke();
    }

    /// <summary>A leaf VM that owns members and counts its own hooks.</summary>
    private sealed class LeafVM(string name, IMessageHub hub, IDispatcher dispatcher, bool background = false)
        : ComponentVMBase(name, "", hub, dispatcher, null, null, background)
    {
        private int _hookRuns;
        public int HookRuns => Volatile.Read(ref _hookRuns);

        public override ViewModelType Type => ViewModelType.Component;

        public T Member<T>(T member) where T : IComponentVM => OwnMember(member);

        protected override void OnConstruct() => Interlocked.Increment(ref _hookRuns);

        protected override void OnDestruct() => Interlocked.Increment(ref _hookRuns);
    }

    private sealed class Box
    {
        public required IComponentVM Vm { get; init; }
        public required Func<HookedVM> Child { get; init; }
        public required Func<int> HookRuns { get; init; }
        public required Func<int> FactoryCalls { get; init; }
    }

    private static Box Build(Container kind, TestHub hub)
    {
        var hookRuns = 0;
        switch (kind)
        {
            case Container.Composite:
                {
                    var c1 = new HookedVM("c1", hub);
                    var composite = CompositeVM<IComponentVM>.Builder()
                        .Name("box").Services(hub, NullDispatcher.Instance)
                        .Children(() => Array.Empty<IComponentVM>())
                        .OnConstruct(() => Interlocked.Increment(ref hookRuns))
                        .OnDestruct(() => Interlocked.Increment(ref hookRuns))
                        .Build();
                    composite.Add(c1);
                    return new Box
                    {
                        Vm = composite,
                        Child = () => c1,
                        HookRuns = () => Volatile.Read(ref hookRuns),
                        FactoryCalls = () => 0,
                    };
                }
            case Container.Group:
                {
                    var c1 = new HookedVM("c1", hub);
                    var group = GroupVM<IComponentVM>.Builder()
                        .Name("box").Services(hub, NullDispatcher.Instance)
                        .Children(() => Array.Empty<IComponentVM>())
                        .OnConstruct(() => Interlocked.Increment(ref hookRuns))
                        .OnDestruct(() => Interlocked.Increment(ref hookRuns))
                        .Build();
                    group.Add(c1);
                    return new Box
                    {
                        Vm = group,
                        Child = () => c1,
                        HookRuns = () => Volatile.Read(ref hookRuns),
                        FactoryCalls = () => 0,
                    };
                }
            case Container.Aggregate1:
                {
                    var factoryCalls = 0;
                    var aggregate = AggregateVM1<HookedVM>.Builder()
                        .Name("box").Services(hub, NullDispatcher.Instance)
                        .Component1(() =>
                        {
                            var n = Interlocked.Increment(ref factoryCalls);
                            return new HookedVM(n == 1 ? "c1" : $"c{n}", hub);
                        })
                        .Build();
                    // Construct once so that c1 exists (LIFE-021 Given).
                    aggregate.Construct();
                    return new Box
                    {
                        Vm = aggregate,
                        Child = () => aggregate.Component1!,
                        // The aggregate's construct hook calls the slot factory.
                        HookRuns = () => Volatile.Read(ref factoryCalls),
                        FactoryCalls = () => Volatile.Read(ref factoryCalls),
                    };
                }
            default:
                throw new ArgumentOutOfRangeException(nameof(kind));
        }
    }

    private static void Invoke(IComponentVM vm, Operation operation)
    {
        // The async methods fail synchronously, as they do from Disposed.
        switch (operation)
        {
            case Operation.Construct: vm.Construct(); break;
            case Operation.Destruct: vm.Destruct(); break;
            case Operation.Reconstruct: vm.Reconstruct(); break;
            case Operation.ConstructAsync: _ = vm.ConstructAsync(); break;
            case Operation.DestructAsync: _ = vm.DestructAsync(); break;
            case Operation.ReconstructAsync: _ = vm.ReconstructAsync(); break;
            default: throw new ArgumentOutOfRangeException(nameof(operation));
        }
    }

    private static string OperationName(Operation operation) => operation switch
    {
        Operation.Construct or Operation.ConstructAsync => "construct",
        Operation.Destruct or Operation.DestructAsync => "destruct",
        _ => "reconstruct",
    };

    private static ConcurrentQueue<string> RecordStatuses(TestHub hub, string sender)
    {
        var recorded = new ConcurrentQueue<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is ConstructionStatusChangedMessage changed && changed.SenderName == sender)
                recorded.Enqueue(changed.Status.ToString());
        });
        return recorded;
    }

    private static void ShouldBeTheDisposedError(Exception? error, Operation operation)
    {
        var refusal = error.Should().BeOfType<StatusTransitionException>(
            "the call fails as it does on a Disposed VM (spec/02 §7.2)").Subject;
        refusal.CurrentStatus.Should().Be(ConstructionStatus.Disposed);
        refusal.AttemptedOperation.Should().Be(OperationName(operation));
    }

    private static Exception? OnAnotherThread(Action action)
    {
        var call = Task.Factory.StartNew(
            () => Record.Exception(action),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        call.Wait(HangGuard).Should().BeTrue("the refused call returns at once");
        return call.Result;
    }

    /// <summary>
    /// LIFE-021 part 1: a child dispose hook that calls a lifecycle method on
    /// its container during the container's inline dispose cascade gets the
    /// Disposed error. The container runs no hook, calls no slot factory and
    /// publishes only Disposed, and every child ends Disposed once. Rule 1
    /// covers every source: the hook also makes the call on another thread.
    /// </summary>
    [Theory, Trait("Conformance", "LIFE-021")]
    [MemberData(nameof(ContainerCases))]
    public void LIFE_021_Container_Call_During_Inline_Cascade_Fails(
        Container kind, ConstructionStatus start, Operation operation, bool fromAnotherThread)
    {
        using var hub = new TestHub();
        var box = Build(kind, hub);
        if (start == ConstructionStatus.Constructed) box.Vm.Construct();
        else box.Vm.Destruct();
        box.Vm.Status.Should().Be(start);
        var c1 = box.Child();
        var hooksBefore = box.HookRuns();
        var factoryBefore = box.FactoryCalls();
        Exception? recordedError = null;
        var hookCalls = 0;
        c1.DisposeHook = () =>
        {
            hookCalls++;
            recordedError = fromAnotherThread
                ? OnAnotherThread(() => Invoke(box.Vm, operation))
                : Record.Exception(() => Invoke(box.Vm, operation));
        };
        var boxStatuses = RecordStatuses(hub, "box");
        var childStatuses = RecordStatuses(hub, "c1");

        box.Vm.Dispose();

        hookCalls.Should().Be(1);
        ShouldBeTheDisposedError(recordedError, operation);
        // An aggregate's destruct hook calls no factory; the child statuses
        // below show that it did not run (it would destruct c1 first).
        box.HookRuns().Should().Be(hooksBefore, "no construct or destruct hook of the container runs");
        box.FactoryCalls().Should().Be(factoryBefore, "no slot factory runs again");
        boxStatuses.Should().Equal("Disposed");
        box.Vm.Status.Should().Be(ConstructionStatus.Disposed);
        c1.Status.Should().Be(ConstructionStatus.Disposed);
        box.Child().Should().BeSameAs(c1, "the container holds no new child or slot");
        childStatuses.Should().Equal("Disposed");
    }

    public static TheoryData<Container, ConstructionStatus, Operation, bool> ContainerCases()
    {
        var data = new TheoryData<Container, ConstructionStatus, Operation, bool>();
        foreach (var kind in Enum.GetValues<Container>())
        {
            foreach (var (start, operation) in new[]
                     {
                         (ConstructionStatus.Destructed, Operation.Construct),
                         (ConstructionStatus.Destructed, Operation.ConstructAsync),
                         (ConstructionStatus.Constructed, Operation.Destruct),
                         (ConstructionStatus.Constructed, Operation.DestructAsync),
                         // The refusal precedes the idempotent no-ops (Rule 2).
                         (ConstructionStatus.Constructed, Operation.Construct),
                         (ConstructionStatus.Constructed, Operation.ConstructAsync),
                         (ConstructionStatus.Destructed, Operation.Destruct),
                         (ConstructionStatus.Constructed, Operation.Reconstruct),
                         (ConstructionStatus.Constructed, Operation.ReconstructAsync),
                     })
                data.Add(kind, start, operation, false);
            // Rule 1 covers a call from another thread (decision (f)).
            data.Add(kind, ConstructionStatus.Destructed, Operation.Construct, true);
            data.Add(kind, ConstructionStatus.Constructed, Operation.Destruct, true);
            data.Add(kind, ConstructionStatus.Constructed, Operation.Reconstruct, true);
        }
        return data;
    }

    /// <summary>
    /// LIFE-021 part 2: a member dispose hook that calls construct() on its
    /// leaf during the member cascade gets the Disposed error, no leaf hook
    /// runs, and the leaf publishes only Disposed.
    /// </summary>
    [Theory, Trait("Conformance", "LIFE-021")]
    [InlineData(ConstructionStatus.Destructed, Operation.Construct)]
    [InlineData(ConstructionStatus.Constructed, Operation.Construct)]
    [InlineData(ConstructionStatus.Constructed, Operation.Destruct)]
    [InlineData(ConstructionStatus.Constructed, Operation.Reconstruct)]
    public void LIFE_021_Leaf_Call_From_Member_Dispose_Hook_Fails(
        ConstructionStatus start, Operation operation)
    {
        using var hub = new TestHub();
        var leaf = new LeafVM("leaf", hub, NullDispatcher.Instance);
        var member = leaf.Member(new HookedVM("m1", hub));
        if (start == ConstructionStatus.Constructed) leaf.Construct();
        var hooksBefore = leaf.HookRuns;
        Exception? recordedError = null;
        member.DisposeHook = () => recordedError = Record.Exception(() => Invoke(leaf, operation));
        var leafStatuses = RecordStatuses(hub, "leaf");

        leaf.Dispose();

        ShouldBeTheDisposedError(recordedError, operation);
        leaf.HookRuns.Should().Be(hooksBefore, "no leaf hook runs");
        leafStatuses.Should().Equal("Disposed");
        leaf.Status.Should().Be(ConstructionStatus.Disposed);
        member.Status.Should().Be(ConstructionStatus.Disposed);
    }

    /// <summary>
    /// LIFE-021 part 2: a background leaf whose construct hook ran and whose
    /// Constructed commit is queued on the foreground. Draining the foreground
    /// from the member's dispose hook publishes no Constructed: after its
    /// Constructing, the leaf publishes only Disposed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-021")]
    public async Task LIFE_021_Queued_Background_Commit_Drained_In_Member_Cascade_Is_Dropped()
    {
        using var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var leaf = new LeafVM("leaf", hub, dispatcher, background: true);
        var member = leaf.Member(new HookedVM("m1", hub));
        var leafStatuses = RecordStatuses(hub, "leaf");
        var construct = leaf.ConstructAsync();
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        leaf.HookRuns.Should().Be(1, "the construct hook ran; its commit is queued");
        leaf.Status.Should().Be(ConstructionStatus.Constructing);
        member.DisposeHook = () => dispatcher.ForegroundScheduler.AdvanceBy(1);

        leaf.Dispose();

        leafStatuses.Should().Equal("Constructing", "Disposed");
        leaf.Status.Should().Be(ConstructionStatus.Disposed);
        member.Status.Should().Be(ConstructionStatus.Disposed);
        await construct.WaitAsync(HangGuard);
        leaf.HasInFlightLifecycleForTesting.Should().BeFalse("the in-flight guard is cleared");
    }

    /// <summary>
    /// LIFE-021 (reconstruct, decision (b)): a Destructed subscriber that
    /// disposes the container ends reconstruct() after its destruct phase. No
    /// construct phase starts: no Constructing, no hook, no slot factory, and
    /// the call returns.
    /// </summary>
    [Theory, Trait("Conformance", "LIFE-021")]
    [InlineData(Container.Composite)]
    [InlineData(Container.Group)]
    [InlineData(Container.Aggregate1)]
    public void LIFE_021_Reconstruct_Starts_No_Construct_Phase_After_Cascade(Container kind)
    {
        using var hub = new TestHub();
        var box = Build(kind, hub);
        box.Vm.Construct();
        var c1 = box.Child();
        var factoryBefore = box.FactoryCalls();
        var boxStatuses = RecordStatuses(hub, "box");
        hub.Messages.Subscribe(message =>
        {
            if (message is ConstructionStatusChangedMessage { SenderName: "box", Status: ConstructionStatus.Destructed })
                box.Vm.Dispose();
        });

        Record.Exception(box.Vm.Reconstruct).Should().BeNull();

        boxStatuses.Should().Equal("Destructing", "Destructed", "Disposed");
        box.FactoryCalls().Should().Be(factoryBefore);
        box.Vm.Status.Should().Be(ConstructionStatus.Disposed);
        c1.Status.Should().Be(ConstructionStatus.Disposed);
    }

    /// <summary>
    /// LIFE-021 (reconstruct, decision (b), cross-thread): a Destructed
    /// subscriber starts a disposal on another thread and waits until its
    /// inline cascade has started. reconstruct() then starts no construct
    /// phase: no Constructing, no hook, no slot factory, and the call returns.
    /// </summary>
    [Theory, Trait("Conformance", "LIFE-021")]
    [InlineData(Container.Composite)]
    [InlineData(Container.Group)]
    [InlineData(Container.Aggregate1)]
    public async Task LIFE_021_Reconstruct_Starts_No_Construct_Phase_After_Cascade_On_Another_Thread(
        Container kind)
    {
        using var hub = new TestHub();
        var box = Build(kind, hub);
        box.Vm.Construct();
        var c1 = box.Child();
        var hooksBefore = box.HookRuns();
        var factoryBefore = box.FactoryCalls();
        using var cascadeStarted = new ManualResetEventSlim();
        using var reconstructReturned = new ManualResetEventSlim();
        c1.DisposeHook = () =>
        {
            cascadeStarted.Set();
            // Hold the cascade until reconstruct() returned. The wait is
            // bounded so that a construct phase blocked behind the cascade
            // cannot hang the test.
            reconstructReturned.Wait(TimeSpan.FromSeconds(5));
        };
        var boxStatuses = RecordStatuses(hub, "box");
        Task<Exception?>? dispose = null;
        hub.Messages.Subscribe(message =>
        {
            if (message is not ConstructionStatusChangedMessage
                {
                    SenderName: "box", Status: ConstructionStatus.Destructed,
                } || dispose is not null)
                return;
            dispose = Task.Factory.StartNew<Exception?>(
                () => Record.Exception(box.Vm.Dispose),
                CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
            cascadeStarted.Wait(HangGuard).Should().BeTrue();
        });

        var reconstruct = Task.Factory.StartNew(
            () =>
            {
                try { return Record.Exception(box.Vm.Reconstruct); }
                finally { reconstructReturned.Set(); }
            },
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        (await reconstruct.WaitAsync(HangGuard)).Should().BeNull("a superseded reconstruct returns");
        dispose.Should().NotBeNull();
        (await dispose!.WaitAsync(HangGuard)).Should().BeNull();

        boxStatuses.Should().Equal("Destructing", "Destructed", "Disposed");
        box.HookRuns().Should().Be(hooksBefore + (kind == Container.Aggregate1 ? 0 : 1),
            "only the destruct phase ran a hook");
        box.FactoryCalls().Should().Be(factoryBefore, "no slot factory runs");
        box.Vm.Status.Should().Be(ConstructionStatus.Disposed);
        c1.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── #1167 cross-thread regressions (spec/02 §7.2 Rule 3) ──────────────────

    /// <summary>
    /// LIFE-021 (#1167): a transition whose hook released its lease before a
    /// disposal on another thread started the inline cascade commits nothing
    /// afterward. The container publishes no Constructed or Destructed over its
    /// disposed child, the call returns without error, and the container ends
    /// Disposed with the child disposed once.
    /// </summary>
    [Theory, Trait("Conformance", "LIFE-021")]
    [InlineData(Container.Composite, true)]
    [InlineData(Container.Composite, false)]
    [InlineData(Container.Group, true)]
    [InlineData(Container.Group, false)]
    [InlineData(Container.Aggregate1, true)]
    [InlineData(Container.Aggregate1, false)]
    public async Task LIFE_021_Commit_After_Hook_Lease_Is_Dropped_Once_Cascade_Starts(
        Container kind, bool construct)
    {
        using var hub = new TestHub();
        var box = Build(kind, hub);
        if (construct) box.Vm.Destruct();
        else box.Vm.Construct();
        var transient = construct ? "Constructing" : "Destructing";
        using var paused = new ManualResetEventSlim();
        using var resume = new ManualResetEventSlim();
        using var childDisposing = new ManualResetEventSlim();
        using var transitionReturned = new ManualResetEventSlim();
        HookedVM? child = null;
        var childDisposals = 0;
        var probe = (ComponentVMBase)box.Vm;
        probe.AfterHookLeaseReleasedForTesting = () =>
        {
            probe.AfterHookLeaseReleasedForTesting = null;
            // The child the hook settled; an aggregate construct made a new slot.
            child = box.Child();
            child.DisposeHook = () =>
            {
                Interlocked.Increment(ref childDisposals);
                childDisposing.Set();
                resume.Set();
                // Hold the cascade until the transition has tried to commit and
                // returned. The wait is bounded so that a commit blocked behind
                // the cascade cannot hang the test.
                transitionReturned.Wait(TimeSpan.FromSeconds(5));
            };
            paused.Set();
            resume.Wait(HangGuard).Should().BeTrue();
        };
        var boxStatuses = new ConcurrentQueue<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is ConstructionStatusChangedMessage { SenderName: "box" } changed)
                boxStatuses.Enqueue($"{changed.Status} child={child?.Status}");
        });

        var transition = Task.Factory.StartNew(
            () =>
            {
                try { return Record.Exception(construct ? box.Vm.Construct : box.Vm.Destruct); }
                finally { transitionReturned.Set(); }
            },
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        paused.Wait(HangGuard).Should().BeTrue();
        var dispose = Task.Factory.StartNew(
            () => Record.Exception(box.Vm.Dispose),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        await Task.WhenAll(transition, dispose).WaitAsync(HangGuard);

        childDisposing.IsSet.Should().BeTrue();
        (await transition).Should().BeNull("a superseded transition returns without error");
        (await dispose).Should().BeNull();
        boxStatuses.Select(entry => entry.Split(' ')[0]).Should().Equal(transient, "Disposed");
        boxStatuses.Last().Should().Be($"Disposed child={ConstructionStatus.Disposed}");
        box.Vm.Status.Should().Be(ConstructionStatus.Disposed);
        child!.Status.Should().Be(ConstructionStatus.Disposed);
        Volatile.Read(ref childDisposals).Should().Be(1);
    }

    /// <summary>
    /// LIFE-021 (#1167, background leaf): thread F runs the queued Constructed
    /// commit while thread D disposes the leaf's member. The leaf publishes no
    /// Constructed while the member is Disposed, and it ends Disposed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-021")]
    public async Task LIFE_021_Queued_Background_Commit_On_Another_Thread_Is_Dropped()
    {
        using var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var leaf = new LeafVM("leaf", hub, dispatcher, background: true);
        var member = leaf.Member(new HookedVM("m1", hub));
        _ = leaf.ConstructAsync();
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        leaf.Status.Should().Be(ConstructionStatus.Constructing);
        using var memberDisposing = new ManualResetEventSlim();
        using var foregroundDrained = new ManualResetEventSlim();
        var leafStatuses = new ConcurrentQueue<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is not ConstructionStatusChangedMessage { SenderName: "leaf" } changed) return;
            leafStatuses.Enqueue($"{changed.Status} m1={member.Status}");
        });
        member.DisposeHook = () =>
        {
            memberDisposing.Set();
            // Hold the member cascade until thread F ran the queued commit. The
            // wait is bounded so that a commit blocked behind the cascade
            // cannot hang the test.
            foregroundDrained.Wait(TimeSpan.FromSeconds(5));
        };

        var foreground = Task.Factory.StartNew(
            () => Record.Exception(() =>
            {
                try
                {
                    memberDisposing.Wait(HangGuard).Should().BeTrue();
                    dispatcher.ForegroundScheduler.AdvanceBy(1);
                }
                finally { foregroundDrained.Set(); }
            }),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        var dispose = Task.Factory.StartNew(
            () => Record.Exception(leaf.Dispose),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);
        await Task.WhenAll(foreground, dispose).WaitAsync(HangGuard);

        (await foreground).Should().BeNull();
        (await dispose).Should().BeNull();
        leafStatuses.Should().Equal($"Disposed m1={ConstructionStatus.Disposed}");
        leaf.Status.Should().Be(ConstructionStatus.Disposed);
    }
}
