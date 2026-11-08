using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Composites;

/// <summary>
/// Selection commits without a membership transaction (spec/06 §4.3, §5,
/// ADR-0173). Another thread's transaction neither fails nor delays a
/// selection (#1145). A child that an add or population attached but has not
/// admitted is not a member for selection (#1146, #1148). The owner thread
/// cannot select before its transaction commits. A non-null selection is
/// refused while disposal is pending, and a null clear is not. The destruct
/// clear is never refused (#1144).
/// </summary>
public sealed class SelectionWithoutTransactionTests
{
    /// <summary>A dispatcher whose queued schedulers run only when a test drains them.</summary>
    private sealed class QueueDispatcher : IDispatcher
    {
        public QueueDispatcher(bool queueForeground = false)
        {
            Background = BackgroundQueue;
            Foreground = queueForeground ? ForegroundQueue : ImmediateScheduler.Instance;
        }

        public Queue BackgroundQueue { get; } = new();

        public Queue ForegroundQueue { get; } = new();

        public IScheduler Foreground { get; }

        public IScheduler Background { get; }

        public void RunAll()
        {
            ForegroundQueue.RunAll();
            BackgroundQueue.RunAll();
        }

        public sealed class Queue : IScheduler
        {
            private readonly object _gate = new();
            private readonly List<Action> _work = new();

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

            public void RunAll()
            {
                while (true)
                {
                    Action work;
                    lock (_gate)
                    {
                        if (_work.Count == 0) return;
                        work = _work[0];
                        _work.RemoveAt(0);
                    }
                    work();
                }
            }
        }
    }

    /// <summary>A composite with recorders for its Current changes.</summary>
    private sealed class Root
    {
        private readonly List<string?> _changes = new();
        private int _currentMessages;

        public Root(
            TestHub hub,
            IDispatcher dispatcher,
            Func<IEnumerable<ComponentVM>> children,
            bool autoConstructOnAdd = true,
            bool asyncSelection = false,
            bool selectFirst = false,
            Action<ComponentVM?>? onCurrent = null)
        {
            var builder = CompositeVM<ComponentVM>.Builder()
                .Name("root").Services(hub, dispatcher).Children(children)
                .AutoConstructOnAdd(autoConstructOnAdd)
                .AsyncSelection(asyncSelection)
                .OnCurrentChanged(value =>
                {
                    lock (_changes) _changes.Add(value?.Name);
                    onCurrent?.Invoke(value);
                });
            if (selectFirst) builder = builder.Current(kids => kids.FirstOrDefault());
            Vm = builder.Build();
            hub.Messages.Subscribe(message =>
            {
                if (message is IPropertyChangedMessage<object> property &&
                    ReferenceEquals(property.SenderObject, Vm) && property.PropertyName == "Current")
                    Interlocked.Increment(ref _currentMessages);
            });
        }

        public CompositeVM<ComponentVM> Vm { get; }

        public IReadOnlyList<string?> Changes { get { lock (_changes) return _changes.ToArray(); } }

        public int CurrentMessages => Volatile.Read(ref _currentMessages);

        public void ResetRecords()
        {
            lock (_changes) _changes.Clear();
            Volatile.Write(ref _currentMessages, 0);
        }
    }

    private static ComponentVM Child(
        TestHub hub, IDispatcher dispatcher, string name, Action? onConstruct = null, bool background = false)
    {
        var builder = ComponentVM.Builder().Name(name).Services(hub, dispatcher).Background(background);
        if (onConstruct is not null) builder = builder.OnConstruct(onConstruct);
        return builder.Build();
    }

    private static Thread Start(Action action, List<Exception> errors)
    {
        var thread = new Thread(() =>
        {
            try { action(); }
            catch (Exception error) { lock (errors) errors.Add(error); }
        })
        { IsBackground = true };
        thread.Start();
        return thread;
    }

    /// <summary>
    /// Starts <c>Add(late)</c> on a worker that parks in the add's own
    /// CollectionChanged publication, while it still holds the transaction.
    /// </summary>
    private sealed class ParkedAdd : IDisposable
    {
        private readonly ManualResetEventSlim _inHandler = new(false);
        private readonly ManualResetEventSlim _release = new(false);
        private readonly Thread _worker;

        public ParkedAdd(CompositeVM<ComponentVM> root, ComponentVM late, Func<bool>? waitInHandler = null)
        {
            var main = Environment.CurrentManagedThreadId;
            root.CollectionChanged += (_, _) =>
            {
                if (Environment.CurrentManagedThreadId == main) return;
                _inHandler.Set();
                if (waitInHandler is not null) HandlerWaitSucceeded = waitInHandler();
                else _release.Wait(HangGuard * 2);
            };
            _worker = Start(() => root.Add(late), Errors);
            _inHandler.Wait(HangGuard).Should().BeTrue();
            root.MembershipTransactionActiveForTesting.Should().BeTrue();
        }

        public List<Exception> Errors { get; } = new();

        public bool HandlerWaitSucceeded { get; private set; }

        public void Finish()
        {
            _release.Set();
            _worker.Join(HangGuard * 3).Should().BeTrue();
            lock (Errors) Errors.Should().BeEmpty();
        }

        public void Dispose()
        {
            _release.Set();
            _worker.Join(HangGuard * 3);
            _inHandler.Dispose();
            _release.Dispose();
        }
    }

    // ── #1144: the destruct clear ────────────────────────────────────────────

    [Theory]
    [InlineData("destruct", false)]
    [InlineData("destruct", true)]
    [InlineData("reconstruct", false)]
    public void Destruct_Clears_Current_While_Another_Thread_Holds_A_Transaction(
        string operation, bool ownerWaitsForDestruct)
    {
        var hub = new TestHub();
        var first = Child(hub, NullDispatcher.Instance, "first");
        var late = Child(hub, NullDispatcher.Instance, "late");
        var root = new Root(hub, NullDispatcher.Instance, () => [first], selectFirst: true);
        root.Vm.Construct();
        root.Vm.Current.Should().BeSameAs(first);

        using var add = new ParkedAdd(root.Vm, late, ownerWaitsForDestruct
            ? () => SpinWait.SpinUntil(() => root.Vm.Status == ConstructionStatus.Destructed, HangGuard)
            : null);
        if (operation == "destruct") root.Vm.Destruct();
        else root.Vm.Reconstruct();

        if (operation == "destruct")
        {
            root.Vm.Status.Should().Be(ConstructionStatus.Destructed);
            root.Vm.Current.Should().BeNull();
            first.IsCurrent.Should().BeFalse();
            root.Changes.Should().Equal("first", null);
        }
        else
        {
            root.Vm.Status.Should().Be(ConstructionStatus.Constructed);
            root.Vm.Current.Should().BeSameAs(first); // the selector ran again
            root.Changes.Should().Equal("first", null, "first");
        }
        add.Finish();
        if (ownerWaitsForDestruct) add.HandlerWaitSucceeded.Should().BeTrue();
    }

    [Fact]
    public void Destruct_Clears_Current_While_Disposal_Is_Deferred()
    {
        var hub = new TestHub();
        var a = Child(hub, NullDispatcher.Instance, "a");
        Root? root = null;
        var seen = new List<(ConstructionStatus Status, ComponentVM? Current)>();
        root = new Root(hub, NullDispatcher.Instance, () => [a], onCurrent: value =>
        {
            if (value is null) return;
            root!.Vm.Dispose(); // deferred: this thread publishes under the lease
            root.Vm.Destruct();
            seen.Add((root.Vm.Status, root.Vm.Current));
        });
        root.Vm.Construct();

        root.Vm.Current = a;

        seen.Should().Equal((ConstructionStatus.Destructed, (ComponentVM?)null));
        a.IsCurrent.Should().BeFalse();
        root.Changes.Should().Equal("a", null);
        root.Vm.Status.Should().Be(ConstructionStatus.Disposed); // the lease end admitted the disposal
    }

    [Fact]
    public void Dispose_From_The_Destruct_Clear_Callback_Is_Deferred()
    {
        var hub = new TestHub();
        var a = Child(hub, NullDispatcher.Instance, "a");
        Root? root = null;
        var seen = new List<ConstructionStatus>();
        root = new Root(hub, NullDispatcher.Instance, () => [a], selectFirst: true, onCurrent: value =>
        {
            if (value is not null) return;
            root!.Vm.Dispose();
            seen.Add(root.Vm.Status);
        });
        root.Vm.Construct();

        root.Vm.Destruct();

        seen.Should().Equal(ConstructionStatus.Destructing); // the lease deferred the disposal
        root.Vm.Current.Should().BeNull();
        SpinWait.SpinUntil(() => root.Vm.Status == ConstructionStatus.Disposed, HangGuard).Should().BeTrue();
    }

    [Fact]
    public void Destruct_From_The_Own_Add_Publication_Clears_Current()
    {
        var hub = new TestHub();
        var first = Child(hub, NullDispatcher.Instance, "first");
        var late = Child(hub, NullDispatcher.Instance, "late");
        var root = new Root(hub, NullDispatcher.Instance, () => [first], selectFirst: true);
        root.Vm.Construct();
        root.Vm.CollectionChanged += (_, _) => root.Vm.Destruct();

        root.Vm.Add(late);

        root.Vm.Status.Should().Be(ConstructionStatus.Destructed);
        root.Vm.Current.Should().BeNull();
        first.IsCurrent.Should().BeFalse();
    }

    // ── #1145: another thread's transaction ──────────────────────────────────

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Selection_Calls_Commit_While_Another_Thread_Holds_A_Transaction(bool asyncSelection)
    {
        var hub = new TestHub();
        var first = Child(hub, NullDispatcher.Instance, "first");
        var second = Child(hub, NullDispatcher.Instance, "second");
        var late = Child(hub, NullDispatcher.Instance, "late");
        var root = new Root(hub, NullDispatcher.Instance, () => [first, second], asyncSelection: asyncSelection);
        root.Vm.Construct();

        using var add = new ParkedAdd(root.Vm, late);
        root.Vm.Current = second;
        root.Vm.Current.Should().BeSameAs(second);
        root.Vm.CanSelectComponent(first).Should().BeTrue();
        root.Vm.SelectComponent(first);
        root.Vm.Current.Should().BeSameAs(first);
        root.Vm.DeselectComponent(first);
        root.Vm.Current.Should().BeNull();
        late.Select(); // admitted before the add publishes
        root.Vm.Current.Should().BeSameAs(late);
        late.Deselect();
        root.Vm.Current.Should().BeNull();
        add.Finish();

        root.Changes.Should().Equal("second", "first", null, "late", null);
        root.Vm.Should().Equal(first, second, late);
    }

    [Fact]
    public void Late_Child_Hook_Selects_During_Another_Threads_Add_Without_Rolling_Back()
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = Child(hub, dispatcher, "first", background: true);
        Root? root = null;
        Exception? hookError = null;
        var late = Child(hub, dispatcher, "late", background: true, onConstruct: () =>
        {
            try { root!.Vm.Current = first; }
            catch (Exception error) { hookError = error; throw; }
        });
        root = new Root(hub, dispatcher, () => [first], selectFirst: true);
        root.Vm.Construct(); // the walk waits on first

        using var add = new ParkedAdd(root.Vm, late);
        SpinWait.SpinUntil(
            () =>
            {
                dispatcher.RunAll(); // late's hook runs here, on a non-owner thread
                return root.Vm.Status != ConstructionStatus.Constructing && !root.Vm.HasInFlightLifecycleForTesting;
            },
            HangGuard).Should().BeTrue();

        hookError.Should().BeNull();
        root.Vm.Status.Should().Be(ConstructionStatus.Constructed);
        root.Vm.Current.Should().BeSameAs(first);
        first.IsCurrent.Should().BeTrue();
        root.Changes.Should().Equal("first");
        late.Status.Should().Be(ConstructionStatus.Constructed);
        add.Finish();
    }

    // ── #1146: the caller's own uncommitted transaction ─────────────────────

    [Theory]
    [InlineData("add", "late", false)]
    [InlineData("insert", "late", false)]
    [InlineData("replace", "late", false)]
    [InlineData("add", "late", true)]
    [InlineData("add", "select-late", false)]
    [InlineData("add", "keep", false)]
    [InlineData("insert", "keep", false)]
    [InlineData("replace", "keep", false)]
    [InlineData("add", "null", true)]
    [InlineData("add", "deselect-keep", true)]
    [InlineData("replace", "null", true)]
    public void Owner_Thread_Selection_Before_A_Failed_Admission_Is_Refused(
        string operation, string target, bool keepCurrent)
    {
        var hub = new TestHub();
        var keep = Child(hub, NullDispatcher.Instance, "keep");
        var spare = Child(hub, NullDispatcher.Instance, "spare");
        Root? root = null;
        ComponentVM? late = null;
        Exception? hookError = null;
        late = Child(hub, NullDispatcher.Instance, "late", onConstruct: () =>
        {
            try
            {
                switch (target)
                {
                    case "late": root!.Vm.Current = late; break;
                    case "select-late": root!.Vm.SelectComponent(late!); break;
                    case "keep": root!.Vm.Current = keep; break;
                    case "null": root!.Vm.Current = null; break;
                    case "deselect-keep": root!.Vm.DeselectComponent(keep); break;
                }
            }
            catch (Exception error) { hookError = error; }
            throw new InvalidOperationException("boom");
        });
        root = new Root(hub, NullDispatcher.Instance, () => [keep, spare]);
        root.Vm.Construct();
        if (keepCurrent) root.Vm.Current = keep;
        root.ResetRecords();

        var act = () =>
        {
            if (operation == "add") root.Vm.Add(late);
            else if (operation == "insert") root.Vm.Insert(0, late);
            else root.Vm[1] = late; // replaces spare
        };

        act.Should().Throw<InvalidOperationException>().WithMessage("boom");
        hookError.Should().BeOfType<InvalidOperationException>().Which.Message.Should().Contain(
            target == "select-late" ? "can_select_component returned false" : "already in progress");
        root.Vm.Should().Equal(keep, spare);
        root.Vm.Current.Should().BeSameAs(keepCurrent ? keep : null);
        keep.IsCurrent.Should().Be(keepCurrent);
        late.IsCurrent.Should().BeFalse();
        root.Changes.Should().BeEmpty();
        root.CurrentMessages.Should().Be(0);
    }

    [Fact]
    public void Owner_Thread_Selection_From_A_Failed_Factory_Population_Is_Refused()
    {
        var hub = new TestHub();
        Root? root = null;
        ComponentVM? a = null;
        Exception? hookError = null;
        a = Child(hub, NullDispatcher.Instance, "a", onConstruct: () =>
        {
            try { root!.Vm.Current = a; }
            catch (Exception error) { hookError = error; }
        });
        var b = Child(hub, NullDispatcher.Instance, "b",
            onConstruct: () => throw new InvalidOperationException("population fails"));
        root = new Root(hub, NullDispatcher.Instance, () => [a, b]);

        var act = () => root.Vm.Construct();

        act.Should().Throw<Exception>();
        hookError.Should().BeOfType<InvalidOperationException>()
            .Which.Message.Should().Contain("already in progress");
        root.Vm.Should().BeEmpty();
        root.Vm.Current.Should().BeNull();
        a.IsCurrent.Should().BeFalse();
        root.Changes.Should().BeEmpty();
        root.CurrentMessages.Should().Be(0);
    }

    [Fact]
    public void Owner_Thread_Selection_From_The_Add_Publication_Commits()
    {
        var hub = new TestHub();
        var keep = Child(hub, NullDispatcher.Instance, "keep");
        var late = Child(hub, NullDispatcher.Instance, "late");
        var root = new Root(hub, NullDispatcher.Instance, () => [keep]);
        root.Vm.Construct();
        root.Vm.CollectionChanged += (_, _) =>
        {
            root.Vm.CanSelectComponent(late).Should().BeTrue();
            root.Vm.SelectComponent(late);
        };

        root.Vm.Add(late);

        root.Vm.Current.Should().BeSameAs(late);
        late.IsCurrent.Should().BeTrue();
        root.Changes.Should().Equal("late");
    }

    [Fact]
    public void Async_Delivery_Inside_The_Owner_Uncommitted_Transaction_Is_Dropped()
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher(queueForeground: true);
        var keep = Child(hub, NullDispatcher.Instance, "keep");
        var late = Child(hub, NullDispatcher.Instance, "late", onConstruct: dispatcher.ForegroundQueue.RunAll);
        var root = new Root(hub, dispatcher, () => [keep], asyncSelection: true);
        root.Vm.Construct();
        dispatcher.RunAll();

        root.Vm.Current = keep; // validated now, delivered by late's hook inside the add
        root.Vm.Add(late);
        dispatcher.RunAll();

        root.Vm.Current.Should().BeNull();
        keep.IsCurrent.Should().BeFalse();
        root.Changes.Should().BeEmpty();
    }

    // ── #1146: rule 2 on another thread ──────────────────────────────────────

    [Fact]
    public void Another_Thread_Cannot_Select_An_Unadmitted_Child_But_Can_Select_A_Member()
    {
        var hub = new TestHub();
        var keep = Child(hub, NullDispatcher.Instance, "keep");
        using var inHook = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        var late = Child(hub, NullDispatcher.Instance, "late", onConstruct: () =>
        {
            inHook.Set();
            release.Wait(HangGuard * 2);
            throw new InvalidOperationException("boom");
        });
        var root = new Root(hub, NullDispatcher.Instance, () => [keep]);
        root.Vm.Construct();
        var errors = new List<Exception>();
        var worker = Start(() => root.Vm.Add(late), errors);
        inHook.Wait(HangGuard).Should().BeTrue();

        var selectLate = () => root.Vm.Current = late;
        selectLate.Should().Throw<InvalidOperationException>().WithMessage("*not a member*");
        root.Vm.CanSelectComponent(late).Should().BeFalse();
        root.Vm.Current = keep; // the foreign transaction neither fails nor delays it
        release.Set();
        worker.Join(HangGuard * 3).Should().BeTrue();

        lock (errors) errors.Select(error => error.Message).Should().Equal("boom");
        root.Vm.Should().Equal(keep);
        root.Vm.Current.Should().BeSameAs(keep); // the rollback leaves a foreign selection
        keep.IsCurrent.Should().BeTrue();
        late.IsCurrent.Should().BeFalse();
        root.Changes.Should().Equal("keep");
    }

    // ── #1148: a staged population ───────────────────────────────────────────

    /// <summary>A subclass that attaches a population at any time (protected API).</summary>
    private sealed class Repopulating : CompositeVMBase<ComponentVM>
    {
        public Repopulating(
            TestHub hub, IDispatcher dispatcher, Func<IEnumerable<ComponentVM>, ComponentVM?> selector,
            Action<ComponentVM?> onCurrentChanged)
            : base("repop", string.Empty, hub, dispatcher, asyncSelection: false, autoConstructOnAdd: false,
                onConstruct: null, onDestruct: null, currentSelector: selector,
                onCurrentChanged: onCurrentChanged, destructOrder: ChildOrder.Insertion)
        {
        }

        public void Repopulate(IEnumerable<ComponentVM> children) => AttachPopulation(children);
    }

    [Fact]
    public void Walk_Ignores_A_Staged_Population_Candidate()
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = Child(hub, dispatcher, "first", background: true);
        var good = Child(hub, NullDispatcher.Instance, "good");
        using var inHook = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        var bad = Child(hub, NullDispatcher.Instance, "bad", onConstruct: () =>
        {
            inHook.Set();
            release.Wait(HangGuard * 2);
            throw new InvalidOperationException("population fails");
        });
        var errors = new List<Exception>();
        var changes = new List<string?>();
        Thread? worker = null;
        Repopulating? root = null;
        root = new Repopulating(hub, dispatcher, _ =>
        {
            Volatile.Write(ref worker, Start(() => root!.Repopulate([good, bad]), errors));
            inHook.Wait(HangGuard).Should().BeTrue();
            root!.CanSelectComponent(good).Should().BeFalse();
            return good; // staged by the worker's population
        }, value => { lock (changes) changes.Add(value?.Name); });
        root.Add(first);

        root.Construct();
        SpinWait.SpinUntil(
            () =>
            {
                dispatcher.RunAll();
                return root.Status != ConstructionStatus.Constructing && !root.HasInFlightLifecycleForTesting;
            },
            HangGuard).Should().BeTrue();
        root.Current.Should().BeNull();
        release.Set();
        SpinWait.SpinUntil(() => Volatile.Read(ref worker) is not null, HangGuard).Should().BeTrue();
        Volatile.Read(ref worker)!.Join(HangGuard * 3).Should().BeTrue();

        lock (errors) errors.Select(error => error.Message).Should().Equal("population fails");
        root.Status.Should().Be(ConstructionStatus.Constructed);
        root.Should().Equal(first);
        root.Current.Should().BeNull();
        good.IsCurrent.Should().BeFalse();
        lock (changes) changes.Should().BeEmpty();
    }

    // ── Rule 3: disposal ─────────────────────────────────────────────────────

    [Fact]
    public void Pending_Disposal_Refuses_A_Non_Null_Selection_But_Not_A_Null_Clear()
    {
        var hub = new TestHub();
        var a = Child(hub, NullDispatcher.Instance, "a");
        var b = Child(hub, NullDispatcher.Instance, "b");
        Root? root = null;
        Exception? selectError = null;
        Exception? selectComponentError = null;
        var canSelect = true;
        root = new Root(hub, NullDispatcher.Instance, () => [a, b], onCurrent: value =>
        {
            if (value is null) return;
            root!.Vm.Dispose(); // deferred by the lease
            try { root.Vm.Current = b; }
            catch (Exception error) { selectError = error; }
            canSelect = root.Vm.CanSelectComponent(b);
            try { root.Vm.SelectComponent(b); }
            catch (Exception error) { selectComponentError = error; }
            root.Vm.Current = null;
        });
        root.Vm.Construct();

        root.Vm.Current = a;

        selectError.Should().BeOfType<ObjectDisposedException>();
        canSelect.Should().BeFalse();
        selectComponentError.Should().BeOfType<InvalidOperationException>()
            .Which.Message.Should().Contain("can_select_component returned false");
        root.Changes.Should().Equal("a", null);
        a.IsCurrent.Should().BeFalse();
        b.IsCurrent.Should().BeFalse();
        root.Vm.Status.Should().Be(ConstructionStatus.Disposed);
    }
}
