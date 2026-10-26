using System.Collections.Concurrent;
using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using System.Reactive.Linq;
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

namespace VMx.Tests.Composites;

/// <summary>
/// A container disposed while its child walk waits for a background child
/// abandons that walk before it disposes the children. The walk then fails
/// because its child was disposed, but the container publishes no rollback
/// status, only its transient status and <c>Disposed</c>, and the awaited
/// <c>ConstructAsync</c> / <c>DestructAsync</c> task completes without a fault
/// when Dispose settles it on <c>Disposed</c> (spec/02 §6, LIFE-013, #755).
/// The rollback and the fault raced the container's own <c>Disposed</c> on a
/// pool thread, so each container kind runs many times.
/// </summary>
public class DisposeAbandonsChildWalkTests
{
    /// <summary>A scheduler whose queued work runs only when the test drains it.</summary>
    private sealed class QueueScheduler : IScheduler
    {
        private readonly ConcurrentQueue<Action> _queue = new();

        public DateTimeOffset Now => DateTimeOffset.UtcNow;

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

        public void RunPending()
        {
            while (_queue.TryDequeue(out var work))
                work();
        }
    }

    public enum Kind
    {
        Composite,
        Group,
        Aggregate,
    }

    private static ComponentVM<string> Leaf(IMessageHub hub, IDispatcher dispatcher, string name, bool background)
        => ComponentVM<string>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Model(name)
            .Background(background)
            .Build();

    private static ComponentVMBase Container(Kind kind, IMessageHub hub, IDispatcher dispatcher)
        => kind switch
        {
            Kind.Composite => CompositeVM<ComponentVM<string>>.Builder()
                .Name("P")
                .Services(hub, dispatcher)
                .Children(() => [Leaf(hub, dispatcher, "B", background: true)])
                .Build(),
            Kind.Group => GroupVM<ComponentVM<string>>.Builder()
                .Name("P")
                .Services(hub, dispatcher)
                .Children(() => [Leaf(hub, dispatcher, "B", background: true)])
                .Build(),
            _ => AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
                .Name("P")
                .Services(hub, dispatcher)
                .Component1(() => Leaf(hub, dispatcher, "A", background: false))
                .Component2(() => Leaf(hub, dispatcher, "B", background: true))
                .Build(),
        };

    public enum Path
    {
        Construct,
        Destruct,
    }

    [Theory]
    [InlineData(Kind.Composite, Path.Construct, 3_000)]
    [InlineData(Kind.Group, Path.Construct, 3_000)]
    [InlineData(Kind.Aggregate, Path.Construct, 3_000)]
    [InlineData(Kind.Composite, Path.Destruct, 2_000)]
    [InlineData(Kind.Group, Path.Destruct, 2_000)]
    [InlineData(Kind.Aggregate, Path.Destruct, 2_000)]
    public void Dispose_During_A_Background_Walk_Publishes_No_Rollback_And_Faults_No_Awaiter(
        Kind kind, Path path, int iterations)
    {
        var transient = path == Path.Construct ? ConstructionStatus.Constructing : ConstructionStatus.Destructing;
        var failures = new List<string>();
        for (var run = 0; run < iterations; run++)
        {
            var background = new QueueScheduler();
            var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, background);
            using var hub = new TestHub();
            var container = Container(kind, hub, dispatcher);
            if (path == Path.Destruct)
            {
                container.Construct();
                WaitUntil(() =>
                {
                    background.RunPending();
                    return container.Status == ConstructionStatus.Constructed &&
                           !container.HasInFlightLifecycleForTesting;
                }, "the container did not construct");
            }

            var statuses = new ConcurrentQueue<ConstructionStatus>();
            using var subscription = hub.Messages
                .OfType<ConstructionStatusChangedMessage>()
                .Where(message => message.SenderName == "P")
                .Subscribe(message => statuses.Enqueue(message.Status));

            var awaited = path == Path.Construct ? container.ConstructAsync() : container.DestructAsync();
            container.Dispose();
            background.RunPending();

            // The failed walk settles the container's in-flight guard on a pool
            // thread; wait for it so a late rollback or fault would be recorded.
            WaitUntil(() => awaited.IsCompleted && !container.HasInFlightLifecycleForTesting,
                "the walk did not settle");

            var published = statuses.ToArray();
            if (!published.SequenceEqual([transient, ConstructionStatus.Disposed]))
                failures.Add($"run {run}: published {string.Join(", ", published)}");
            if (awaited.Status != TaskStatus.RanToCompletion)
                failures.Add($"run {run}: awaited task {awaited.Status}: {awaited.Exception?.InnerException?.Message}");
        }

        failures.Should().BeEmpty(
            $"a container disposed during its child walk publishes only {transient} and Disposed, " +
            $"and its awaited task does not fault; {failures.Count} failures in {iterations} runs, " +
            $"first: {string.Join("; ", failures.Take(3))}");
    }

    private static void WaitUntil(Func<bool> condition, string timeoutMessage)
    {
        var deadline = DateTime.UtcNow + HangGuard;
        while (!condition())
        {
            if (DateTime.UtcNow > deadline) throw new TimeoutException(timeoutMessage);
            Thread.Yield();
        }
    }
}
