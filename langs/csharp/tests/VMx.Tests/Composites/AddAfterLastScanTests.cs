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

namespace VMx.Tests.Composites;

/// <summary>
/// An add that reads Constructing after the construct walk's last late scan,
/// but before the container commits Constructed, starts its child. The
/// container must then reach Constructed only after that child (spec/02 §6,
/// spec/06 §5.1, #744). Both the foreground and the background queue their
/// work, so each test decides when the commit runs. Every wait is bounded.
/// </summary>
public class AddAfterLastScanTests
{
    private static readonly TimeSpan Bound = TimeSpan.FromSeconds(5);

    /// <summary>A scheduler that queues work until the test runs it.</summary>
    private sealed class WorkQueue : IScheduler
    {
        private readonly object _gate = new();
        private readonly List<Action> _work = new();

        public DateTimeOffset Now => DateTimeOffset.UtcNow;

        public int Count { get { lock (_gate) return _work.Count; } }

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

        /// <summary>Runs the oldest queued item; false when none is queued.</summary>
        public bool RunOne()
        {
            Action work;
            lock (_gate)
            {
                if (_work.Count == 0) return false;
                work = _work[0];
                _work.RemoveAt(0);
            }
            work();
            return true;
        }

        public void RunAll()
        {
            while (RunOne()) { }
        }
    }

    private sealed class QueuedDispatcher : IDispatcher
    {
        public WorkQueue Fg { get; } = new();
        public WorkQueue Bg { get; } = new();
        public IScheduler Foreground => Fg;
        public IScheduler Background => Bg;
    }

    private sealed class Harness
    {
        public required QueuedDispatcher Dispatcher { get; init; }
        public required TestHub Hub { get; init; }
        public required IComponentVM Root { get; init; }
        public required Action<ComponentVM> Add { get; init; }
        public required LateChildStarts LateStarts { get; init; }
        public List<string> Statuses { get; } = new();
        public ComponentVM? Late { get; set; }
        public ConstructionStatus? LateWhenRootConstructed { get; set; }
        public int LateRuns;
        public int SelectorRuns;
    }

    private static Harness Create(string kind, Action<Harness>? select = null)
    {
        var hub = new TestHub();
        var dispatcher = new QueuedDispatcher();
        var anchor = ComponentVM.Builder().Name("anchor").Services(hub, dispatcher).Background(true).Build();
        Harness? harness = null;
        if (kind == "composite")
        {
            var builder = CompositeVM<ComponentVM>.Builder()
                .Name("root").Services(hub, dispatcher).Children(() => [anchor]).AutoConstructOnAdd(true);
            if (select is not null)
            {
                builder = builder.Current(_ =>
                {
                    harness!.SelectorRuns++;
                    select(harness);
                    return null;
                });
            }
            var composite = builder.Build();
            harness = new Harness
            {
                Dispatcher = dispatcher,
                Hub = hub,
                Root = composite,
                Add = composite.Add,
                LateStarts = composite.LateStartsForTesting,
            };
        }
        else
        {
            var group = GroupVM<ComponentVM>.Builder()
                .Name("root").Services(hub, dispatcher).Children(() => [anchor]).AutoConstructOnAdd(true).Build();
            harness = new Harness
            {
                Dispatcher = dispatcher,
                Hub = hub,
                Root = group,
                Add = group.Add,
                LateStarts = group.LateStartsForTesting,
            };
        }
        var h = harness;
        hub.Messages.OfType<ConstructionStatusChangedMessage>().Subscribe(message =>
        {
            lock (h.Statuses) h.Statuses.Add($"{message.SenderName}:{message.Status}");
            if (message.SenderName == "root" && message.Status == ConstructionStatus.Constructed)
                h.LateWhenRootConstructed = h.Late?.Status;
        });
        return h;
    }

    private static ComponentVM Late(Harness h)
    {
        var late = ComponentVM.Builder().Name("late").Services(h.Hub, h.Dispatcher).Background(true)
            .OnConstruct(() => Interlocked.Increment(ref h.LateRuns)).Build();
        h.Late = late;
        return late;
    }

    /// <summary>Adds a background late child on this thread or another one.</summary>
    private static ConstructionStatus AddLate(Harness h, bool otherThread)
    {
        var late = Late(h);
        var seen = ConstructionStatus.Disposed;
        Exception? error = null;
        void Add()
        {
            seen = h.Root.Status;
            try { h.Add(late); }
            catch (Exception e) { error = e; }
        }
        if (otherThread)
        {
            var adder = new Thread(Add) { IsBackground = true };
            adder.Start();
            adder.Join(Bound).Should().BeTrue("the add completes");
        }
        else
        {
            Add();
        }
        error.Should().BeNull();
        return seen;
    }

    /// <summary>
    /// Settles the anchor, then runs foreground work one item at a time until
    /// the item that ran the walk's tail returns: its last scan, the selector
    /// (if any) and the commit step ran. A walk that ended has queued the
    /// container's Constructed commit on the foreground, not yet run.
    /// </summary>
    private static void RunWalkToQueuedCommit(Harness h)
    {
        var walkEnded = 0;
        var previous = h.LateStarts.ProbeForTesting;
        h.LateStarts.ProbeForTesting = (child, stage) =>
        {
            previous?.Invoke(child, stage);
            if (stage == LateChildStage.WalkEnded) Volatile.Write(ref walkEnded, 1);
        };
        h.Root.Construct();
        h.Root.Status.Should().Be(ConstructionStatus.Constructing);
        h.Dispatcher.Bg.RunAll(); // the anchor's hook; its Constructed goes to the foreground
        SpinWait.SpinUntil(
            () =>
            {
                h.Dispatcher.Fg.RunOne();
                return Volatile.Read(ref walkEnded) == 1 || h.SelectorRuns > 0;
            },
            Bound).Should().BeTrue("the construct walk reaches its tail");
        h.LateStarts.ProbeForTesting = previous;
    }

    /// <summary>Runs all work until the root and the late child settled.</summary>
    private static void Settle(Harness h)
    {
        SpinWait.SpinUntil(
            () =>
            {
                h.Dispatcher.Fg.RunAll();
                h.Dispatcher.Bg.RunAll();
                return h.Root.Status != ConstructionStatus.Constructing &&
                    !((ComponentVMBase)h.Root).HasInFlightLifecycleForTesting &&
                    h.Late?.Status != ConstructionStatus.Constructing;
            },
            Bound).Should().BeTrue("the root and the late child settle");
    }

    [Theory]
    [InlineData("composite", true)]
    [InlineData("composite", false)]
    [InlineData("group", true)]
    [InlineData("group", false)]
    public void Add_Before_The_Queued_Commit_Is_Joined_Or_Follows_Add_After_Constructed(
        string kind, bool otherThread)
    {
        var h = Create(kind);
        RunWalkToQueuedCommit(h);

        var seen = AddLate(h, otherThread);
        h.Late!.Status.Should().NotBe(ConstructionStatus.Destructed, "auto-construct started the child");
        h.Dispatcher.Fg.RunAll(); // the queued commit runs; the late child is still Constructing
        Settle(h);

        h.Root.Status.Should().Be(ConstructionStatus.Constructed);
        h.Late.Status.Should().Be(ConstructionStatus.Constructed);
        Volatile.Read(ref h.LateRuns).Should().Be(1);
        if (seen == ConstructionStatus.Constructing)
        {
            h.LateWhenRootConstructed.Should().Be(
                ConstructionStatus.Constructed,
                "an add that read Constructing makes the root wait for its child");
        }
        else
        {
            seen.Should().Be(ConstructionStatus.Constructed, "the add followed add-after-Constructed");
        }
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void Composite_Waits_For_A_Child_Its_Selector_Adds(bool otherThread)
    {
        ConstructionStatus? seen = null;
        var h = Create("composite", select: harness => seen ??= AddLate(harness, otherThread));
        RunWalkToQueuedCommit(h);
        seen.Should().Be(ConstructionStatus.Constructing, "the selector runs while the root is Constructing");

        h.Dispatcher.Fg.RunAll();
        h.Root.Status.Should().Be(ConstructionStatus.Constructing, "the root waits for the late child");
        Settle(h);

        h.Root.Status.Should().Be(ConstructionStatus.Constructed);
        h.LateWhenRootConstructed.Should().Be(ConstructionStatus.Constructed);
        lock (h.Statuses)
            h.Statuses.IndexOf("root:Constructed").Should().BeGreaterThan(h.Statuses.IndexOf("late:Constructed"));
        Volatile.Read(ref h.LateRuns).Should().Be(1);
        h.SelectorRuns.Should().Be(1, "the selector runs once");
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Add_After_The_Published_Constructed_Constructs_Before_Collection_Changed(string kind)
    {
        var h = Create(kind);
        RunWalkToQueuedCommit(h);
        Settle(h);
        h.Root.Status.Should().Be(ConstructionStatus.Constructed);

        var late = ComponentVM.Builder().Name("late").Services(h.Hub, h.Dispatcher).Build();
        ConstructionStatus? atChange = null;
        ((System.Collections.Specialized.INotifyCollectionChanged)h.Root).CollectionChanged +=
            (_, _) => atChange ??= late.Status;
        h.Add(late);

        atChange.Should().Be(ConstructionStatus.Constructed);
    }

    /// <summary>
    /// Runs <paramref name="inWindow"/> on the walk's thread right after the
    /// commit step committed Constructed and before the Constructed status is
    /// published, then settles the root.
    /// </summary>
    private static void InCommitWindow(Harness h, Action inWindow)
    {
        var ran = 0;
        h.LateStarts.ProbeForTesting = (_, stage) =>
        {
            if (stage != LateChildStage.WalkEnded || Interlocked.Exchange(ref ran, 1) == 1) return;
            lock (h.Statuses) h.Statuses.Should().NotContain("root:Constructed", "the commit is not yet published");
            inWindow();
        };
        h.Root.Construct();
        h.Dispatcher.Bg.RunAll();
        SpinWait.SpinUntil(
            () =>
            {
                h.Dispatcher.Fg.RunOne();
                return Volatile.Read(ref ran) == 1;
            },
            Bound).Should().BeTrue("the walk reaches its commit step");
        Settle(h);
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Construct_While_The_Commit_Is_Unpublished_Throws_Like_An_In_Flight_Construct(string kind)
    {
        var h = Create(kind);
        Exception? error = null;
        InCommitWindow(h, () =>
        {
            try { h.Root.Construct(); }
            catch (Exception e) { error = e; }
        });

        error.Should().BeOfType<StatusTransitionException>("the construct is still in flight");
        h.Root.Status.Should().Be(ConstructionStatus.Constructed);
        lock (h.Statuses) h.Statuses.Count(status => status == "root:Constructed").Should().Be(1);
        h.Root.Construct(); // a published Constructed stays idempotent
        lock (h.Statuses) h.Statuses.Count(status => status == "root:Constructed").Should().Be(1);
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Lifecycle_Predicates_Are_False_While_The_Commit_Is_Unpublished(string kind)
    {
        var h = Create(kind);
        bool[]? predicates = null;
        Exception? destructError = null;
        Exception? reconstructError = null;
        InCommitWindow(h, () =>
        {
            predicates = [h.Root.CanConstruct(), h.Root.CanDestruct(), h.Root.CanReconstruct()];
            try { h.Root.Destruct(); }
            catch (Exception e) { destructError = e; }
            try { h.Root.Reconstruct(); }
            catch (Exception e) { reconstructError = e; }
        });

        predicates.Should().Equal([false, false, false], "each predicate agrees with its operation");
        destructError.Should().BeOfType<StatusTransitionException>();
        reconstructError.Should().BeOfType<StatusTransitionException>();
        h.Root.Status.Should().Be(ConstructionStatus.Constructed);
        h.Root.CanDestruct().Should().BeTrue();
        h.Root.CanReconstruct().Should().BeTrue();
    }

    [Theory]
    [InlineData("component")]
    [InlineData("composite")]
    [InlineData("group")]
    public void ConstructAsync_From_A_Constructed_Subscriber_Completes_At_Once(string kind)
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        IComponentVM vm = kind switch
        {
            "component" => ComponentVM.Builder().Name("vm").Services(hub, dispatcher).Build(),
            "composite" => CompositeVM<ComponentVM>.Builder().Name("vm").Services(hub, dispatcher)
                .Children(() => [Member()]).AutoConstructOnAdd(true).Build(),
            _ => GroupVM<ComponentVM>.Builder().Name("vm").Services(hub, dispatcher)
                .Children(() => [Member()]).AutoConstructOnAdd(true).Build(),
        };
        ComponentVM Member() => ComponentVM.Builder().Name("member").Services(hub, dispatcher).Build();
        bool? completedAtOnce = null;
        hub.Messages.OfType<ConstructionStatusChangedMessage>().Subscribe(message =>
        {
            if (!ReferenceEquals(message.Sender, vm) || message.Status != ConstructionStatus.Constructed ||
                completedAtOnce is not null) return;
            var task = vm.ConstructAsync();
            completedAtOnce = task.IsCompleted && task.Wait(Bound);
        });

        vm.Construct();

        completedAtOnce.Should().BeTrue("a Constructed subscriber sees a completed transition");
    }
}
