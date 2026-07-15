using System.Collections.Concurrent;
using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using FluentAssertions;
using FluentAssertions.Execution;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// Regression tests for async-lifecycle termination and dispose races
/// (spec/02-lifecycle.md invariant 3: Disposed is terminal).
/// </summary>
public class ComponentVMLifecycleRaceTests
{
    private static (ComponentVM<string> vm, TestHub hub, TestDispatcher dispatcher) BuildBackgroundVm()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .Build();
        return (vm, hub, dispatcher);
    }

    [Fact]
    public void ConstructAsync_On_Already_Constructed_Background_Vm_Completes_Synchronously()
    {
        var (vm, _, dispatcher) = BuildBackgroundVm();
        vm.Construct();
        dispatcher.BackgroundScheduler.AdvanceBy(1);  // OnConstruct on background
        dispatcher.ForegroundScheduler.AdvanceBy(1);  // marshalled Constructed on foreground (VMX-025)
        vm.Status.Should().Be(ConstructionStatus.Constructed);

        var task = vm.ConstructAsync();

        task.IsCompletedSuccessfully.Should().BeTrue(
            "already-Constructed is an idempotent no-op that emits no status message to wait for");
    }

    [Fact]
    public void DestructAsync_On_Already_Destructed_Background_Vm_Completes_Synchronously()
    {
        var (vm, _, dispatcher) = BuildBackgroundVm();
        vm.Construct();
        dispatcher.BackgroundScheduler.AdvanceBy(1);  // OnConstruct on background
        dispatcher.ForegroundScheduler.AdvanceBy(1);  // marshalled Constructed on foreground (VMX-025)
        vm.Destruct();
        dispatcher.BackgroundScheduler.AdvanceBy(1);  // OnDestruct on background
        dispatcher.ForegroundScheduler.AdvanceBy(1);  // marshalled Destructed on foreground (VMX-025)
        vm.Status.Should().Be(ConstructionStatus.Destructed);

        var task = vm.DestructAsync();

        task.IsCompletedSuccessfully.Should().BeTrue(
            "already-Destructed is an idempotent no-op that emits no status message to wait for");
    }

    [Fact]
    public async Task ConstructAsync_With_NullMessageHub_Completes_From_Internal_Lifecycle_State()
    {
        var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Model("m")
            .Background(true)
            .Build();

        var task = vm.ConstructAsync();

        var completed = await Task.WhenAny(task, Task.Delay(TimeSpan.FromSeconds(1)));
        completed.Should().BeSameAs(task,
            "lifecycle completion must not depend on a message hub publishing status messages");
        await task;
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public async Task DestructAsync_With_NullMessageHub_Completes_From_Internal_Lifecycle_State()
    {
        var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Model("m")
            .Background(true)
            .Build();
        vm.Construct();

        var task = vm.DestructAsync();

        var completed = await Task.WhenAny(task, Task.Delay(TimeSpan.FromSeconds(1)));
        completed.Should().BeSameAs(task,
            "lifecycle completion must not depend on a message hub publishing status messages");
        await task;
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Dispose_During_InFlight_Background_Construct_Does_Not_Resurrect()
    {
        var (vm, hub, dispatcher) = BuildBackgroundVm();
        var statuses = new List<ConstructionStatus>();
        using var sub = hub.Messages
            .OfType<IConstructionStatusChangedMessage>()
            .Where(m => ReferenceEquals(m.SenderObject, vm))
            .Subscribe(m => statuses.Add(m.Status));

        vm.Construct();                               // Constructing emitted; work scheduled
        vm.Dispose();                                 // terminal before background work runs
        dispatcher.BackgroundScheduler.AdvanceBy(1);  // background lambda must now no-op

        vm.Status.Should().Be(ConstructionStatus.Disposed);
        statuses.Should().NotContain(ConstructionStatus.Constructed,
            "a disposed VM must not publish post-dispose status messages");
        statuses[^1].Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public async Task ConstructAsync_Completes_When_Vm_Is_Disposed_Mid_Flight()
    {
        var (vm, _, dispatcher) = BuildBackgroundVm();

        var task = vm.ConstructAsync();
        vm.Dispose();
        dispatcher.BackgroundScheduler.AdvanceBy(1);

        var completed = await Task.WhenAny(task, Task.Delay(TimeSpan.FromSeconds(5)));
        completed.Should().BeSameAs(task,
            "the awaiter must observe the Disposed transition instead of hanging");
        vm.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public async Task ConstructAsync_Faults_When_Background_Construct_Rolls_Back()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .OnConstruct(() => throw new InvalidOperationException("boom"))
            .Build();

        var task = vm.ConstructAsync();
        Action runBackground = () => dispatcher.BackgroundScheduler.AdvanceBy(1);

        runBackground.Should().Throw<InvalidOperationException>();
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        var error = await Assert.ThrowsAsync<InvalidOperationException>(async () => await task);
        error.Message.Should().Be("boom");
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public async Task DestructAsync_Faults_When_Background_Destruct_Rolls_Back()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .OnDestruct(() => throw new InvalidOperationException("boom"))
            .Build();
        vm.Construct();
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        var task = vm.DestructAsync();
        Action runBackground = () => dispatcher.BackgroundScheduler.AdvanceBy(1);

        runBackground.Should().Throw<InvalidOperationException>();
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        var error = await Assert.ThrowsAsync<InvalidOperationException>(async () => await task);
        error.Message.Should().Be("boom");
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public async Task ConstructAsync_Faults_When_Background_Child_Rolls_Back()
    {
        var hub = new TestHub();
        var dispatcher = new RealThreadDispatcher();
        var failure = new InvalidOperationException("child hook failed");
        var child = ComponentVM<string>.Builder()
            .Name("child")
            .Services(hub, dispatcher)
            .Model("m")
            .Background(true)
            .OnConstruct(() => throw failure)
            .Build();
        var parent = CompositeVM<ComponentVM<string>>.Builder()
            .Name("parent")
            .Services(hub, dispatcher)
            .Children(() => [child])
            .Build();

        var task = parent.ConstructAsync();

        var error = await Assert.ThrowsAsync<InvalidOperationException>(
            async () => await task.WaitAsync(TimeSpan.FromSeconds(5)));
        error.Should().BeSameAs(failure);
        child.Status.Should().Be(ConstructionStatus.Destructed);
        parent.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public async Task Concurrent_Construct_Is_Rejected_While_First_Construct_Is_In_Flight()
    {
        var started = new ManualResetEventSlim();
        var release = new ManualResetEventSlim();
        var constructCalls = 0;
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("m")
            .OnConstruct(() =>
            {
                Interlocked.Increment(ref constructCalls);
                started.Set();
                release.Wait();
            })
            .Build();

        var first = Task.Run(vm.Construct);
        started.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue("the first construct entered its hook");

        Action second = vm.Construct;
        second.Should().Throw<StatusTransitionException>(
            "the per-VM lifecycle guard must reject concurrent construct re-entry");

        release.Set();
        await first;

        constructCalls.Should().Be(1);
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public async Task Concurrent_Destruct_Is_Rejected_While_First_Destruct_Is_In_Flight()
    {
        var started = new ManualResetEventSlim();
        var release = new ManualResetEventSlim();
        var destructCalls = 0;
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("vm")
            .Services(hub, dispatcher)
            .Model("m")
            .OnDestruct(() =>
            {
                Interlocked.Increment(ref destructCalls);
                started.Set();
                release.Wait();
            })
            .Build();
        vm.Construct();

        var first = Task.Run(vm.Destruct);
        started.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue("the first destruct entered its hook");

        Action second = vm.Destruct;
        second.Should().Throw<StatusTransitionException>(
            "the per-VM lifecycle guard must reject concurrent destruct re-entry");

        release.Set();
        await first;

        destructCalls.Should().Be(1);
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    /// <summary>
    /// VMX-001/054 regression: a background <c>Construct()</c> whose
    /// <c>SetStatus(Constructed)</c> runs on a real pool thread must never race a
    /// foreground <c>Dispose()</c> into (a) an <see cref="ObjectDisposedException"/>
    /// on the status-trigger Subject, (b) resurrection of the VM (final status
    /// flipping back to Constructed after Disposed), or (c) a post-dispose
    /// <c>ConstructionStatusChangedMessage(Constructed)</c>.
    ///
    /// Unlike the <c>TestScheduler</c>-driven cases above (which run the
    /// scheduled work single-threaded after Dispose, where the in-flight guard is
    /// trivially consistent), this exercises the genuine multi-threaded race that
    /// the audit flags as "only reachable under the real TaskPoolScheduler": the
    /// background completion and the foreground Dispose run concurrently. With the
    /// non-atomic check-then-act on a non-volatile <c>_status</c> this reproduces
    /// resurrection/post-dispose publishes within a few iterations; once the
    /// transition + dispose are serialized under one lock it is impossible, so the
    /// assertions hold deterministically (zero violations) for the fixed code.
    /// </summary>
    [Fact]
    public async Task Background_Construct_Racing_Dispose_Never_Resurrects_Or_Publishes_PostDispose()
    {
        // High iteration count so the (architecture-independent) interleaving
        // window is hit many times on the buggy code; the corrected code admits
        // zero violations regardless of count, so this stays deterministic.
        const int iterations = 20_000;

        var odeCount = 0;
        var resurrectionCount = 0;
        var postDisposeMessageCount = 0;
        var firstViolation = -1;

        for (var i = 0; i < iterations; i++)
        {
            using var hub = new TestHub();
            var dispatcher = new RealThreadDispatcher();
            var vm = ComponentVM<string>.Builder()
                .Name("vm")
                .Services(hub, dispatcher)
                .Model("m")
                .Background(true)
                .Build();

            var seenDisposed = 0;
            var seenConstructedAfterDispose = 0;
            using var sub = hub.Messages
                .OfType<IConstructionStatusChangedMessage>()
                .Where(m => ReferenceEquals(m.SenderObject, vm))
                .Subscribe(m =>
                {
                    if (m.Status == ConstructionStatus.Disposed)
                    {
                        Interlocked.Exchange(ref seenDisposed, 1);
                    }
                    else if (m.Status == ConstructionStatus.Constructed &&
                             Volatile.Read(ref seenDisposed) == 1)
                    {
                        // A Constructed message emitted *after* Disposed is a
                        // post-dispose publish (spec/02 invariant 3 violation).
                        Interlocked.Exchange(ref seenConstructedAfterDispose, 1);
                    }
                });

            // The race: schedule the background completion, then immediately
            // dispose on this (foreground) thread while it runs on the pool.
            vm.Construct();
            vm.Dispose();

            await Task.WhenAll(dispatcher.PendingWork);

            var ode = !dispatcher.Errors.IsEmpty;
            var resurrected = vm.Status == ConstructionStatus.Constructed;
            var postDispose = Volatile.Read(ref seenConstructedAfterDispose) == 1;

            if (ode) odeCount++;
            if (resurrected) resurrectionCount++;
            if (postDispose) postDisposeMessageCount++;
            if (firstViolation < 0 && (ode || resurrected || postDispose))
                firstViolation = i;
        }

        using (new AssertionScope())
        {
            odeCount.Should().Be(0,
                "OnNext must never run on a disposed status-trigger Subject");
            resurrectionCount.Should().Be(0,
                "a disposed VM must never flip back to Constructed (Disposed is terminal)");
            postDisposeMessageCount.Should().Be(0,
                "a disposed VM must never publish a post-dispose Constructed status message");
            firstViolation.Should().Be(-1,
                "the background transition and foreground Dispose must be atomic");
        }
    }

    [Fact]
    public async Task Concurrent_Dispose_Invokes_OnDispose_At_Most_Once()
    {
        const int iterations = 1_000;
        const int contenders = 16;

        for (var i = 0; i < iterations; i++)
        {
            var vm = new OnDisposeProbeVM();
            using var start = new ManualResetEventSlim();
            var tasks = Enumerable.Range(0, contenders)
                .Select(_ => Task.Run(() =>
                {
                    start.Wait();
                    vm.Dispose();
                }))
                .ToArray();

            start.Set();
            await Task.WhenAll(tasks);

            vm.DisposeCalls.Should().Be(1);
        }
    }
}

internal sealed class OnDisposeProbeVM : ComponentVMBase
{
    private int _disposeCalls;

    public OnDisposeProbeVM()
        : base("probe", "", new TestHub(), new TestDispatcher(), null, null)
    {
    }

    public override ViewModelType Type => ViewModelType.Component;
    public int DisposeCalls => _disposeCalls;

    protected override void OnDispose()
    {
        Interlocked.Increment(ref _disposeCalls);
    }
}

/// <summary>
/// Test-only <see cref="IDispatcher"/> whose Background scheduler runs scheduled
/// work on real thread-pool threads (so a background completion genuinely races a
/// foreground Dispose), capturing any thrown exceptions and exposing the pending
/// tasks so a test can await quiescence. Foreground is the inline scheduler.
/// </summary>
internal sealed class RealThreadDispatcher : IDispatcher
{
    private readonly RealThreadScheduler _background = new();

    public IScheduler Foreground => ImmediateScheduler.Instance;
    public IScheduler Background => _background;

    public ConcurrentQueue<Exception> Errors => _background.Errors;
    public IReadOnlyCollection<Task> PendingWork => _background.Tasks;

    private sealed class RealThreadScheduler : IScheduler
    {
        public ConcurrentQueue<Exception> Errors { get; } = new();
        public ConcurrentBag<Task> Tasks { get; } = new();

        public DateTimeOffset Now => DateTimeOffset.UtcNow;

        public IDisposable Schedule<TState>(
            TState state, Func<IScheduler, TState, IDisposable> action)
        {
            Tasks.Add(Task.Run(() =>
            {
                try
                {
                    action(this, state);
                }
                catch (Exception ex)
                {
                    Errors.Enqueue(ex);
                }
            }));
            return Disposable.Empty;
        }

        public IDisposable Schedule<TState>(
            TState state, TimeSpan dueTime, Func<IScheduler, TState, IDisposable> action)
            => Schedule(state, action);

        public IDisposable Schedule<TState>(
            TState state, DateTimeOffset dueTime, Func<IScheduler, TState, IDisposable> action)
            => Schedule(state, action);
    }
}
