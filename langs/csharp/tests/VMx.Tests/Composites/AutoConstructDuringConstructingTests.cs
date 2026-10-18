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

namespace VMx.Tests.Composites;

/// <summary>
/// A container's construct completes only when every child has reached
/// Constructed (spec/02 §6). With <c>AutoConstructOnAdd(true)</c>, a child
/// added while the container waits on a background child is constructed at
/// add time and joined by the child walk, so the container never reports
/// Constructed with an unconstructed added child. Mirrors the Python and
/// TypeScript tests.
/// </summary>
public class AutoConstructDuringConstructingTests
{
    /// <summary>Queues background work so a test decides when each item runs.</summary>
    private sealed class QueueDispatcher : IDispatcher, IScheduler
    {
        private readonly object _gate = new();
        private readonly List<Action> _work = new();

        public List<Exception> Errors { get; } = new();
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
                var index = first ? 0 : _work.Count - 1;
                work = _work[index];
                _work.RemoveAt(index);
            }
            try { work(); }
            catch (Exception error) { lock (_gate) Errors.Add(error); }
        }
    }

    private sealed record Setup(
        QueueDispatcher Dispatcher,
        TestHub Hub,
        ComponentVM First,
        IComponentVM Root,
        Action<ComponentVM> Add);

    private static Setup Create(string kind, bool autoConstruct = true)
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = ComponentVM.Builder().Name("first").Services(hub, dispatcher).Background(true).Build();
        if (kind == "composite")
        {
            var composite = CompositeVM<ComponentVM>.Builder()
                .Name("root").Services(hub, dispatcher).Children(() => [first])
                .AutoConstructOnAdd(autoConstruct).Build();
            return new Setup(dispatcher, hub, first, composite, composite.Add);
        }
        var group = GroupVM<ComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher).Children(() => [first])
            .AutoConstructOnAdd(autoConstruct).Build();
        return new Setup(dispatcher, hub, first, group, group.Add);
    }

    private static ComponentVM Child(Setup setup, string name, bool background, Action? onConstruct = null)
    {
        var builder = ComponentVM.Builder().Name(name).Services(setup.Hub, setup.Dispatcher).Background(background);
        if (onConstruct is not null) builder = builder.OnConstruct(onConstruct);
        return builder.Build();
    }

    /// <summary>Drains background work until the root leaves Constructing.</summary>
    private static void Settle(Setup setup)
    {
        SpinWait.SpinUntil(
            () =>
            {
                setup.Dispatcher.RunAll();
                return setup.Root.Status != ConstructionStatus.Constructing;
            },
            TimeSpan.FromSeconds(5)).Should().BeTrue();
        setup.Dispatcher.RunAll();
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Foreground_Child_Added_During_Background_Wait_Is_Constructed(string kind)
    {
        var setup = Create(kind);
        setup.Root.Construct();
        setup.Root.Status.Should().Be(ConstructionStatus.Constructing);

        var late = Child(setup, "late", background: false);
        setup.Add(late);
        late.Status.Should().Be(ConstructionStatus.Constructed);

        Settle(setup);
        setup.Root.Status.Should().Be(ConstructionStatus.Constructed);
        late.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Container_Waits_For_Late_Background_Child(string kind)
    {
        var setup = Create(kind);
        setup.Root.Construct();
        var late = Child(setup, "late", background: true);
        setup.Add(late);
        late.Status.Should().Be(ConstructionStatus.Constructing);

        setup.Dispatcher.RunFirst(); // only the original child settles
        SpinWait.SpinUntil(() => setup.First.Status == ConstructionStatus.Constructed, TimeSpan.FromSeconds(5));
        Thread.Sleep(50); // give an (incorrect) early completion time to land
        late.Status.Should().Be(ConstructionStatus.Constructing);
        setup.Root.Status.Should().Be(ConstructionStatus.Constructing);

        Settle(setup);
        late.Status.Should().Be(ConstructionStatus.Constructed);
        setup.Root.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Failed_Late_Child_Rolls_Back_Without_Rerunning(string kind)
    {
        var setup = Create(kind);
        setup.Root.Construct();
        var runs = 0;
        var late = Child(setup, "late", background: true, () =>
        {
            Interlocked.Increment(ref runs);
            throw new InvalidOperationException("late failed");
        });
        setup.Add(late);
        setup.Dispatcher.RunLast(); // the late child fails first
        late.Status.Should().Be(ConstructionStatus.Destructed);

        Settle(setup);
        Volatile.Read(ref runs).Should().Be(1, "a late auto-constructed child is joined, never restarted");
        setup.Root.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Without_Auto_Construct_Late_Child_Is_Left_Alone(string kind)
    {
        var setup = Create(kind, autoConstruct: false);
        setup.Root.Construct();
        var late = Child(setup, "late", background: false);
        setup.Add(late);

        Settle(setup);
        setup.Root.Status.Should().Be(ConstructionStatus.Constructed);
        late.Status.Should().Be(ConstructionStatus.Destructed);
    }
}
