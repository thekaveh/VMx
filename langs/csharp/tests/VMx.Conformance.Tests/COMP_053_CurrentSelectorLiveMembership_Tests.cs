using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COMP-053 (spec/06 §3.2, ADR-0218 rule 2): the <c>Current(selector)</c>
/// receives the composite's live membership when it runs, so it can pick a
/// late child that an auto-construct add attached during the walk.
/// </summary>
public class COMP_053_CurrentSelectorLiveMembership_Tests
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
                work();
            }
        }
    }

    [Fact, Trait("Conformance", "COMP-053")]
    public void COMP_053_Selector_Receives_Live_Membership_And_Picks_A_Late_Child()
    {
        var hub = new TestHub();
        var dispatcher = new QueueDispatcher();
        ComponentVM? late = null;
        var calls = 0;
        List<ComponentVM>? input = null;
        var anchor = ComponentVM.Builder().Name("a").Services(hub, dispatcher).Background(true).Build();
        var composite = CompositeVM<ComponentVM>.Builder()
            .Name("root").Services(hub, dispatcher).Children(() => Array.Empty<ComponentVM>())
            .AutoConstructOnAdd(true)
            .Current(members =>
            {
                Interlocked.Increment(ref calls);
                input = members.ToList();
                return input.FirstOrDefault(member => ReferenceEquals(member, late));
            })
            .Build();
        composite.Add(anchor);

        composite.Construct();
        composite.Status.Should().Be(ConstructionStatus.Constructing, "the walk waits on the background member");
        late = ComponentVM.Builder().Name("l").Services(hub, dispatcher).Build();
        composite.Add(late);
        SpinWait.SpinUntil(
            () =>
            {
                dispatcher.RunAll();
                return composite.Status == ConstructionStatus.Constructed &&
                    !((ComponentVMBase)composite).HasInFlightLifecycleForTesting;
            },
            Liveness.HangGuard).Should().BeTrue("the composite settles");

        composite.Status.Should().Be(ConstructionStatus.Constructed);
        Volatile.Read(ref calls).Should().Be(1, "the selector runs once");
        input.Should().NotBeNull();
        input!.Should().Contain(anchor).And.Contain(late, "the selector sees the live membership");
        composite.Current.Should().BeSameAs(late);
        late.IsCurrent.Should().BeTrue();
    }
}
