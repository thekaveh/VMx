using System.Collections.Concurrent;
using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using FluentAssertions;
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
/// Opt-in reverse child destruct order (spec/02 §6, spec/06 §5, spec/07 §2,
/// ADR-0161): GRP-014 and COMP-046. With <see cref="ChildOrder.Reverse"/>,
/// destruct (including the destruct phase of reconstruct) and dispose walk the
/// children last-first, construct stays in child order, and every child is
/// disposed before the parent publishes Disposed (LIFE-013). The default keeps
/// child order.
/// </summary>
public class GRP_014_COMP_046_ReverseDestructOrder_Tests
{
    private static readonly TestDispatcher Dispatcher = new();
    private static readonly string[] Names = ["a", "b", "c"];

    private static ComponentVM<string> Child(MessageHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, Dispatcher).Model(name).Build();

    /// <summary>Records each settled status message as "status:name".</summary>
    private static List<string> Record(MessageHub hub)
    {
        var log = new List<string>();
        hub.Messages.OfType<ConstructionStatusChangedMessage>()
            .Where(m => m.Status is ConstructionStatus.Constructed
                or ConstructionStatus.Destructed or ConstructionStatus.Disposed)
            .Subscribe(m => log.Add($"{m.Status}:{m.SenderName}"));
        return log;
    }

    private static string[] Expect(ConstructionStatus status, string[] children, string parent)
        => children.Append(parent).Select(name => $"{status}:{name}").ToArray();

    /// <summary>
    /// Drives construct, destruct, reconstruct and dispose on <paramref name="parent"/>
    /// and checks the child order of each phase against <paramref name="order"/>.
    /// </summary>
    private static void AssertOrder(
        MessageHub hub, IComponentVM parent, List<string> log, ChildOrder order)
    {
        var forward = Names;
        var teardown = order == ChildOrder.Reverse ? Enumerable.Reverse(Names).ToArray() : Names;

        parent.Construct();
        log.Should().Equal(Expect(ConstructionStatus.Constructed, forward, parent.Name));

        log.Clear();
        parent.Destruct();
        log.Should().Equal(Expect(ConstructionStatus.Destructed, teardown, parent.Name));

        parent.Construct();
        log.Clear();
        parent.Reconstruct();
        log.Should().Equal(
            Expect(ConstructionStatus.Destructed, teardown, parent.Name)
                .Concat(Expect(ConstructionStatus.Constructed, forward, parent.Name)));

        log.Clear();
        parent.Dispose();
        // Depth-first (LIFE-013): every child is Disposed before the parent.
        log.Should().Equal(Expect(ConstructionStatus.Disposed, teardown, parent.Name));
        hub.Dispose();
    }

    // ── GRP-014 — GroupVM destructs and disposes children in reverse order ──

    [Theory, Trait("Conformance", "GRP-014")]
    [InlineData(ChildOrder.Reverse)]
    [InlineData(ChildOrder.Insertion)]
    public void GRP_014_Group_DestructOrder_Builder(ChildOrder order)
    {
        var hub = new MessageHub();
        var builder = GroupVM<ComponentVM<string>>.Builder()
            .Name("group").Services(hub, Dispatcher)
            .Children(() => Names.Select(name => Child(hub, name)).ToArray());
        if (order == ChildOrder.Reverse) builder = builder.DestructOrder(ChildOrder.Reverse);
        var log = Record(hub);

        AssertOrder(hub, builder.Build(), log, order);
    }

    [Fact, Trait("Conformance", "GRP-014")]
    public void GRP_014_Group_DestructOrder_Options()
    {
        var hub = new MessageHub();
        var group = GroupVM<ComponentVM<string>>.Create(new GroupVMOptions<ComponentVM<string>>
        {
            Name = "group",
            Hub = hub,
            Dispatcher = Dispatcher,
            Children = () => Names.Select(name => Child(hub, name)).ToArray(),
            DestructOrder = ChildOrder.Reverse,
        });
        var log = Record(hub);

        AssertOrder(hub, group, log, ChildOrder.Reverse);
    }

    // ── COMP-046 — CompositeVM destructs and disposes children in reverse order ──

    [Theory, Trait("Conformance", "COMP-046")]
    [InlineData(ChildOrder.Reverse)]
    [InlineData(ChildOrder.Insertion)]
    public void COMP_046_Composite_DestructOrder_Builder(ChildOrder order)
    {
        var hub = new MessageHub();
        var builder = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, Dispatcher)
            .Children(() => Names.Select(name => Child(hub, name)).ToArray())
            // A current child is cleared before the children are destructed;
            // COMP_046_Reverse_Clears_Current_Before_The_First_Child_Destructs
            // checks it.
            .Current(children => children.Last());
        if (order == ChildOrder.Reverse) builder = builder.DestructOrder(ChildOrder.Reverse);
        var log = Record(hub);

        AssertOrder(hub, builder.Build(), log, order);
    }

    [Fact, Trait("Conformance", "COMP-046")]
    public void COMP_046_Composite_DestructOrder_Options()
    {
        var hub = new MessageHub();
        var composite = CompositeVM<ComponentVM<string>>.Create(
            new CompositeVMOptions<ComponentVM<string>>
            {
                Name = "composite",
                Hub = hub,
                Dispatcher = Dispatcher,
                Children = () => Names.Select(name => Child(hub, name)).ToArray(),
                DestructOrder = ChildOrder.Reverse,
            });
        var log = Record(hub);

        AssertOrder(hub, composite, log, ChildOrder.Reverse);
    }

    [Theory, Trait("Conformance", "COMP-046")]
    [InlineData(ChildOrder.Reverse)]
    [InlineData(ChildOrder.Insertion)]
    public void COMP_046_ModeledComposite_DestructOrder_Builder(ChildOrder order)
    {
        var hub = new MessageHub();
        var builder = CompositeVMOfM<string, ComponentVM<string>>.Builder()
            .Name("modeled").Services(hub, Dispatcher)
            .ChildrenModels(() => Names)
            .ChildModelToChildViewModel(name => Child(hub, name));
        if (order == ChildOrder.Reverse) builder = builder.DestructOrder(ChildOrder.Reverse);
        var log = Record(hub);

        AssertOrder(hub, builder.Build(), log, order);
    }

    [Fact, Trait("Conformance", "COMP-046")]
    public void COMP_046_Reverse_Clears_Current_Before_The_First_Child_Destructs()
    {
        var hub = new MessageHub();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, Dispatcher)
            .Children(() => Names.Select(name => Child(hub, name)).ToArray())
            .Current(children => children.Last())
            .DestructOrder(ChildOrder.Reverse)
            .Build();
        composite.Construct();
        composite.Current.Should().NotBeNull();
        var currentAtFirstDestructing = new List<ComponentVM<string>?>();
        using var probe = hub.Messages.OfType<ConstructionStatusChangedMessage>()
            .Where(m => m.Status == ConstructionStatus.Destructing && m.SenderName != composite.Name)
            .Subscribe(_ =>
            {
                if (currentAtFirstDestructing.Count == 0)
                    currentAtFirstDestructing.Add(composite.Current);
            });
        var log = Record(hub);

        composite.Destruct();

        currentAtFirstDestructing.Should().Equal([null], "Current is cleared before the first child destructs");
        log.Should().Equal(Expect(ConstructionStatus.Destructed, ["c", "b", "a"], composite.Name));
        hub.Dispose();
    }

    // ── Background children: the walk waits for each child before the next ──

    /// <summary>A scheduler whose queued work runs only when a test drains it.</summary>
    private sealed class ManualScheduler : IScheduler
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

        public int Pending => _queue.Count;

        /// <summary>Runs the work queued so far, in order.</summary>
        public void RunPending()
        {
            for (var count = _queue.Count; count > 0 && _queue.TryDequeue(out var work); count--)
                work();
        }

        /// <summary>
        /// Runs queued work until <paramref name="done"/> holds. A walk resumes
        /// through a pool thread, so an empty queue alone does not mean the walk
        /// has finished.
        /// </summary>
        public void RunUntil(Func<bool> done)
        {
            var deadline = DateTime.UtcNow + HangGuard;
            while (!done())
            {
                if (DateTime.UtcNow > deadline) throw new TimeoutException("the condition did not hold");
                RunPending();
                Thread.Sleep(1);
            }
        }
    }

    private static void AssertBackgroundWaits(
        Func<MessageHub, IDispatcher, IEnumerable<ComponentVM<string>>, IComponentVM> make)
    {
        var background = new ManualScheduler();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, background);
        var hub = new MessageHub();
        var children = Names
            .Select(name => ComponentVM<string>.Builder()
                .Name(name).Services(hub, dispatcher).Model(name).Background(true).Build())
            .ToArray();
        var parent = make(hub, dispatcher, children);
        var construct = parent.ConstructAsync();
        // The walk resumes on a pool thread, so wait for the whole construct.
        background.RunUntil(() => construct.IsCompleted);
        construct.Status.Should().Be(TaskStatus.RanToCompletion);
        parent.Status.Should().Be(ConstructionStatus.Constructed);
        var log = Record(hub);

        parent.Destruct();

        // The walk starts only the last child and waits for it to settle.
        children.Select(child => child.Status).Should().Equal(
            ConstructionStatus.Constructed, ConstructionStatus.Constructed, ConstructionStatus.Destructing);
        var vm = (ComponentVMBase)parent;
        background.RunUntil(() =>
            parent.Status == ConstructionStatus.Destructed && !vm.HasInFlightLifecycleForTesting);
        log.Should().Equal(Expect(ConstructionStatus.Destructed, ["c", "b", "a"], parent.Name));
        hub.Dispose();
    }

    [Fact, Trait("Conformance", "GRP-014")]
    public void GRP_014_Reverse_Waits_For_Background_Children_Last_First()
        => AssertBackgroundWaits((hub, dispatcher, children) => GroupVM<ComponentVM<string>>.Builder()
            .Name("group").Services(hub, dispatcher)
            .Children(() => children)
            .DestructOrder(ChildOrder.Reverse)
            .Build());

    [Fact, Trait("Conformance", "COMP-046")]
    public void COMP_046_Reverse_Waits_For_Background_Children_Last_First()
        => AssertBackgroundWaits((hub, dispatcher, children) => CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, dispatcher)
            .Children(() => children)
            .Current(items => items.Last())
            .DestructOrder(ChildOrder.Reverse)
            .Build());
}
