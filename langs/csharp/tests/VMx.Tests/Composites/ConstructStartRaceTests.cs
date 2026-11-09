using System.Reactive.Concurrency;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Composites;

/// <summary>
/// One starter for each transition (ADR-0218 rule 6, #1370). A child added
/// while the container is Constructing, before the walk's snapshot, has two
/// starters: the add and the walk. Whoever calls construct first starts the
/// child. The walk joins a construct that the add started; the add leaves one
/// that the walk started. Neither fails, and the child's hook runs once.
/// </summary>
public class ConstructStartRaceTests
{
    private sealed class ImmediateDispatcher : IDispatcher
    {
        public IScheduler Foreground => ImmediateScheduler.Instance;
        public IScheduler Background => ImmediateScheduler.Instance;
    }

    private sealed class Rig
    {
        public required IComponentVM Root { get; init; }
        public required Action<ComponentVM> Add { get; init; }
        public required LateChildStarts LateStarts { get; init; }
        public required IEnumerable<IComponentVM> Members { get; init; }

        /// <summary>Runs inside the root's construct hook once the test arms it.</summary>
        public Action? Hook { get; set; }
    }

    private static Rig Create(string kind, IMessageHub hub, IDispatcher dispatcher)
    {
        Rig? rig = null;
        void Hook() => rig!.Hook?.Invoke();
        if (kind == "composite")
        {
            var composite = CompositeVM<ComponentVM>.Builder()
                .Name("root").Services(hub, dispatcher).Children(() => Array.Empty<ComponentVM>())
                .AutoConstructOnAdd(true).OnConstruct(Hook).Build();
            rig = new Rig
            {
                Root = composite,
                Add = composite.Add,
                LateStarts = composite.LateStartsForTesting,
                Members = composite,
            };
        }
        else
        {
            var group = GroupVM<ComponentVM>.Builder()
                .Name("root").Services(hub, dispatcher).Children(() => Array.Empty<ComponentVM>())
                .AutoConstructOnAdd(true).OnConstruct(Hook).Build();
            rig = new Rig
            {
                Root = group,
                Add = group.Add,
                LateStarts = group.LateStartsForTesting,
                Members = group,
            };
        }
        // Population runs on the first construct only; the race needs a
        // construct whose hook is followed directly by the walk's snapshot.
        rig.Root.Construct();
        rig.Root.Destruct();
        rig.Root.Status.Should().Be(ConstructionStatus.Destructed);
        return rig;
    }

    private sealed class Scenario : IDisposable
    {
        public ManualResetEventSlim ChildEntered { get; } = new();
        public ManualResetEventSlim ReleaseChild { get; } = new();
        public int Runs;

        public void Dispose()
        {
            ReleaseChild.Set();
            ChildEntered.Dispose();
            ReleaseChild.Dispose();
        }
    }

    private static ComponentVM Child(IMessageHub hub, IDispatcher dispatcher, Scenario scenario)
        => ComponentVM.Builder().Name("child").Services(hub, dispatcher).OnConstruct(() =>
        {
            Interlocked.Increment(ref scenario.Runs);
            scenario.ChildEntered.Set();
            scenario.ReleaseChild.Wait(Liveness.HangGuard).Should().BeTrue("the test releases the child");
        }).Build();

    private static Task<Exception?> Run(Action action)
        => Task.Factory.StartNew(
            Exception? () => Record.Exception(action),
            CancellationToken.None, TaskCreationOptions.LongRunning, TaskScheduler.Default);

    /// <summary>
    /// Releases the child's hook once the side that lost the start returned,
    /// so the child stays Constructing while that side makes its call.
    /// </summary>
    private static async Task ShouldSettle(Rig rig, ComponentVM child, Scenario scenario,
        Task<Exception?> construct, Task<Exception?> add, Task<Exception?> loser)
    {
        scenario.ChildEntered.Wait(Liveness.HangGuard).Should().BeTrue("one side starts the child");
        await loser.WaitAsync(Liveness.HangGuard);
        scenario.ReleaseChild.Set();
        await Task.WhenAll(construct, add).WaitAsync(Liveness.HangGuard);
        SpinWait.SpinUntil(
            () => rig.Root.Status != ConstructionStatus.Constructing &&
                !((ComponentVMBase)rig.Root).HasInFlightLifecycleForTesting,
            Liveness.HangGuard).Should().BeTrue("the root settles");

        (await add).Should().BeNull("the add leaves a construct that the walk started");
        (await construct).Should().BeNull("the walk joins a construct that the add started");
        rig.Root.Status.Should().Be(ConstructionStatus.Constructed);
        child.Status.Should().Be(ConstructionStatus.Constructed);
        rig.Members.Should().Contain(child);
        Volatile.Read(ref scenario.Runs).Should().Be(1, "the child's construct hook runs once");
    }

    /// <summary>The add reads Destructed; the walk starts the child before the add's call.</summary>
    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public async Task Add_Leaves_A_Construct_The_Walk_Started(string kind)
    {
        var hub = new TestHub();
        var dispatcher = new ImmediateDispatcher();
        var rig = Create(kind, hub, dispatcher);
        using var scenario = new Scenario();
        using var hookEntered = new ManualResetEventSlim();
        using var addStarting = new ManualResetEventSlim();
        var child = Child(hub, dispatcher, scenario);
        rig.Hook = () =>
        {
            hookEntered.Set();
            addStarting.Wait(Liveness.HangGuard).Should().BeTrue("the add reads the child Destructed");
        };
        rig.LateStarts.ProbeForTesting = (vm, stage) =>
        {
            if (!ReferenceEquals(vm, child) || stage != LateChildStage.Starting) return;
            addStarting.Set();
            SpinWait.SpinUntil(() => child.Status == ConstructionStatus.Constructing, Liveness.HangGuard)
                .Should().BeTrue("the walk starts the child");
        };

        var construct = Run(rig.Root.Construct);
        hookEntered.Wait(Liveness.HangGuard).Should().BeTrue();
        var add = Run(() => rig.Add(child));

        await ShouldSettle(rig, child, scenario, construct, add, loser: add);
    }

    /// <summary>The walk reads Destructed; the add starts the child before the walk's call.</summary>
    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public async Task Walk_Joins_A_Construct_The_Add_Started(string kind)
    {
        var hub = new TestHub();
        var dispatcher = new ImmediateDispatcher();
        var rig = Create(kind, hub, dispatcher);
        using var scenario = new Scenario();
        using var hookEntered = new ManualResetEventSlim();
        using var attached = new ManualResetEventSlim();
        using var walkReading = new ManualResetEventSlim();
        var child = Child(hub, dispatcher, scenario);
        rig.Hook = () =>
        {
            hookEntered.Set();
            attached.Wait(Liveness.HangGuard).Should().BeTrue("the add attaches the child");
        };
        rig.LateStarts.ProbeForTesting = (vm, stage) =>
        {
            if (!ReferenceEquals(vm, child) || stage != LateChildStage.Attached) return;
            attached.Set();
            walkReading.Wait(Liveness.HangGuard).Should().BeTrue("the walk reads the child Destructed");
        };
        child.ConstructOrJoinProbeForTesting = () =>
        {
            walkReading.Set();
            SpinWait.SpinUntil(() => child.Status == ConstructionStatus.Constructing, Liveness.HangGuard)
                .Should().BeTrue("the add starts the child");
        };

        var construct = Run(rig.Root.Construct);
        hookEntered.Wait(Liveness.HangGuard).Should().BeTrue();
        var add = Run(() => rig.Add(child));

        await ShouldSettle(rig, child, scenario, construct, add, loser: construct);
    }
}
