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
/// Factory population starts every factory child before the child walk runs.
/// A later background child that fails while the walk waits on an earlier one
/// is final: the walk joins it, rolls the container back, and never re-runs its
/// hook (spec/02 §6, LIFE-014).
/// </summary>
public class PopulationBackgroundJoinTests
{
    /// <summary>Runs the newest background work first and collects its failures.</summary>
    private sealed class LifoDispatcher : IDispatcher, IScheduler
    {
        private readonly object _gate = new();
        private readonly Stack<Action> _work = new();

        public List<Exception> Errors { get; } = new();
        public IScheduler Foreground => ImmediateScheduler.Instance;
        public IScheduler Background => this;
        public DateTimeOffset Now => DateTimeOffset.UtcNow;

        public bool IsIdle { get { lock (_gate) return _work.Count == 0; } }

        public IDisposable Schedule<TState>(TState state, Func<IScheduler, TState, IDisposable> action)
        {
            lock (_gate) _work.Push(() => action(this, state));
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
                    work = _work.Pop();
                }
                try { work(); }
                catch (Exception error) { lock (_gate) Errors.Add(error); }
            }
        }
    }

    [Theory]
    [InlineData("composite")]
    [InlineData("group")]
    public void Later_Failing_Child_Is_Joined_And_Rolls_The_Container_Back(string kind)
    {
        var hub = new TestHub();
        var dispatcher = new LifoDispatcher();
        var badHookRuns = 0;
        var ok = ComponentVM.Builder().Name("ok").Services(hub, dispatcher).Background(true).Build();
        var bad = ComponentVM.Builder()
            .Name("bad")
            .Services(hub, dispatcher)
            .Background(true)
            .OnConstruct(() =>
            {
                Interlocked.Increment(ref badHookRuns);
                throw new InvalidOperationException("bad failed");
            })
            .Build();
        IComponentVM container = kind == "composite"
            ? CompositeVM<ComponentVM>.Builder()
                .Name("root").Services(hub, dispatcher).Children(() => [ok, bad]).Build()
            : GroupVM<ComponentVM>.Builder()
                .Name("root").Services(hub, dispatcher).Children(() => [ok, bad]).Build();

        container.Construct();
        ok.Status.Should().Be(ConstructionStatus.Constructing);
        bad.Status.Should().Be(ConstructionStatus.Constructing);
        SpinWait.SpinUntil(
            () =>
            {
                dispatcher.RunAll();
                return dispatcher.IsIdle && container.Status != ConstructionStatus.Constructing;
            },
            Liveness.HangGuard).Should().BeTrue();
        dispatcher.RunAll();

        Volatile.Read(ref badHookRuns).Should().Be(1, "a joined child is never restarted");
        bad.Status.Should().Be(ConstructionStatus.Destructed);
        container.Status.Should().Be(ConstructionStatus.Destructed);
        container.CanConstruct().Should().BeTrue();
    }
}
