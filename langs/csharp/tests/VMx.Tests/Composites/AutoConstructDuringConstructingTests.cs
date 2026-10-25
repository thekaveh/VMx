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
        Action<ComponentVM> Add,
        LateChildStarts LateStarts);

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
            return new Setup(dispatcher, hub, first, composite, composite.Add,
                composite.LateStartsForTesting);
        }
        var group = GroupVM<ComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher).Children(() => [first])
            .AutoConstructOnAdd(autoConstruct).Build();
        return new Setup(dispatcher, hub, first, group, group.Add, group.LateStartsForTesting);
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

    private static readonly TimeSpan Bound = TimeSpan.FromSeconds(5);

    /// <summary>Records each status a component publishes, in order.</summary>
    private static List<string> RecordStatuses(Setup setup)
    {
        var statuses = new List<string>();
        setup.Hub.Messages.OfType<ConstructionStatusChangedMessage>().Subscribe(message =>
        {
            lock (statuses) statuses.Add($"{message.SenderName}:{message.Status}");
        });
        return statuses;
    }

    /// <summary>
    /// Adds <paramref name="late"/> from another thread. That add (or the late
    /// child's construct, which runs on the adder thread) pauses: the test
    /// waits for <paramref name="paused"/>, then settles the original child,
    /// so the construct walk pulls <paramref name="late"/> while the add is
    /// paused. Every wait is bounded.
    /// </summary>
    private static Exception? AddWhileWalkPulls(Setup setup, ComponentVM late, ManualResetEventSlim paused)
    {
        Exception? addError = null;
        var adder = new Thread(() =>
        {
            try { setup.Add(late); }
            catch (Exception error) { addError = error; }
        })
        { IsBackground = true };
        adder.Start();
        paused.Wait(Bound).Should().BeTrue("the add pauses before the late child settles");
        setup.Dispatcher.RunFirst(); // the original child settles; the walk pulls `late`
        adder.Join(Bound).Should().BeTrue("the paused add resumes and completes");
        Settle(setup);
        return addError;
    }

    /// <summary>
    /// Pauses the add of <paramref name="late"/> after it attached the
    /// Destructed child and before it starts it, until the walk waits for
    /// that add (or the root left Constructing). Returns the pause signal.
    /// </summary>
    private static ManualResetEventSlim PauseAddUntilWalkWaits(
        Setup setup, ComponentVM late, Func<bool> walkWaiting)
    {
        var paused = new ManualResetEventSlim();
        var previous = setup.LateStarts.ProbeForTesting;
        setup.LateStarts.ProbeForTesting = (child, stage) =>
        {
            previous?.Invoke(child, stage);
            if (!ReferenceEquals(child, late) || stage != LateChildStage.Attached) return;
            setup.Root.Status.Should().Be(ConstructionStatus.Constructing);
            late.Status.Should().Be(ConstructionStatus.Destructed);
            paused.Set();
            SpinWait.SpinUntil(
                () => walkWaiting() || setup.Root.Status != ConstructionStatus.Constructing, Bound);
        };
        return paused;
    }

    /// <summary>Records whether the walk waited for the add of <paramref name="late"/>.</summary>
    private static Func<bool> RecordWalkWaiting(Setup setup, ComponentVM late)
    {
        var waiting = 0;
        setup.LateStarts.ProbeForTesting = (child, stage) =>
        {
            if (ReferenceEquals(child, late) && stage == LateChildStage.WalkWaitingOnAdd)
                Volatile.Write(ref waiting, 1);
        };
        return () => Volatile.Read(ref waiting) == 1;
    }

    private static void ShouldReachConstructedAfterLate(Setup setup, ComponentVM late, List<string> statuses)
    {
        setup.Root.Status.Should().Be(ConstructionStatus.Constructed);
        late.Status.Should().Be(ConstructionStatus.Constructed);
        lock (statuses)
        {
            var lateConstructed = statuses.IndexOf("late:Constructed");
            lateConstructed.Should().BeGreaterThanOrEqualTo(0);
            statuses.IndexOf("root:Constructed").Should().BeGreaterThan(lateConstructed);
            statuses.Count(status => status == "late:Constructing").Should().Be(1);
        }
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Walk_Waits_For_The_Adds_Start_Attempt_Then_Joins(string kind)
    {
        var setup = Create(kind);
        var statuses = RecordStatuses(setup);
        setup.Root.Construct();
        var runs = 0;
        var late = Child(setup, "late", background: false, () => Interlocked.Increment(ref runs));
        var walkWaiting = RecordWalkWaiting(setup, late);
        using var paused = PauseAddUntilWalkWaits(setup, late, walkWaiting);

        var addError = AddWhileWalkPulls(setup, late, paused);

        addError.Should().BeNull();
        ShouldReachConstructedAfterLate(setup, late, statuses);
        walkWaiting().Should().BeTrue("the walk pulled the child before its add started it");
        Volatile.Read(ref runs).Should().Be(1, "only the add starts the child");
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Walk_Joins_A_Late_Child_Its_Add_Is_Starting(string kind)
    {
        var setup = Create(kind);
        var statuses = RecordStatuses(setup);
        setup.Root.Construct();
        var runs = 0;
        using var paused = new ManualResetEventSlim();
        ComponentVM? late = null;
        Func<bool> walkWaiting = () => false;
        late = Child(setup, "late", background: false, () =>
        {
            Interlocked.Increment(ref runs);
            paused.Set();
            // The add started the child; hold its construct until the walk
            // waits for the add (or a bounded time on a walk that joins it).
            SpinWait.SpinUntil(
                () => walkWaiting() || setup.Root.Status != ConstructionStatus.Constructing, Bound);
        });
        walkWaiting = RecordWalkWaiting(setup, late);

        var addError = AddWhileWalkPulls(setup, late, paused);

        addError.Should().BeNull();
        ShouldReachConstructedAfterLate(setup, late, statuses);
        Volatile.Read(ref runs).Should().Be(1, "only the add starts the child");
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Failed_Add_Started_Late_Child_Undoes_The_Add_And_Rolls_Back(string kind)
    {
        var setup = Create(kind);
        setup.Root.Construct();
        var runs = 0;
        var late = Child(setup, "late", background: false, () =>
        {
            Interlocked.Increment(ref runs);
            throw new InvalidOperationException("late failed");
        });
        var walkWaiting = RecordWalkWaiting(setup, late);
        using var paused = PauseAddUntilWalkWaits(setup, late, walkWaiting);

        var addError = AddWhileWalkPulls(setup, late, paused);

        addError.Should().BeOfType<InvalidOperationException>("the add's own construct failed");
        ((IEnumerable<IComponentVM>)setup.Root).Should().NotContain(late, "the failed add is undone");
        setup.Root.Status.Should().Be(ConstructionStatus.Destructed, "the walk waited on the failing child");
        late.Status.Should().Be(ConstructionStatus.Destructed);
        Volatile.Read(ref runs).Should().Be(1);
    }

    private sealed class ThrowOnceComposite(IMessageHub hub, IDispatcher dispatcher)
        : CompositeVMBase<ComponentVM>("root", hub, dispatcher, autoConstructOnAdd: true)
    {
        private bool _throwNext = true;

        public override ViewModelType Type => ViewModelType.Composite;

        protected override void OnConstruct()
        {
            base.OnConstruct();
            if (!_throwNext) return;
            _throwNext = false;
            throw new InvalidOperationException("the hook throws after its walk deferred");
        }
    }

    private sealed class ThrowOnceGroup(IMessageHub hub, IDispatcher dispatcher)
        : GroupVMBase<ComponentVM>("root", hub, dispatcher, autoConstructOnAdd: true)
    {
        private bool _throwNext = true;

        public override ViewModelType Type => ViewModelType.Group;

        protected override void OnConstruct()
        {
            base.OnConstruct();
            if (!_throwNext) return;
            _throwNext = false;
            throw new InvalidOperationException("the hook throws after its walk deferred");
        }
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Abandoned_Walk_Never_Takes_Or_Clears_The_Next_Walks_Records(string kind)
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = ComponentVM.Builder().Name("first").Services(hub, dispatcher).Background(true).Build();
        var second = ComponentVM.Builder().Name("second").Services(hub, dispatcher).Background(true).Build();
        Setup setup;
        if (kind == "composite")
        {
            var composite = new ThrowOnceComposite(hub, dispatcher);
            composite.Add(first);
            composite.Add(second);
            setup = new Setup(dispatcher, hub, first, composite, composite.Add, composite.LateStartsForTesting);
        }
        else
        {
            var group = new ThrowOnceGroup(hub, dispatcher);
            group.Add(first);
            group.Add(second);
            setup = new Setup(dispatcher, hub, first, group, group.Add, group.LateStartsForTesting);
        }
        var statuses = RecordStatuses(setup);
        var walksEnded = 0;

        // Walk 1 waits on `first`, then the hook throws: the walk is abandoned
        // and the root rolls back with `first` still Constructing.
        var firstConstruct = () => setup.Root.Construct();
        firstConstruct.Should().Throw<InvalidOperationException>();
        setup.Root.Status.Should().Be(ConstructionStatus.Destructed);
        first.Status.Should().Be(ConstructionStatus.Constructing);

        // Walk 2 joins `first`. A late child added from another thread
        // registers its start record in walk 2's scope and pauses before it
        // starts the child, until walk 2 waits for it.
        setup.Root.Construct();
        setup.Root.Status.Should().Be(ConstructionStatus.Constructing);
        var runs = 0;
        var late = Child(setup, "late", background: false, () => Interlocked.Increment(ref runs));
        var walkWaiting = RecordWalkWaiting(setup, late);
        var recordWalks = setup.LateStarts.ProbeForTesting;
        setup.LateStarts.ProbeForTesting = (child, stage) =>
        {
            recordWalks?.Invoke(child, stage);
            if (stage == LateChildStage.WalkEnded) Interlocked.Increment(ref walksEnded);
        };
        using var paused = PauseAddUntilWalkWaits(setup, late, walkWaiting);
        Exception? addError = null;
        var adder = new Thread(() =>
        {
            try { setup.Add(late); }
            catch (Exception error) { addError = error; }
        })
        { IsBackground = true };
        adder.Start();
        paused.Wait(Bound).Should().BeTrue("the add pauses after it registered its record");

        // `first` settles and both walks resume: the abandoned walk 1 ends
        // (its stale path runs), and walk 2 starts `second`.
        setup.Dispatcher.RunFirst();
        SpinWait.SpinUntil(() => Volatile.Read(ref walksEnded) >= 1, Bound)
            .Should().BeTrue("the abandoned walk ends");
        SpinWait.SpinUntil(() => second.Status == ConstructionStatus.Constructing, Bound)
            .Should().BeTrue("walk 2 starts the next snapshot child");

        // `second` settles: walk 2 pulls `late` and must find its record.
        setup.Dispatcher.RunFirst();
        adder.Join(Bound).Should().BeTrue("the paused add resumes and completes");
        Settle(setup);

        addError.Should().BeNull();
        ShouldReachConstructedAfterLate(setup, late, statuses);
        walkWaiting().Should().BeTrue("walk 2 waited for the add's start attempt");
        Volatile.Read(ref runs).Should().Be(1);
    }
}
