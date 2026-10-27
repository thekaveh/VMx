using System.Collections.Concurrent;
using System.Reactive.Concurrency;
using Microsoft.Reactive.Testing;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Consumer.Tests;

/// <summary>
/// A leaf view-model written the way an application writes one: it sees only
/// the public and protected surface of VMx (spec/02 §6.1 and §7.1, ADR-0162).
/// </summary>
public class LeafMemberTests
{
    private sealed class DashboardVM : ComponentVMBase
    {
        public DashboardVM(IMessageHub hub, IDispatcher dispatcher, IComponentVM chart, IComponentVM table)
            : base("dashboard", hub, dispatcher)
        {
            Chart = OwnMember(chart);
            Table = OwnMember(table);
        }

        public IComponentVM Chart { get; }
        public IComponentVM Table { get; }
        public int AfterRuns { get; private set; }

        public override ViewModelType Type => ViewModelType.Component;

        public static Task WalkOutsideAHook(IComponentVM child)
            => TransitionChildrenAsync([child], construct: true);

        public void DeferOutsideAHook() => CompleteLifecycleHookAfter(Task.CompletedTask);

        protected override void OnConstruct()
            => CompleteLifecycleHookAfter(
                TransitionChildrenAsync([Chart, Table], construct: true, after: () => AfterRuns++));

        protected override void OnDestruct()
            => CompleteLifecycleHookAfter(TransitionChildrenAsync([Table, Chart], construct: false));
    }

    private sealed class ManualDispatcher : IDispatcher
    {
        public TestScheduler BackgroundScheduler { get; } = new();
        public IScheduler Foreground => ImmediateScheduler.Instance;
        public IScheduler Background => BackgroundScheduler;
    }

    private static ComponentVM Member(string name, IMessageHub hub, IDispatcher? dispatcher = null,
        bool background = false)
        => ComponentVM.Builder()
            .Name(name)
            .Services(hub, dispatcher ?? NullDispatcher.Instance)
            .Background(background)
            .Build();

    private static ConcurrentQueue<string> Record(MessageHub hub)
    {
        var recorded = new ConcurrentQueue<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is IConstructionStatusChangedMessage changed)
                recorded.Enqueue($"{changed.SenderName} {changed.Status}");
        });
        return recorded;
    }

    [Fact]
    public void ConstructAndDestruct_WalkTheMembersInTheGivenOrder()
    {
        using var hub = new MessageHub();
        var vm = new DashboardVM(hub, NullDispatcher.Instance, Member("chart", hub), Member("table", hub));
        var recorded = Record(hub);

        vm.Construct();
        vm.Destruct();

        Assert.Equal(
            [
                "dashboard Constructing",
                "chart Constructing", "chart Constructed",
                "table Constructing", "table Constructed",
                "dashboard Constructed",
                "dashboard Destructing",
                "table Destructing", "table Destructed",
                "chart Destructing", "chart Destructed",
                "dashboard Destructed",
            ],
            recorded);
        Assert.Equal(1, vm.AfterRuns);
    }

    [Fact]
    public async Task Construct_WaitsForABackgroundMember()
    {
        using var hub = new MessageHub();
        var dispatcher = new ManualDispatcher();
        var chart = Member("chart", hub, dispatcher, background: true);
        var vm = new DashboardVM(hub, NullDispatcher.Instance, chart, Member("table", hub));

        var construct = vm.ConstructAsync();

        Assert.Equal(ConstructionStatus.Constructing, vm.Status);
        Assert.Equal(ConstructionStatus.Destructed, vm.Table.Status);
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        await construct.WaitAsync(TimeSpan.FromSeconds(30));
        Assert.Equal(ConstructionStatus.Constructed, vm.Status);
        Assert.Equal(ConstructionStatus.Constructed, vm.Table.Status);
        Assert.Equal(1, vm.AfterRuns);
    }

    [Fact]
    public void TheHelpers_ThrowOutsideTheVMsOwnHook()
    {
        using var hub = new MessageHub();
        var child = Member("child", hub);
        var vm = new DashboardVM(hub, NullDispatcher.Instance, Member("chart", hub), Member("table", hub));

        Assert.Throws<InvalidOperationException>(() => { _ = DashboardVM.WalkOutsideAHook(child); });
        Assert.Throws<InvalidOperationException>(vm.DeferOutsideAHook);
        Assert.Equal(ConstructionStatus.Destructed, child.Status);
    }

    [Fact]
    public void Dispose_DisposesTheMembersFirst()
    {
        using var hub = new MessageHub();
        var vm = new DashboardVM(hub, NullDispatcher.Instance, Member("chart", hub), Member("table", hub));
        vm.Construct();
        var recorded = Record(hub);

        vm.Dispose();

        Assert.Equal(["chart Disposed", "table Disposed", "dashboard Disposed"], recorded);
    }
}
