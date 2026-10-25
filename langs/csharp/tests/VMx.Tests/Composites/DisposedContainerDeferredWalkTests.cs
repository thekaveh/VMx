using System.Collections.Concurrent;
using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Composites;

/// <summary>
/// A container disposed while its child walk waits to resume on the foreground
/// runs no user hook afterwards: neither its <c>onDestruct</c> callback nor the
/// composite <c>Current</c> selector (spec/02 §6, LIFE-015, #735).
/// </summary>
public class DisposedContainerDeferredWalkTests
{
    /// <summary>A scheduler whose queued work runs only when a test drains it.</summary>
    private sealed class ManualScheduler : IScheduler
    {
        private readonly ConcurrentQueue<Action> _queue = new();

        public DateTimeOffset Now => DateTimeOffset.UtcNow;

        public int Pending => _queue.Count;

        public IDisposable Schedule<TState>(TState state, Func<IScheduler, TState, IDisposable> action)
        {
            _queue.Enqueue(() => action(this, state));
            return Disposable.Empty;
        }

        public IDisposable Schedule<TState>(
            TState state, TimeSpan dueTime, Func<IScheduler, TState, IDisposable> action)
            => Schedule(state, action);

        public IDisposable Schedule<TState>(
            TState state, DateTimeOffset dueTime, Func<IScheduler, TState, IDisposable> action)
            => Schedule(state, action);

        /// <summary>Runs the work queued so far, in order.</summary>
        public void RunPending()
        {
            for (var count = _queue.Count; count > 0 && _queue.TryDequeue(out var work); count--)
                work();
        }

        public void WaitForPending(int count)
        {
            var deadline = DateTime.UtcNow + HangGuard;
            while (_queue.Count < count)
            {
                if (DateTime.UtcNow > deadline) throw new TimeoutException("expected queued work");
                Thread.Sleep(1);
            }
        }
    }

    private sealed class ManualDispatcher : IDispatcher
    {
        public ManualScheduler ForegroundQueue { get; } = new();
        public ManualScheduler BackgroundQueue { get; } = new();
        public IScheduler Foreground => ForegroundQueue;
        public IScheduler Background => BackgroundQueue;

        /// <summary>
        /// Runs queued background and foreground work until <paramref name="done"/>
        /// holds. A walk resumes through a pool thread, so idle queues alone do
        /// not mean the walk has finished.
        /// </summary>
        public void RunUntil(Func<bool> done)
        {
            var deadline = DateTime.UtcNow + HangGuard;
            while (!done())
            {
                if (DateTime.UtcNow > deadline) throw new TimeoutException("the condition did not hold");
                BackgroundQueue.RunPending();
                ForegroundQueue.RunPending();
                Thread.Sleep(1);
            }
        }
    }

    private static ComponentVM<string> BackgroundChild(ManualDispatcher dispatcher) => ComponentVM<string>.Builder()
        .Name("child")
        .Services(NullMessageHub.Instance, dispatcher)
        .Model("child")
        .Background(true)
        .Build();

    /// <summary>
    /// Runs the child's queued background hook and its terminal status, then
    /// waits until the container's walk has queued its foreground resumption.
    /// The test then disposes the container and runs that resumption itself.
    /// </summary>
    private static void SettleChildUntilTheWalkIsQueued(ManualDispatcher dispatcher)
    {
        dispatcher.BackgroundQueue.WaitForPending(1);
        dispatcher.BackgroundQueue.RunPending();
        dispatcher.ForegroundQueue.WaitForPending(1);
        dispatcher.ForegroundQueue.RunPending();
        dispatcher.ForegroundQueue.WaitForPending(1);
    }

    [Fact]
    public void Composite_Disposed_Before_Its_Deferred_Destruct_Resumes_Runs_No_OnDestruct()
    {
        var dispatcher = new ManualDispatcher();
        var onDestructRuns = 0;
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [BackgroundChild(dispatcher)])
            .OnDestruct(() => Interlocked.Increment(ref onDestructRuns))
            .Build();
        _ = composite.ConstructAsync();
        dispatcher.RunUntil(() => composite.Status == ConstructionStatus.Constructed);

        _ = composite.DestructAsync();
        SettleChildUntilTheWalkIsQueued(dispatcher);
        composite.Dispose();
        dispatcher.ForegroundQueue.RunPending();

        onDestructRuns.Should().Be(0, "a disposed composite runs no user onDestruct");
        composite.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void Composite_Disposed_Before_Its_Deferred_Construct_Resumes_Runs_No_Current_Selector()
    {
        var dispatcher = new ManualDispatcher();
        var selectorRuns = 0;
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [BackgroundChild(dispatcher)])
            .Current(children =>
            {
                Interlocked.Increment(ref selectorRuns);
                return children.FirstOrDefault();
            })
            .Build();

        _ = composite.ConstructAsync();
        SettleChildUntilTheWalkIsQueued(dispatcher);
        composite.Dispose();
        dispatcher.ForegroundQueue.RunPending();

        selectorRuns.Should().Be(0, "a disposed composite runs no Current selector");
        composite.Current.Should().BeNull();
        composite.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void Group_Disposed_Before_Its_Deferred_Destruct_Resumes_Runs_No_OnDestruct()
    {
        var dispatcher = new ManualDispatcher();
        var onDestructRuns = 0;
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("group")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [BackgroundChild(dispatcher)])
            .OnDestruct(() => Interlocked.Increment(ref onDestructRuns))
            .Build();
        _ = group.ConstructAsync();
        dispatcher.RunUntil(() => group.Status == ConstructionStatus.Constructed);

        _ = group.DestructAsync();
        SettleChildUntilTheWalkIsQueued(dispatcher);
        group.Dispose();
        dispatcher.ForegroundQueue.RunPending();

        onDestructRuns.Should().Be(0, "a disposed group runs no user onDestruct");
        group.Status.Should().Be(ConstructionStatus.Disposed);
    }
}
