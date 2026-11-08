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
/// <c>Remove</c> of a non-child ends its membership transaction after it
/// releases the shared coordination lane (#1147). When a deferred
/// <c>Dispose()</c> waits for that transaction, the disposal cascade runs
/// without the lane, so a <c>Current</c> change on any other composite, and a
/// child hook that makes one, can finish while the cascade runs
/// (spec/06 §4.2).
/// </summary>
public sealed class RemoveNonChildDeferredDisposalTests
{
    private sealed class ThrowingOnDisposeVM(IMessageHub hub, IDispatcher dispatcher)
        : ComponentVMBase("throws-on-dispose", string.Empty, hub, dispatcher, null, null)
    {
        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnDispose() => throw new InvalidOperationException("dispose failed");
    }

    /// <summary>An unrelated, constructed composite whose selection moves from x to y.</summary>
    private sealed class Unrelated
    {
        public Unrelated()
        {
            var hub = new TestHub();
            X = ComponentVM.Builder().Name("x").Services(hub, NullDispatcher.Instance).Build();
            Y = ComponentVM.Builder().Name("y").Services(hub, NullDispatcher.Instance).Build();
            IComponentVM[] kids = [X, Y];
            Vm = CompositeVM<IComponentVM>.Builder().Name("other").Services(hub, NullDispatcher.Instance)
                .Children(() => kids).Build();
            Vm.Construct();
            Vm.Current = X;
        }

        public CompositeVM<IComponentVM> Vm { get; }

        public IComponentVM X { get; }

        public IComponentVM Y { get; }

        /// <summary>
        /// Selects y on a new thread and waits for it within the hang guard.
        /// The thread survives a timed-out wait, so a regression that holds the
        /// lane delays the assignment but does not leave it blocked.
        /// </summary>
        public bool SelectOnAnotherThreadWithinHangGuard()
        {
            // Not disposed: a timed-out setter still signals it later.
            var done = new ManualResetEventSlim(false);
            var setter = new Thread(() =>
            {
                Vm.Current = Y;
                done.Set();
            })
            { IsBackground = true };
            setter.Start();
            var completed = done.Wait(HangGuard);
            setter.Join(HangGuard);
            return completed;
        }
    }

    private sealed record RemoveOutcome(bool Returned, bool Result, Exception? Error, int ThreadId);

    /// <summary>
    /// Builds the #1147 ordering. The test thread holds the coordination lane
    /// (the monitor is reentrant) and selects <paramref name="select"/>. Its
    /// <c>OnCurrentChanged</c> callback starts thread A, which calls
    /// <c>Remove(outsider)</c>, and waits until A owns the membership
    /// transaction. The callback then calls <c>Dispose()</c>, which VMx defers
    /// because this thread is publishing the selection. The test thread ends
    /// its publication before it releases the lane, so A's transaction end,
    /// not the publication end, runs the deferred disposal.
    /// </summary>
    private static RemoveOutcome RemoveNonChildWithDeferredDispose(
        CompositeVM<IComponentVM> root, Action<Action> armCallback, IComponentVM select, IComponentVM outsider)
    {
        var result = false;
        Exception? error = null;
        var threadId = 0;
        Thread? remover = null;
        armCallback(() =>
        {
            remover = new Thread(() =>
            {
                threadId = Environment.CurrentManagedThreadId;
                try { result = root.Remove(outsider); }
                catch (Exception e) { error = e; }
            })
            { IsBackground = true };
            remover.Start();
            SpinWait.SpinUntil(() => root.MembershipTransactionActiveForTesting, HangGuard)
                .Should().BeTrue("thread A opens its transaction before it waits for the lane");
            root.Dispose();
            root.Status.Should().NotBe(ConstructionStatus.Disposed, "the disposal is deferred");
        });
        lock (CompositeCurrentChangeCoordinator.Gate)
            root.Current = select;
        remover.Should().NotBeNull();
        // A regression holds the lane while a test hook waits up to one hang
        // guard for a selection; the longer join lets the precise assertions
        // below report it instead of the join.
        var returned = remover!.Join(HangGuard * 3);
        return new RemoveOutcome(returned, result, error, threadId);
    }

    private static (CompositeVM<IComponentVM> Root, Action<Action> Arm) BuildRoot(
        TestHub hub, params IComponentVM[] kids)
    {
        Action? pending = null;
        var root = CompositeVM<IComponentVM>.Builder().Name("root").Services(hub, NullDispatcher.Instance)
            .Children(() => kids)
            .DestructOrder(ChildOrder.Insertion)
            .OnCurrentChanged(_ =>
            {
                var action = Interlocked.Exchange(ref pending, null);
                action?.Invoke();
            })
            .Build();
        root.Construct();
        return (root, action => Volatile.Write(ref pending, action));
    }

    private static bool IsChildDisposed(IMessage message, CompositeVM<IComponentVM> root)
        => message is ConstructionStatusChangedMessage { Status: ConstructionStatus.Disposed } status &&
            !ReferenceEquals(status.Sender, root);

    [Fact]
    public void Deferred_disposal_from_Remove_of_a_non_child_runs_outside_the_coordination_lane()
    {
        var hub = new TestHub();
        var a = ComponentVM.Builder().Name("a").Services(hub, NullDispatcher.Instance).Build();
        var b = ComponentVM.Builder().Name("b").Services(hub, NullDispatcher.Instance).Build();
        var outsider = ComponentVM.Builder().Name("outsider").Services(hub, NullDispatcher.Instance).Build();
        var (root, arm) = BuildRoot(hub, a, b);
        var unrelated = new Unrelated();
        var observations = new List<(int ThreadId, bool LaneHeld)>();
        bool? unrelatedSelectionCompleted = null;
        using var subscription = hub.Messages.Subscribe(message =>
        {
            if (message is not ConstructionStatusChangedMessage { Status: ConstructionStatus.Disposed })
                return;
            lock (observations)
                observations.Add((Environment.CurrentManagedThreadId,
                    Monitor.IsEntered(CompositeCurrentChangeCoordinator.Gate)));
            if (IsChildDisposed(message, root) && unrelatedSelectionCompleted is null)
                unrelatedSelectionCompleted = unrelated.SelectOnAnotherThreadWithinHangGuard();
        });

        var outcome = RemoveNonChildWithDeferredDispose(root, arm, a, outsider);

        outcome.Returned.Should().BeTrue("Remove returns within the hang guard");
        outcome.Error.Should().BeNull();
        outcome.Result.Should().BeFalse("outsider is not a child");
        root.Status.Should().Be(ConstructionStatus.Disposed);
        lock (observations)
        {
            observations.Should().HaveCount(3, "a, b and root each publish Disposed");
            observations.Should().OnlyContain(o => o.ThreadId == outcome.ThreadId,
                "the transaction owner runs the deferred disposal");
            observations.Should().OnlyContain(o => !o.LaneHeld,
                "the disposal cascade does not hold the shared coordination lane (spec/06 §4.2)");
        }
        unrelatedSelectionCompleted.Should().BeTrue(
            "a Current change on an unrelated composite does not wait for the cascade");
        unrelated.Vm.Current.Should().BeSameAs(unrelated.Y);
    }

    [Fact]
    public void Child_hook_that_selects_on_another_composite_finishes_during_the_deferred_disposal()
    {
        var hub = new TestHub();
        var unrelated = new Unrelated();
        // Not disposed: after a timed-out wait the hook thread can still use them.
        var hookStarted = new ManualResetEventSlim(false);
        var release = new ManualResetEventSlim(false);
        var hookFinished = new ManualResetEventSlim(false);
        var hookArmed = 1;
        bool? hookReleased = null;
        bool? hookSelectionCompleted = null;
        var a = ComponentVM.Builder().Name("a").Services(hub, NullDispatcher.Instance).Build();
        var b = ComponentVM.Builder().Name("b").Services(hub, NullDispatcher.Instance).Build();
        var h = ComponentVM.Builder().Name("h").Services(hub, NullDispatcher.Instance)
            .OnDestruct(() =>
            {
                if (Interlocked.Exchange(ref hookArmed, 0) == 0) return;
                hookStarted.Set();
                hookReleased = release.Wait(HangGuard);
                hookSelectionCompleted = unrelated.SelectOnAnotherThreadWithinHangGuard();
                hookFinished.Set();
            })
            .Build();
        var outsider = ComponentVM.Builder().Name("outsider").Services(hub, NullDispatcher.Instance).Build();
        // Insertion destruct order: a and b publish Disposed before the cascade
        // reaches h and waits for its running hook.
        var (root, arm) = BuildRoot(hub, a, b, h);
        using var subscription = hub.Messages.Subscribe(message =>
        {
            if (IsChildDisposed(message, root)) release.Set();
        });
        Exception? destructError = null;
        var destructor = new Thread(() =>
        {
            try { h.Destruct(); }
            catch (Exception e) { destructError = e; }
        })
        { IsBackground = true };
        destructor.Start();
        hookStarted.Wait(HangGuard).Should().BeTrue("h's OnDestruct hook is running on thread D");

        var outcome = RemoveNonChildWithDeferredDispose(root, arm, a, outsider);

        outcome.Returned.Should().BeTrue("Remove returns within the hang guard");
        outcome.Error.Should().BeNull();
        outcome.Result.Should().BeFalse("outsider is not a child");
        hookFinished.Wait(HangGuard).Should().BeTrue("the hook finishes");
        destructor.Join(HangGuard).Should().BeTrue();
        destructError.Should().BeNull();
        hookReleased.Should().BeTrue("the cascade published a child Disposed message");
        hookSelectionCompleted.Should().BeTrue(
            "the hook's Current change does not wait for a cascade that holds the lane");
        root.Status.Should().Be(ConstructionStatus.Disposed);
        h.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void Dispose_failure_of_the_deferred_disposal_propagates_from_Remove_of_a_non_child()
    {
        var hub = new TestHub();
        var a = ComponentVM.Builder().Name("a").Services(hub, NullDispatcher.Instance).Build();
        var throwing = new ThrowingOnDisposeVM(hub, NullDispatcher.Instance);
        var outsider = ComponentVM.Builder().Name("outsider").Services(hub, NullDispatcher.Instance).Build();
        var (root, arm) = BuildRoot(hub, a, throwing);

        var outcome = RemoveNonChildWithDeferredDispose(root, arm, a, outsider);

        outcome.Returned.Should().BeTrue("Remove returns within the hang guard");
        outcome.Error.Should().BeOfType<InvalidOperationException>()
            .Which.Message.Should().Be("dispose failed");
        root.Status.Should().Be(ConstructionStatus.Disposed);
        root.MembershipTransactionActiveForTesting.Should().BeFalse();
    }
}
