using System.Collections.Concurrent;
using System.Reactive.Concurrency;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// Deferred lifecycle completion (<c>CompleteLifecycleHookAfter</c> /
/// <c>TransitionChildrenAsync</c>): a hook that throws after deferring abandons
/// the deferral, and a deferred continuation publishes on the foreground.
/// </summary>
public class DeferredLifecycleHookTests
{
    private sealed class DeferThenThrowVM(IMessageHub hub, IDispatcher dispatcher)
        : ComponentVMBase("defer-then-throw", string.Empty, hub, dispatcher, null, null)
    {
        public Func<Task?> Deferral { get; set; } = () => null;
        public bool ThrowAfterDeferring { get; set; } = true;

        public override ViewModelType Type => ViewModelType.Component;

        public Task? LastDeferral { get; private set; }

        protected override void OnConstruct()
        {
            LastDeferral = Deferral();
            if (LastDeferral is not null)
                CompleteLifecycleHookAfter(LastDeferral);
            if (ThrowAfterDeferring)
                throw new InvalidOperationException("hook failed after deferring");
        }

        public static Task Children(IComponentVM child, Action after)
            => TransitionChildrenAsync([child], construct: true, after);
    }

    private static DeferThenThrowVM FailedAfterDeferring(Func<Task?> deferral)
    {
        var vm = new DeferThenThrowVM(new TestHub(), NullDispatcher.Instance) { Deferral = deferral };
        var act = () => vm.Construct();
        act.Should().Throw<InvalidOperationException>().WithMessage("*after deferring*");
        vm.Status.Should().Be(ConstructionStatus.Destructed);
        return vm;
    }

    [Fact]
    public void ThrowingHook_AbandonsDeferral_NextPlainConstructSettles()
    {
        var pending = new TaskCompletionSource<bool>();
        var vm = FailedAfterDeferring(() => pending.Task);

        vm.Deferral = () => null;
        vm.ThrowAfterDeferring = false;
        vm.Construct();

        vm.Status.Should().Be(ConstructionStatus.Constructed);
        pending.SetResult(true);
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public async Task ThrowingHook_AbandonsDeferral_NextDeferringConstructIsAccepted()
    {
        var vm = FailedAfterDeferring(() => new TaskCompletionSource<bool>().Task);

        var next = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        vm.Deferral = () => next.Task;
        vm.ThrowAfterDeferring = false;
        var construct = vm.ConstructAsync();
        vm.Status.Should().Be(ConstructionStatus.Constructing);

        next.SetResult(true);
        await construct.WaitAsync(TimeSpan.FromSeconds(5));
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public async Task ThrowingHook_AbandonedChildTransition_NeverRunsAfter()
    {
        var childDispatcher = new TestDispatcher();
        var child = ComponentVM.Builder()
            .Name("child")
            .Services(new TestHub(), childDispatcher)
            .Background(true)
            .Build();
        var afterRan = 0;
        var vm = FailedAfterDeferring(
            () => DeferThenThrowVM.Children(child, () => Interlocked.Exchange(ref afterRan, 1)));
        var abandoned = vm.LastDeferral!;

        childDispatcher.BackgroundScheduler.AdvanceBy(1);
        childDispatcher.ForegroundScheduler.AdvanceBy(1);
        await abandoned.WaitAsync(TimeSpan.FromSeconds(5));

        child.Status.Should().Be(ConstructionStatus.Constructed);
        Volatile.Read(ref afterRan).Should().Be(0);
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void DeferredCompositeContinuation_PublishesOnForeground()
    {
        using var foreground = new EventLoopScheduler(start => new Thread(start)
        {
            Name = "vmx-test-foreground",
            IsBackground = true,
        });
        var foregroundThreadId = 0;
        foreground.Schedule(() => foregroundThreadId = Environment.CurrentManagedThreadId);
        var dispatcher = new RxDispatcher(foreground, TaskPoolScheduler.Default);
        var hub = new MessageHub();
        var observed = new ConcurrentQueue<(string What, int ThreadId)>();
        void Record(string what) => observed.Enqueue((what, Environment.CurrentManagedThreadId));

        var child = ComponentVM.Builder()
            .Name("child")
            .Services(hub, dispatcher)
            .Background(true)
            .Build();
        var composite = CompositeVM<IComponentVM>.Builder()
            .Name("composite")
            .Services(hub, dispatcher)
            .Children(() => [child])
            .Current(items => items.First())
            .OnCurrentChanged(_ => Record("OnCurrentChanged"))
            .OnDestruct(() => Record("onDestruct"))
            .Build();
        child.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(IComponentVM.IsCurrent)) Record("child IsCurrent");
        };
        using var constructed = new ManualResetEventSlim();
        using var destructed = new ManualResetEventSlim();
        composite.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == "Current") Record("composite Current");
            if (e.PropertyName != nameof(IComponentVM.Status)) return;
            if (composite.Status == ConstructionStatus.Constructed) constructed.Set();
            if (composite.Status == ConstructionStatus.Destructed) destructed.Set();
        };

        foreground.Schedule(() => composite.Construct());
        constructed.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();
        foreground.Schedule(() => composite.Destruct());
        destructed.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();

        observed.Select(entry => entry.What).Should().Contain(
            ["child IsCurrent", "composite Current", "OnCurrentChanged", "onDestruct"]);
        observed.Should().OnlyContain(entry => entry.ThreadId == foregroundThreadId);
        composite.Dispose();
    }
}
