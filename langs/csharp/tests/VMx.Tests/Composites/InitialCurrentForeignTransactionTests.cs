using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using System.Reactive.Linq;
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
/// The construct walk assigns the <c>Current(selector)</c> result through a
/// non-raising validated assignment (spec/06 §3.2) even while another thread
/// holds the composite's membership transaction (#1064). The assignment never
/// waits for that transaction, so the composite reaches Constructed with the
/// selected child current. It selects only committed members.
/// </summary>
public class InitialCurrentForeignTransactionTests
{
    private sealed class QueueDispatcher : IDispatcher, IScheduler
    {
        private readonly object _gate = new();
        private readonly List<Action> _work = new();

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

        public void RunFirst()
        {
            Action work;
            lock (_gate)
            {
                work = _work[0];
                _work.RemoveAt(0);
            }
            work();
        }

        public void RunAll()
        {
            while (true)
            {
                lock (_gate) if (_work.Count == 0) return;
                RunFirst();
            }
        }
    }

    /// <summary>A composite whose selector picks its first child, with recorders.</summary>
    private sealed class Root : IDisposable
    {
        private readonly List<string> _order = new();
        private readonly List<string?> _changes = new();

        public Root(
            IEnumerable<ComponentVM> children,
            TestHub hub,
            IDispatcher dispatcher,
            Action<ComponentVM?>? onCurrent = null)
        {
            Vm = CompositeVM<ComponentVM>.Builder()
                .Name("root").Services(hub, dispatcher).Children(() => children)
                .AutoConstructOnAdd(true)
                .Current(kids => kids.FirstOrDefault())
                .OnCurrentChanged(value =>
                {
                    lock (_changes) _changes.Add(value?.Name);
                    onCurrent?.Invoke(value);
                })
                .Build();
            hub.Messages.Subscribe(message =>
            {
                switch (message)
                {
                    case IPropertyChangedMessage<object> property
                        when ReferenceEquals(property.SenderObject, Vm) && property.PropertyName == "Current":
                        Record("Current");
                        break;
                    case ConstructionStatusChangedMessage status when status.SenderName == "root":
                        Record($"root:{status.Status}");
                        if (status.Status == ConstructionStatus.Constructed) Constructed.Set();
                        break;
                }
            });
        }

        public CompositeVM<ComponentVM> Vm { get; }

        public ManualResetEventSlim Constructed { get; } = new(false);

        public IReadOnlyList<string?> Changes { get { lock (_changes) return _changes.ToArray(); } }

        private void Record(string entry)
        {
            lock (_order) _order.Add(entry);
        }

        public void SettleWalk(QueueDispatcher dispatcher)
            => SpinWait.SpinUntil(
                () =>
                {
                    dispatcher.RunAll();
                    return Vm.Status != ConstructionStatus.Constructing && !Vm.HasInFlightLifecycleForTesting;
                },
                HangGuard).Should().BeTrue();

        public void ShouldSelectBeforeConstructed()
        {
            string[] order;
            lock (_order) order = _order.ToArray();
            order.Should().NotContain("root:Destructed");
            Array.IndexOf(order, "Current").Should().BeGreaterThanOrEqualTo(0)
                .And.BeLessThan(Array.IndexOf(order, "root:Constructed"));
        }

        public void Dispose() => Constructed.Dispose();
    }

    /// <summary>A composite whose <c>Dispose</c> can run a hook first.</summary>
    private sealed class HookedComposite : CompositeVMBase<ComponentVM>
    {
        public HookedComposite(TestHub hub, IDispatcher dispatcher, Action<ComponentVM?> onCurrentChanged)
            : base("root", string.Empty, hub, dispatcher, asyncSelection: false, autoConstructOnAdd: true,
                onConstruct: null, onDestruct: null, currentSelector: kids => kids.FirstOrDefault(),
                onCurrentChanged: onCurrentChanged, destructOrder: ChildOrder.Insertion)
        {
        }

        public Action? BeforeDispose { get; set; }

        public override void Dispose()
        {
            BeforeDispose?.Invoke();
            base.Dispose();
        }
    }

    private static ComponentVM Child(TestHub hub, IDispatcher dispatcher, string name, bool background = false)
        => ComponentVM.Builder().Name(name).Services(hub, dispatcher).Background(background).Build();

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

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Selector_Assigns_While_Another_Thread_Holds_The_Add_Transaction(bool ownerWaitsForWalk)
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = Child(hub, dispatcher, "first", background: true);
        var late = Child(hub, dispatcher, "late", background: true);
        using var root = new Root([first], hub, dispatcher);
        var main = Environment.CurrentManagedThreadId;
        using var inHandler = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        var ownerSawConstructed = false;
        root.Vm.CollectionChanged += (_, _) =>
        {
            if (Environment.CurrentManagedThreadId == main) return;
            inHandler.Set();
            // The transaction owner holds its committed add transaction here.
            if (ownerWaitsForWalk) ownerSawConstructed = root.Constructed.Wait(HangGuard);
            else release.Wait(HangGuard * 2);
        };

        root.Vm.Construct();
        var errors = new List<Exception>();
        var worker = Start(() => root.Vm.Add(late), errors);
        inHandler.Wait(HangGuard).Should().BeTrue();

        root.SettleWalk(dispatcher); // the walk resumes and assigns the selector result
        root.Vm.Status.Should().Be(ConstructionStatus.Constructed, "the walk needs no transaction");
        release.Set();
        worker.Join(HangGuard * 3).Should().BeTrue();

        errors.Should().BeEmpty();
        if (ownerWaitsForWalk) ownerSawConstructed.Should().BeTrue();
        root.Vm.Current.Should().BeSameAs(first);
        first.IsCurrent.Should().BeTrue();
        root.Changes.Should().Equal("first");
        root.Vm.Should().Contain(late);
        root.ShouldSelectBeforeConstructed();
    }

    [Fact]
    public void Selector_Assigns_While_The_Owner_Of_A_Remove_Waits_For_The_Walk()
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var extra = Child(hub, dispatcher, "extra");
        var first = Child(hub, dispatcher, "first", background: true);
        using var root = new Root([extra, first], hub, dispatcher);
        var main = Environment.CurrentManagedThreadId;
        using var inHandler = new ManualResetEventSlim(false);
        var ownerSawConstructed = false;
        root.Vm.CollectionChanged += (_, _) =>
        {
            if (Environment.CurrentManagedThreadId == main) return;
            inHandler.Set();
            ownerSawConstructed = root.Constructed.Wait(HangGuard);
        };

        root.Vm.Construct(); // extra constructs now; the walk then waits on first
        var errors = new List<Exception>();
        var worker = Start(() => root.Vm.Remove(extra), errors);
        inHandler.Wait(HangGuard).Should().BeTrue();

        root.SettleWalk(dispatcher);
        worker.Join(HangGuard * 3).Should().BeTrue();

        errors.Should().BeEmpty();
        ownerSawConstructed.Should().BeTrue();
        root.Vm.Status.Should().Be(ConstructionStatus.Constructed);
        root.Vm.Current.Should().BeSameAs(first);
        root.Changes.Should().Equal("first");
        root.Vm.Should().NotContain(extra);
        root.ShouldSelectBeforeConstructed();
    }

    [Fact]
    public void Selector_Result_Is_Ignored_After_The_Owner_Disposes_The_Composite()
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = Child(hub, dispatcher, "first", background: true);
        var late = Child(hub, dispatcher, "late", background: true);
        using var root = new Root([first], hub, dispatcher);
        var main = Environment.CurrentManagedThreadId;
        using var inHandler = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        root.Vm.CollectionChanged += (_, _) =>
        {
            if (Environment.CurrentManagedThreadId == main) return;
            ((IDisposable)root.Vm).Dispose(); // deferred: this thread owns the transaction
            inHandler.Set();
            release.Wait(HangGuard * 2);
        };

        root.Vm.Construct();
        var errors = new List<Exception>();
        var worker = Start(() => root.Vm.Add(late), errors);
        inHandler.Wait(HangGuard).Should().BeTrue();

        root.SettleWalk(dispatcher); // the walk runs the selector and hits the dispose guard
        root.Vm.Current.Should().BeNull();
        release.Set();
        worker.Join(HangGuard * 3).Should().BeTrue();
        SpinWait.SpinUntil(() => root.Vm.Status == ConstructionStatus.Disposed, HangGuard).Should().BeTrue();

        root.Changes.Should().BeEmpty();
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Dispose_From_The_Selector_Publication_Defers_To_The_Lease(bool foreignOwner)
    {
        // A Dispose from the selection's own callback defers until the
        // publication ends; it must not wait for another thread's
        // transaction (spec/06 §3.2).
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = Child(hub, dispatcher, "first", background: true);
        var late = Child(hub, dispatcher, "late", background: true);
        var seen = new List<ConstructionStatus>();
        Root? root = null;
        root = new Root([first], hub, dispatcher, onCurrent: _ =>
        {
            ((IDisposable)root!.Vm).Dispose();
            lock (seen) seen.Add(root.Vm.Status);
        });
        using var disposeRoot = root;
        var main = Environment.CurrentManagedThreadId;
        using var inHandler = new ManualResetEventSlim(false);
        var ownerSawConstructed = false;
        root.Vm.CollectionChanged += (_, _) =>
        {
            if (Environment.CurrentManagedThreadId == main) return;
            inHandler.Set();
            ownerSawConstructed = root.Constructed.Wait(HangGuard);
        };

        root.Vm.Construct();
        var errors = new List<Exception>();
        Thread? worker = null;
        if (foreignOwner)
        {
            worker = Start(() => root.Vm.Add(late), errors);
            inHandler.Wait(HangGuard).Should().BeTrue();
        }

        SpinWait.SpinUntil(
            () =>
            {
                dispatcher.RunAll();
                return root.Vm.Status is ConstructionStatus.Constructed or ConstructionStatus.Disposed &&
                    !root.Vm.HasInFlightLifecycleForTesting;
            },
            HangGuard).Should().BeTrue();
        if (worker is not null)
        {
            worker.Join(HangGuard * 3).Should().BeTrue();
            ownerSawConstructed.Should().BeTrue();
        }
        SpinWait.SpinUntil(() => root.Vm.Status == ConstructionStatus.Disposed, HangGuard).Should().BeTrue();

        errors.Should().BeEmpty();
        root.Changes.Should().Equal("first");
        lock (seen) seen.Should().Equal(ConstructionStatus.Constructing); // the Dispose waited for the publication
    }

    [Fact]
    public void Deferred_Dispose_Admits_No_Transaction_After_The_Owner_Transaction_Ends()
    {
        // The owner's own transaction defers a Dispose from its handler; when the
        // transaction ends, a foreign Add before the Dispose admits must be refused.
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var b = Child(hub, dispatcher, "b");
        var x = Child(hub, dispatcher, "x");
        var errors = new List<Exception>();
        var calls = 0;
        var root = new HookedComposite(hub, dispatcher, _ => { });
        root.Construct();
        root.BeforeDispose = () =>
        {
            if (Interlocked.Increment(ref calls) != 2) return; // the handoff from the transaction end
            Start(() => root.Add(x), errors).Join(HangGuard).Should().BeTrue();
        };
        root.CollectionChanged += (_, _) => root.Dispose();

        root.Add(b);

        Volatile.Read(ref calls).Should().BeGreaterThanOrEqualTo(2);
        lock (errors) errors.Should().ContainSingle().Which.Should().BeOfType<ObjectDisposedException>();
        root.Should().NotContain(x);
        SpinWait.SpinUntil(() => root.Status == ConstructionStatus.Disposed, HangGuard).Should().BeTrue();
    }

    [Fact]
    public void Selector_Result_Is_Ignored_While_The_Composite_Is_Disposing()
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = Child(hub, dispatcher, "first", background: true);
        var changes = new List<string?>();
        CompositeVM<ComponentVM>? root = null;
        root = CompositeVM<ComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher).Children(() => [first])
            .AutoConstructOnAdd(true)
            .Current(_ =>
            {
                // No transaction or publication is open: disposal starts now.
                ((IDisposable)root!).Dispose();
                return first;
            })
            .OnCurrentChanged(value => { lock (changes) changes.Add(value?.Name); })
            .Build();

        root.Construct();
        SpinWait.SpinUntil(
            () =>
            {
                dispatcher.RunAll();
                return root.Status == ConstructionStatus.Disposed && !root.HasInFlightLifecycleForTesting;
            },
            HangGuard).Should().BeTrue();

        root.Current.Should().BeNull();
        lock (changes) changes.Should().BeEmpty();
        first.IsCurrent.Should().BeFalse();
    }

    [Fact]
    public void Dispose_From_An_Ordinary_Selection_Callback_Defers_To_The_Lease()
    {
        // The lease covers every current change, not only the walk's selection:
        // a Dispose from the callback must not wait for another thread's transaction.
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var a = Child(hub, dispatcher, "a");
        var c = Child(hub, dispatcher, "c");
        var main = Environment.CurrentManagedThreadId;
        using var inHandler = new ManualResetEventSlim(false);
        using var disposeReturned = new ManualResetEventSlim(false);
        var ownerSawDisposeReturn = false;
        var seen = new List<ConstructionStatus>();
        var errors = new List<Exception>();
        Thread? worker = null;
        CompositeVM<ComponentVM>? root = null;
        root = CompositeVM<ComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher).Children(() => [a])
            .OnCurrentChanged(_ =>
            {
                worker = Start(() => root!.Add(c), errors);
                inHandler.Wait(HangGuard).Should().BeTrue();
                ((IDisposable)root!).Dispose();
                lock (seen) seen.Add(root.Status);
                disposeReturned.Set();
            })
            .Build();
        root.Construct();
        root.CollectionChanged += (_, _) =>
        {
            if (Environment.CurrentManagedThreadId == main) return;
            inHandler.Set();
            ownerSawDisposeReturn = disposeReturned.Wait(HangGuard);
        };

        root.Current = a;
        worker!.Join(HangGuard * 3).Should().BeTrue();
        SpinWait.SpinUntil(() => root.Status == ConstructionStatus.Disposed, HangGuard).Should().BeTrue();

        lock (errors) errors.Should().BeEmpty();
        ownerSawDisposeReturn.Should().BeTrue();
        lock (seen) seen.Should().Equal(ConstructionStatus.Constructed); // the Dispose returned at once
    }

    [Fact]
    public void Deferred_Dispose_Admits_No_Transaction_During_The_Handoff()
    {
        // When the lease ends, the deferred Dispose runs on this thread. A foreign
        // Add in between must be refused, or that Dispose would wait for it.
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = Child(hub, dispatcher, "first", background: true);
        var x = Child(hub, dispatcher, "x");
        var errors = new List<Exception>();
        var calls = 0;
        HookedComposite? root = null;
        root = new HookedComposite(hub, dispatcher, _ => root!.Dispose());
        root.BeforeDispose = () =>
        {
            if (Interlocked.Increment(ref calls) != 2) return; // the handoff from the lease end
            Start(() => root.Add(x), errors).Join(HangGuard).Should().BeTrue();
        };
        root.Add(first);

        root.Construct();
        SpinWait.SpinUntil(
            () =>
            {
                dispatcher.RunAll();
                return root.Status == ConstructionStatus.Disposed && !root.HasInFlightLifecycleForTesting;
            },
            HangGuard).Should().BeTrue();

        Volatile.Read(ref calls).Should().BeGreaterThanOrEqualTo(2);
        lock (errors) errors.Should().ContainSingle().Which.Should().BeOfType<ObjectDisposedException>();
        root.Should().NotContain(x);
    }

    [Theory]
    [InlineData("add")]
    [InlineData("insert")]
    [InlineData("replace")]
    public void Selector_Result_Whose_Add_Is_Not_Admitted_Is_Not_Selected(string operation)
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = Child(hub, dispatcher, "first", background: true);
        var spare = Child(hub, dispatcher, "spare");
        var late = Child(hub, dispatcher, "late");
        using var attached = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        var errors = new List<Exception>();
        Thread? worker = null;
        var selectorReturned = false;
        CompositeVM<ComponentVM>? root = null;
        root = CompositeVM<ComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher).Children(() => [first, spare])
            .AutoConstructOnAdd(true)
            .Current(_ =>
            {
                Volatile.Write(ref worker, Start(
                    () =>
                    {
                        if (operation == "add") root!.Add(late);
                        else if (operation == "insert") root!.Insert(0, late);
                        else root![1] = late; // replaces spare
                    },
                    errors));
                attached.Wait(HangGuard).Should().BeTrue();
                Volatile.Write(ref selectorReturned, true);
                return late; // attached, not admitted
            })
            .Build();
        root.LateStartsForTesting.ProbeForTesting = (child, stage) =>
        {
            if (stage != LateChildStage.Attached || !ReferenceEquals(child, late)) return;
            attached.Set();
            release.Wait(HangGuard * 2);
            throw new InvalidOperationException("the add rolls back");
        };

        root.Construct();
        dispatcher.RunAll(); // the walk may resume on a pool thread
        SpinWait.SpinUntil(() => Volatile.Read(ref selectorReturned), HangGuard).Should().BeTrue();
        root.Current.Should().BeNull();
        release.Set();
        Volatile.Read(ref worker)!.Join(HangGuard * 3).Should().BeTrue();
        dispatcher.RunAll();

        lock (errors) errors.Select(error => error.Message).Should().Equal("the add rolls back");
        root.Should().Equal(first, spare); // the rollback restored the membership
        root.Current.Should().BeNull();
        late.IsCurrent.Should().BeFalse();
    }

    [Theory]
    [InlineData("transfer-commit")]
    [InlineData("transfer-rollback")]
    [InlineData("replace")]
    [InlineData("replace-from-container")]
    public void Transaction_That_Detached_The_Current_Child_Keeps_The_Selector_Result(string mode)
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var first = Child(hub, dispatcher, "first", background: true);
        var x = Child(hub, dispatcher, "X");
        var y = Child(hub, dispatcher, "Y");
        var dfirst = Child(hub, dispatcher, "dfirst", background: true);
        var dest = CompositeVM<ComponentVM>.Builder()
            .Name("dest").Services(hub, dispatcher).Children(() => [dfirst])
            .AutoConstructOnAdd(true).Build();
        // Y's old parent: its removal callback runs after root admits Y and before
        // root clears the replaced child, so the walk can select inside that window.
        // The case guards against reading Current before that callback; the clear's
        // own check-and-clear is atomic under the gates and has no user code inside.
        var source = CompositeVM<ComponentVM>.Builder()
            .Name("source").Services(hub, dispatcher)
            .Children(() => mode == "replace-from-container" ? [y] : [])
            .Build();
        source.Construct();
        using var paused = new ManualResetEventSlim(false);
        using var release = new ManualResetEventSlim(false);
        using var selected = new ManualResetEventSlim(false);
        var sawSelection = new List<bool>();
        source.CollectionChanged += (_, args) =>
        {
            if (args.Action != System.Collections.Specialized.NotifyCollectionChangedAction.Remove) return;
            paused.Set();
            lock (sawSelection) sawSelection.Add(selected.Wait(HangGuard));
        };
        var changes = new List<string?>();
        var errors = new List<Exception>();
        Thread? worker = null;
        CompositeVM<ComponentVM>? root = null;
        root = CompositeVM<ComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher).Children(() => [])
            .AutoConstructOnAdd(true)
            .Current(_ =>
            {
                Volatile.Write(ref worker, Start(
                    () =>
                    {
                        if (mode.StartsWith("replace", StringComparison.Ordinal)) root![1] = y;
                        else dest.Add(x);
                    },
                    errors));
                paused.Wait(HangGuard).Should().BeTrue();
                return first;
            })
            .OnCurrentChanged(value =>
            {
                lock (changes) changes.Add(value?.Name);
                if (ReferenceEquals(value, first)) selected.Set();
            })
            .Build();
        root.Add(first);
        root.Add(x);
        root.Current = x;
        changes.Clear();
        selected.Reset();
        if (mode != "replace-from-container")
            (mode == "replace" ? root.LateStartsForTesting : dest.LateStartsForTesting).ProbeForTesting =
                (_, stage) =>
                {
                    if (stage != LateChildStage.Attached) return;
                    paused.Set();
                    release.Wait(HangGuard * 2);
                    if (mode == "transfer-rollback") throw new InvalidOperationException("dest attach fails");
                };

        root.Construct();
        dest.Construct();
        dispatcher.RunFirst(); // first settles; root's walk runs the selector, maybe on a pool thread
        paused.Wait(HangGuard).Should().BeTrue();
        // The selection commits while the foreign transaction is paused.
        SpinWait.SpinUntil(
            () => ReferenceEquals(root.Current, first) || root.Status != ConstructionStatus.Constructing,
            HangGuard).Should().BeTrue();
        release.Set();
        SpinWait.SpinUntil(() => Volatile.Read(ref worker) is not null, HangGuard).Should().BeTrue();
        Volatile.Read(ref worker)!.Join(HangGuard * 3).Should().BeTrue();
        SpinWait.SpinUntil(
            () =>
            {
                dispatcher.RunAll();
                return root.Status != ConstructionStatus.Constructing &&
                    !root.HasInFlightLifecycleForTesting;
            },
            HangGuard).Should().BeTrue();

        lock (errors)
            errors.Select(error => error.Message).Should().Equal(
                mode == "transfer-rollback" ? ["dest attach fails"] : Array.Empty<string>());
        root.Status.Should().Be(ConstructionStatus.Constructed);
        root.Current.Should().BeSameAs(first);
        first.IsCurrent.Should().BeTrue();
        x.IsCurrent.Should().BeFalse();
        lock (changes) changes.Should().Equal("first");
        if (mode == "replace-from-container")
        {
            lock (sawSelection) sawSelection.Should().Equal(true); // selected after root admitted Y
            root.Should().Equal(first, y);
        }
    }
}
