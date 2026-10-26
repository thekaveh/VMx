using System.Collections.Concurrent;
using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using FluentAssertions;
using VMx.Aggregates;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Composites;

/// <summary>
/// A container destructed while one of its children is already Destructing
/// joins that child's in-flight destruct instead of starting a second one
/// (spec/02 §6, #754). The container settles only when the joined child does,
/// and a failed joined destruct surfaces like one the walk started.
/// </summary>
public class DestructJoinsDestructingChildTests
{
    /// <summary>
    /// A scheduler whose queued work runs only when a test drains it. A queued
    /// item that throws is recorded, not rethrown: a failing background hook
    /// rethrows into its scheduler by design.
    /// </summary>
    private sealed class ManualScheduler : IScheduler
    {
        private readonly ConcurrentQueue<Action> _queue = new();

        public DateTimeOffset Now => DateTimeOffset.UtcNow;

        public ConcurrentQueue<Exception> Faults { get; } = new();

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
            {
                try { work(); }
                catch (Exception error) { Faults.Enqueue(error); }
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

    private sealed class Counter
    {
        private int _value;
        public int Value => Volatile.Read(ref _value);
        public void Increment() => Interlocked.Increment(ref _value);
    }

    private static ComponentVM<string> BackgroundChild(
        ManualDispatcher dispatcher, Counter destructs, Exception? failure = null)
        => ComponentVM<string>.Builder()
            .Name("background")
            .Services(NullMessageHub.Instance, dispatcher)
            .Model("background")
            .Background(true)
            .OnDestruct(() =>
            {
                destructs.Increment();
                if (failure is not null) throw failure;
            })
            .Build();

    private static ComponentVM<string> SyncChild(ManualDispatcher dispatcher)
        => ComponentVM<string>.Builder()
            .Name("sync")
            .Services(NullMessageHub.Instance, dispatcher)
            .Model("sync")
            .Build();

    /// <summary>
    /// Starts the child's destruct and holds its background hook in the queue,
    /// so the child stays Destructing while the container destructs.
    /// </summary>
    private static Task StartChildDestruct(ComponentVM<string> child)
    {
        var childDestruct = child.DestructAsync();
        child.Status.Should().Be(ConstructionStatus.Destructing);
        return childDestruct;
    }

    private static void ShouldJoinTheDestructingChild(
        ManualDispatcher dispatcher,
        IComponentVM container,
        ComponentVM<string> child,
        Counter childDestructs)
    {
        dispatcher.RunUntil(() =>
            container.Status == ConstructionStatus.Constructed &&
            child.Status == ConstructionStatus.Constructed);
        var childDestruct = StartChildDestruct(child);

        Action destruct = container.Destruct;

        destruct.Should().NotThrow("the container joins the child's in-flight destruct");
        container.Status.Should().Be(ConstructionStatus.Destructing);
        dispatcher.RunUntil(() =>
            container.Status == ConstructionStatus.Destructed &&
            child.Status == ConstructionStatus.Destructed &&
            childDestruct.IsCompleted);
        childDestruct.Status.Should().Be(TaskStatus.RanToCompletion);
        childDestructs.Value.Should().Be(1, "the joined child's OnDestruct runs once");
        dispatcher.BackgroundQueue.Faults.Should().BeEmpty();
        dispatcher.ForegroundQueue.Faults.Should().BeEmpty();
    }

    [Fact]
    public void Composite_Destruct_Joins_A_Destructing_Child()
    {
        var dispatcher = new ManualDispatcher();
        var childDestructs = new Counter();
        var containerDestructs = new Counter();
        var child = BackgroundChild(dispatcher, childDestructs);
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [child, SyncChild(dispatcher)])
            .OnDestruct(containerDestructs.Increment)
            .Build();
        _ = composite.ConstructAsync();

        ShouldJoinTheDestructingChild(dispatcher, composite, child, childDestructs);

        containerDestructs.Value.Should().Be(1);
        composite.Should().OnlyContain(item => item.Status == ConstructionStatus.Destructed);
    }

    [Fact]
    public async Task Composite_DestructAsync_Joins_A_Destructing_Child()
    {
        var dispatcher = new ManualDispatcher();
        var childDestructs = new Counter();
        var child = BackgroundChild(dispatcher, childDestructs);
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [child])
            .Build();
        _ = composite.ConstructAsync();
        dispatcher.RunUntil(() => composite.Status == ConstructionStatus.Constructed);
        var childDestruct = StartChildDestruct(child);

        var destruct = composite.DestructAsync();
        dispatcher.RunUntil(() => destruct.IsCompleted && childDestruct.IsCompleted);

        await destruct;
        await childDestruct;
        composite.Status.Should().Be(ConstructionStatus.Destructed);
        child.Status.Should().Be(ConstructionStatus.Destructed);
        childDestructs.Value.Should().Be(1);
    }

    [Fact]
    public void Group_Destruct_Joins_A_Destructing_Child()
    {
        var dispatcher = new ManualDispatcher();
        var childDestructs = new Counter();
        var containerDestructs = new Counter();
        var child = BackgroundChild(dispatcher, childDestructs);
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("group")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [SyncChild(dispatcher), child])
            .OnDestruct(containerDestructs.Increment)
            .Build();
        _ = group.ConstructAsync();

        ShouldJoinTheDestructingChild(dispatcher, group, child, childDestructs);

        containerDestructs.Value.Should().Be(1);
        group.Should().OnlyContain(item => item.Status == ConstructionStatus.Destructed);
    }

    [Fact]
    public void Aggregate_Destruct_Joins_A_Destructing_Slot()
    {
        var dispatcher = new ManualDispatcher();
        var childDestructs = new Counter();
        var aggregate = AggregateVM2<ComponentVM<string>, ComponentVM<string>>.Builder()
            .Name("aggregate")
            .Services(NullMessageHub.Instance, dispatcher)
            .Component1(() => SyncChild(dispatcher))
            .Component2(() => BackgroundChild(dispatcher, childDestructs))
            .Build();
        _ = aggregate.ConstructAsync();
        dispatcher.RunUntil(() => aggregate.Status == ConstructionStatus.Constructed);

        ShouldJoinTheDestructingChild(dispatcher, aggregate, aggregate.Component2!, childDestructs);

        aggregate.Component1!.Status.Should().Be(ConstructionStatus.Destructed);
    }

    private sealed class CountingDecorator(IComponentVM<string> wrapped)
        : ForwardingComponentVM<string>(wrapped)
    {
        private int _destructAsyncCalls;

        public int DestructAsyncCalls => Volatile.Read(ref _destructAsyncCalls);

        public override Task DestructAsync()
        {
            Interlocked.Increment(ref _destructAsyncCalls);
            return base.DestructAsync();
        }
    }

    /// <summary>
    /// A forwarding decorator whose wrapped VM is already Destructing is joined
    /// through the decorator: the container calls neither the decorator's
    /// <c>DestructAsync()</c> nor the wrapped VM's destruct a second time.
    /// </summary>
    [Fact]
    public void Composite_Destruct_Joins_A_Destructing_Forwarding_Child()
    {
        var dispatcher = new ManualDispatcher();
        var childDestructs = new Counter();
        var decorator = new CountingDecorator(BackgroundChild(dispatcher, childDestructs));
        var composite = CompositeVM<IComponentVM>.Builder()
            .Name("composite")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [decorator])
            .Build();
        _ = composite.ConstructAsync();
        dispatcher.RunUntil(() => composite.Status == ConstructionStatus.Constructed);
        var childDestruct = decorator.DestructAsync();
        decorator.Status.Should().Be(ConstructionStatus.Destructing);

        Action destruct = composite.Destruct;

        destruct.Should().NotThrow("the container joins the decorator's in-flight destruct");
        dispatcher.RunUntil(() =>
            composite.Status == ConstructionStatus.Destructed &&
            decorator.Status == ConstructionStatus.Destructed &&
            childDestruct.IsCompleted);
        childDestruct.Status.Should().Be(TaskStatus.RanToCompletion);
        decorator.DestructAsyncCalls.Should().Be(1, "the joined decorator is not destructed again");
        childDestructs.Value.Should().Be(1);
    }

    /// <summary>
    /// A joined child whose destruct fails leaves the container Constructed and
    /// faults its DestructAsync with the child's error, exactly as when the
    /// container's walk started the child's destruct itself.
    /// </summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Composite_Surfaces_A_Failed_Child_Destruct_Whether_Joined_Or_Started(bool joined)
    {
        var dispatcher = new ManualDispatcher();
        var childDestructs = new Counter();
        var containerDestructs = new Counter();
        var failure = new InvalidOperationException("child destruct failed");
        var child = BackgroundChild(dispatcher, childDestructs, failure);
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [child])
            .OnDestruct(containerDestructs.Increment)
            .Build();
        _ = composite.ConstructAsync();
        dispatcher.RunUntil(() => composite.Status == ConstructionStatus.Constructed);
        var childDestruct = joined ? StartChildDestruct(child) : null;

        Task destruct = null!;
        Action start = () => destruct = composite.DestructAsync();

        start.Should().NotThrow("a background child's failure surfaces on the task");
        dispatcher.RunUntil(() => destruct.IsCompleted);

        var error = await Assert.ThrowsAsync<InvalidOperationException>(() => destruct);
        error.Should().BeSameAs(failure);
        composite.Status.Should().Be(ConstructionStatus.Constructed, "the container rolls back");
        child.Status.Should().Be(ConstructionStatus.Constructed, "the child rolls back");
        childDestructs.Value.Should().Be(1, "the child's OnDestruct runs once");
        containerDestructs.Value.Should().Be(0, "a failed walk runs no container onDestruct");
        if (childDestruct is not null)
            (await Assert.ThrowsAsync<InvalidOperationException>(() => childDestruct))
                .Should().BeSameAs(failure);
    }

    /// <summary>
    /// The synchronous <c>Destruct()</c> of a container joining a failing
    /// child does not throw: like a walk-started background child, the failure
    /// arrives after <c>Destruct()</c> returned and rolls the container back.
    /// </summary>
    [Fact]
    public void Group_Destruct_Rolls_Back_When_The_Joined_Child_Destruct_Fails()
    {
        var dispatcher = new ManualDispatcher();
        var childDestructs = new Counter();
        var failure = new InvalidOperationException("child destruct failed");
        var child = BackgroundChild(dispatcher, childDestructs, failure);
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("group")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [child])
            .Build();
        _ = group.ConstructAsync();
        dispatcher.RunUntil(() => group.Status == ConstructionStatus.Constructed);
        _ = StartChildDestruct(child);

        Action destruct = group.Destruct;

        destruct.Should().NotThrow();
        dispatcher.RunUntil(() =>
            group.Status == ConstructionStatus.Constructed &&
            child.Status == ConstructionStatus.Constructed &&
            group.CanDestruct());
        childDestructs.Value.Should().Be(1);
    }

    /// <summary>
    /// A child still Constructing is not joined by a destruct: every flavor's
    /// walk calls the child's destruct, which rejects the transient status, so
    /// the container rolls back and the child's construct is undisturbed.
    /// </summary>
    [Fact]
    public void Composite_Destruct_Rejects_A_Constructing_Child()
    {
        var dispatcher = new ManualDispatcher();
        var childDestructs = new Counter();
        var child = BackgroundChild(dispatcher, childDestructs);
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite")
            .Services(NullMessageHub.Instance, dispatcher)
            .Children(() => [child])
            .Build();
        _ = composite.ConstructAsync();
        dispatcher.RunUntil(() => composite.Status == ConstructionStatus.Constructed);
        var childDestruct = child.DestructAsync();
        dispatcher.RunUntil(() => childDestruct.IsCompleted);
        var childConstruct = child.ConstructAsync();
        child.Status.Should().Be(ConstructionStatus.Constructing);

        Action destruct = composite.Destruct;

        destruct.Should().Throw<StatusTransitionException>();
        composite.Status.Should().Be(ConstructionStatus.Constructed);
        dispatcher.RunUntil(() => childConstruct.IsCompleted);
        child.Status.Should().Be(ConstructionStatus.Constructed);
        childDestructs.Value.Should().Be(1);
    }
}
