using System.ComponentModel;
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

namespace VMx.Conformance.Tests;

/// <summary>
/// COMP-054 and GRP-017 (spec/06 §4.2, spec/07 §4, ADR-0218 rule 7): a failed
/// add, insert or replacement that auto-started a background child, which is
/// still Constructing at the rollback, returns that child to Destructed once
/// its construct settles Constructed with no parent. The rollback does not
/// wait for the child.
/// </summary>
public class COMP_054_GRP_017_BackgroundRollbackCompensation_Tests
{
    /// <summary>Queues background work; the foreground runs inline.</summary>
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
                // A background hook that a disposal superseded may throw here.
                try { work(); }
                catch (InvalidOperationException) { }
            }
        }
    }

    private static ComponentVM Child(IMessageHub hub, IDispatcher dispatcher, string name, bool background)
        => ComponentVM.Builder().Name(name).Services(hub, dispatcher).Background(background).Build();

    /// <summary>Disposes <paramref name="container"/> when <paramref name="child"/> publishes Constructing.</summary>
    private static void DisposeOnConstructing(ComponentVM child, IDisposable container)
    {
        var fired = 0;
        ((INotifyPropertyChanged)child).PropertyChanged += (_, args) =>
        {
            if (args.PropertyName != nameof(IComponentVM.Status) ||
                child.Status != ConstructionStatus.Constructing ||
                Interlocked.Exchange(ref fired, 1) != 0) return;
            container.Dispose();
        };
    }

    private static void RunUntil(QueueDispatcher dispatcher, Func<bool> done)
        => SpinWait.SpinUntil(
            () =>
            {
                dispatcher.RunAll();
                return done();
            },
            Liveness.HangGuard).Should().BeTrue("the queued work settles");

    /// <summary>
    /// Runs one case: the container is Constructed, or held Constructing by a
    /// background member. A sibling sync member gives the replacement a slot.
    /// </summary>
    private static void RunCase<TContainer>(
        Func<IMessageHub, IDispatcher, TContainer> build, string operation, bool constructing, bool background)
        where TContainer : class, IList<ComponentVM>, IComponentVM
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        var container = build(hub, dispatcher);
        var slot = Child(hub, dispatcher, "slot", background: false);
        if (constructing)
        {
            container.Add(Child(hub, dispatcher, "anchor", background: true));
            container.Add(slot);
            container.Construct();
            container.Status.Should().Be(ConstructionStatus.Constructing, "the walk waits on the anchor");
        }
        else
        {
            container.Construct();
            container.Add(slot);
            container.Status.Should().Be(ConstructionStatus.Constructed);
        }
        var child = Child(hub, dispatcher, "c", background);
        DisposeOnConstructing(child, (IDisposable)container);

        Action change = operation switch
        {
            "add" => () => container.Add(child),
            "insert" => () => container.Insert(0, child),
            _ => () => container[container.IndexOf(slot)] = child,
        };

        change.Should().Throw<ObjectDisposedException>("the container's disposal fails the change");
        ((IComponentVMInternals)child).Parent.Should().BeNull("the rollback detached the child");
        ((IEnumerable<ComponentVM>)container).Should().NotContain(child);
        RunUntil(dispatcher, () => child.Status == ConstructionStatus.Destructed);

        child.Status.Should().Be(ConstructionStatus.Destructed, "the compensation returns the child to Destructed");
        ((IComponentVMInternals)child).Parent.Should().BeNull();
        container.Status.Should().Be(ConstructionStatus.Disposed);
    }

    private static CompositeVM<ComponentVM> Composite(IMessageHub hub, IDispatcher dispatcher)
        => CompositeVM<ComponentVM>.Builder().Name("root").Services(hub, dispatcher).Children(() => Array.Empty<ComponentVM>())
            .AutoConstructOnAdd(true).Build();

    private static GroupVM<ComponentVM> Group(IMessageHub hub, IDispatcher dispatcher)
        => GroupVM<ComponentVM>.Builder().Name("root").Services(hub, dispatcher).Children(() => Array.Empty<ComponentVM>())
            .AutoConstructOnAdd(true).Build();

    [Theory, Trait("Conformance", "COMP-054")]
    [InlineData("add", false)]
    [InlineData("add", true)]
    [InlineData("insert", false)]
    [InlineData("insert", true)]
    [InlineData("replace", false)]
    [InlineData("replace", true)]
    public void COMP_054_Failed_Change_Destructs_Background_Child_Once_It_Settles(string operation, bool constructing)
        => RunCase(Composite, operation, constructing, background: true);

    [Theory, Trait("Conformance", "COMP-054")]
    [InlineData(false)]
    [InlineData(true)]
    public void COMP_054_Control_Failed_Add_Of_Sync_Child_Ends_Destructed(bool constructing)
        => RunCase(Composite, "add", constructing, background: false);

    [Theory, Trait("Conformance", "GRP-017")]
    [InlineData("add", false)]
    [InlineData("add", true)]
    [InlineData("insert", false)]
    [InlineData("insert", true)]
    [InlineData("replace", false)]
    [InlineData("replace", true)]
    public void GRP_017_Failed_Change_Destructs_Background_Child_Once_It_Settles(string operation, bool constructing)
        => RunCase(Group, operation, constructing, background: true);

    [Theory, Trait("Conformance", "GRP-017")]
    [InlineData(false)]
    [InlineData(true)]
    public void GRP_017_Control_Failed_Add_Of_Sync_Child_Ends_Destructed(bool constructing)
        => RunCase(Group, "add", constructing, background: false);
}
