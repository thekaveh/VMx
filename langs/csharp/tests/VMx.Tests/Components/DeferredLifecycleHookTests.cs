using System.Collections.Concurrent;
using System.Reactive.Concurrency;
using FluentAssertions;
using FluentAssertions.Execution;
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

        public static Task Children(IComponentVM first, IComponentVM second, Action after)
            => TransitionChildrenAsync([first, second], construct: true, after);
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
    public async Task ThrowingHook_AbandonedChildTransition_DrivesNoFurtherChildren()
    {
        var childDispatcher = new TestDispatcher();
        var first = ComponentVM.Builder()
            .Name("first")
            .Services(new TestHub(), childDispatcher)
            .Background(true)
            .Build();
        var second = ComponentVM.Builder()
            .Name("second")
            .Services(new TestHub(), NullDispatcher.Instance)
            .Build();
        var vm = FailedAfterDeferring(
            () => DeferThenThrowVM.Children(first, second, () => { }));
        var abandoned = vm.LastDeferral!;

        childDispatcher.BackgroundScheduler.AdvanceBy(1);
        childDispatcher.ForegroundScheduler.AdvanceBy(1);
        await abandoned.WaitAsync(TimeSpan.FromSeconds(5));

        first.Status.Should().Be(ConstructionStatus.Constructed);
        second.Status.Should().Be(ConstructionStatus.Destructed);
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

    // ── Issue #725: the rest of the walk after a background child ─────────────

    /// <summary>A named foreground event loop with thread-tagged recording.</summary>
    private sealed class ForegroundLoop : IDisposable
    {
        private readonly EventLoopScheduler _loop = new(start => new Thread(start)
        {
            Name = "vmx-test-foreground",
            IsBackground = true,
        });

        public ForegroundLoop()
        {
            Dispatcher = new RxDispatcher(_loop, TaskPoolScheduler.Default);
            Run(() => ThreadId = Environment.CurrentManagedThreadId);
        }

        public int ThreadId { get; private set; }
        public RxDispatcher Dispatcher { get; }
        public MessageHub Hub { get; } = new();
        public ConcurrentQueue<(string Phase, string What, int ThreadId)> Observed { get; } = new();
        public string Phase { get; set; } = "build";

        public void Record(string what)
            => Observed.Enqueue((Phase, what, Environment.CurrentManagedThreadId));

        /// <summary>Runs <paramref name="action"/> on the loop and waits for it.</summary>
        public void Run(Action action)
        {
            Exception? failure = null;
            using var done = new ManualResetEventSlim();
            _loop.Schedule(() =>
            {
                try { action(); }
                catch (Exception error) { failure = error; }
                finally { done.Set(); }
            });
            done.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();
            if (failure is not null) throw new InvalidOperationException("loop action failed", failure);
        }

        /// <summary>Runs one lifecycle phase on the loop and waits for the root to settle.</summary>
        public void Transition(string phase, IComponentVM root, Action<IComponentVM> start, ConstructionStatus settled)
        {
            Phase = phase;
            Run(() => start(root));
            SpinWait.SpinUntil(() => root.Status == settled, TimeSpan.FromSeconds(5)).Should().BeTrue();
            Run(() => { }); // flush anything the terminal emission queued behind it
        }

        public void Dispose() => _loop.Dispose();
    }

    private static ComponentVM BackgroundChild(ForegroundLoop loop) => ComponentVM.Builder()
        .Name("background")
        .Services(loop.Hub, loop.Dispatcher)
        .Background(true)
        .Build();

    /// <summary>A composite sibling with one child, recording every emission it owns.</summary>
    private static CompositeVM<IComponentVM> RecordingSibling(ForegroundLoop loop)
    {
        var x = ComponentVM.Builder().Name("x").Services(loop.Hub, loop.Dispatcher).Build();
        x.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(IComponentVM.IsCurrent)) loop.Record("X IsCurrent");
        };
        var sibling = CompositeVM<IComponentVM>.Builder()
            .Name("sibling")
            .Services(loop.Hub, loop.Dispatcher)
            .Children(() => [x])
            .Current(items => items.First())
            .OnCurrentChanged(_ => loop.Record("C OnCurrentChanged"))
            .OnConstruct(() => loop.Record("C onConstruct"))
            .OnDestruct(() => loop.Record("C onDestruct"))
            .Build();
        sibling.CollectionChanged += (_, _) => loop.Record("C CollectionChanged");
        sibling.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == "Current") loop.Record("C Current");
        };
        return sibling;
    }

    private static readonly string[] s_constructEmissions =
        ["C onConstruct", "C CollectionChanged", "X IsCurrent", "C Current", "C OnCurrentChanged"];

    private static readonly string[] s_destructEmissions =
        ["X IsCurrent", "C Current", "C OnCurrentChanged", "C onDestruct"];

    private static void ShouldAllRunOnForeground(ForegroundLoop loop, string phase, string[] expected)
    {
        var entries = loop.Observed.Where(entry => entry.Phase == phase).ToArray();
        entries.Select(entry => entry.What).Should().Contain(expected);
        entries.Should().OnlyContain(
            entry => entry.ThreadId == loop.ThreadId,
            $"every {phase} emission must run on the foreground thread {loop.ThreadId}");
    }

    [Fact]
    public void BackgroundChild_ThenAddedCompositeSibling_WalkStaysOnForeground()
    {
        using var loop = new ForegroundLoop();
        var parent = CompositeVM<IComponentVM>.Builder()
            .Name("parent")
            .Services(loop.Hub, loop.Dispatcher)
            .Children(() => [])
            .Build();
        loop.Run(() =>
        {
            parent.Add(BackgroundChild(loop));
            parent.Add(RecordingSibling(loop));
        });

        loop.Transition("construct", parent, vm => vm.Construct(), ConstructionStatus.Constructed);
        loop.Transition("destruct", parent, vm => vm.Destruct(), ConstructionStatus.Destructed);

        using (new AssertionScope())
        {
            ShouldAllRunOnForeground(loop, "construct", s_constructEmissions);
            ShouldAllRunOnForeground(loop, "destruct", s_destructEmissions);
        }
        loop.Run(parent.Dispose);
    }

    [Fact]
    public void BackgroundChild_ThenFactoryCompositeSibling_DestructWalkStaysOnForeground()
    {
        using var loop = new ForegroundLoop();
        var parent = CompositeVM<IComponentVM>.Builder()
            .Name("parent")
            .Services(loop.Hub, loop.Dispatcher)
            .Children(() => [BackgroundChild(loop), RecordingSibling(loop)])
            .Build();

        loop.Transition("construct", parent, vm => vm.Construct(), ConstructionStatus.Constructed);
        loop.Transition("destruct", parent, vm => vm.Destruct(), ConstructionStatus.Destructed);

        using (new AssertionScope())
        {
            ShouldAllRunOnForeground(loop, "construct", s_constructEmissions);
            ShouldAllRunOnForeground(loop, "destruct", s_destructEmissions);
        }
        loop.Run(parent.Dispose);
    }

    [Fact]
    public void BackgroundSlot_ThenCompositeSlot_AggregateWalkStaysOnForeground()
    {
        using var loop = new ForegroundLoop();
        var aggregate = VMx.Aggregates.AggregateVM2<IComponentVM, IComponentVM>.Builder()
            .Name("aggregate")
            .Services(loop.Hub, loop.Dispatcher)
            .Component1(() => BackgroundChild(loop))
            .Component2(() => RecordingSibling(loop))
            .Build();

        loop.Transition("construct", aggregate, vm => vm.Construct(), ConstructionStatus.Constructed);
        loop.Transition("destruct", aggregate, vm => vm.Destruct(), ConstructionStatus.Destructed);

        using (new AssertionScope())
        {
            ShouldAllRunOnForeground(loop, "construct", s_constructEmissions);
            ShouldAllRunOnForeground(loop, "destruct", s_destructEmissions);
        }
        loop.Run(aggregate.Dispose);
    }

    [Fact]
    public void SynchronousChildren_ConstructCompletesWalkOnCallingThreadBeforeReturning()
    {
        using var loop = new ForegroundLoop();
        var plain = ComponentVM.Builder().Name("plain").Services(loop.Hub, loop.Dispatcher).Build();
        var parent = CompositeVM<IComponentVM>.Builder()
            .Name("parent")
            .Services(loop.Hub, loop.Dispatcher)
            .Children(() => [plain, RecordingSibling(loop)])
            .Current(items => items.Last())
            .OnCurrentChanged(_ => loop.Record("P OnCurrentChanged"))
            .Build();
        var caller = Environment.CurrentManagedThreadId;
        caller.Should().NotBe(loop.ThreadId);

        loop.Phase = "construct";
        parent.Construct();
        parent.Status.Should().Be(ConstructionStatus.Constructed);
        var constructed = loop.Observed.ToArray();
        constructed.Select(entry => entry.What).Should().Contain([.. s_constructEmissions, "P OnCurrentChanged"]);
        constructed.Should().OnlyContain(entry => entry.ThreadId == caller);

        loop.Phase = "destruct";
        parent.Destruct();
        parent.Status.Should().Be(ConstructionStatus.Destructed);
        var destructed = loop.Observed.Where(entry => entry.Phase == "destruct").ToArray();
        destructed.Select(entry => entry.What).Should().Contain([.. s_destructEmissions, "P OnCurrentChanged"]);
        destructed.Should().OnlyContain(entry => entry.ThreadId == caller);
        parent.Dispose();
    }

    private sealed class RejectingForeground : IScheduler
    {
        public DateTimeOffset Now => DateTimeOffset.UtcNow;

        public IDisposable Schedule<TState>(TState state, Func<IScheduler, TState, IDisposable> action)
            => throw new InvalidOperationException("foreground rejected work");

        public IDisposable Schedule<TState>(
            TState state, TimeSpan dueTime, Func<IScheduler, TState, IDisposable> action)
            => throw new InvalidOperationException("foreground rejected work");

        public IDisposable Schedule<TState>(
            TState state, DateTimeOffset dueTime, Func<IScheduler, TState, IDisposable> action)
            => throw new InvalidOperationException("foreground rejected work");
    }

    [Fact]
    public async Task BackgroundChild_RejectedForegroundResumption_FaultsTheParentTransition()
    {
        using var loop = new ForegroundLoop();
        var siblingConstructed = 0;
        var sibling = ComponentVM.Builder()
            .Name("sibling")
            .Services(loop.Hub, loop.Dispatcher)
            .OnConstruct(() => Interlocked.Exchange(ref siblingConstructed, 1))
            .Build();
        var parent = CompositeVM<IComponentVM>.Builder()
            .Name("parent")
            .Services(new MessageHub(), new RxDispatcher(new RejectingForeground(), ImmediateScheduler.Instance))
            .Children(() => [])
            .Build();
        parent.Add(BackgroundChild(loop));
        parent.Add(sibling);

        var construct = () => parent.ConstructAsync().WaitAsync(TimeSpan.FromSeconds(5));

        await construct.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("foreground rejected work");
        parent.Status.Should().Be(ConstructionStatus.Destructed);
        Volatile.Read(ref siblingConstructed).Should().Be(0);
    }
}
