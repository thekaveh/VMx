using System.Collections.Concurrent;
using FluentAssertions;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// The supported child-transition helper and member disposal on a consumer
/// subclass (spec/02 §6.1 and §7.1, ADR-0162): the usage guards, joins,
/// background hooks, reconstruct, and member registration rules.
/// </summary>
public class ChildTransitionHelperTests
{
    private sealed class ConsumerVM(string name, IMessageHub hub, IDispatcher dispatcher, bool background = false)
        : ComponentVMBase(name, hub, dispatcher, background: background)
    {
        public IReadOnlyList<IComponentVM> ConstructMembers { get; set; } = [];
        public IReadOnlyList<IComponentVM> DestructMembers { get; set; } = [];
        public Action? DuringConstruct { get; set; }

        public override ViewModelType Type => ViewModelType.Component;

        public static Task Walk(IEnumerable<IComponentVM> children, bool construct)
            => TransitionChildrenAsync(children, construct);

        public void Defer(Task task) => CompleteLifecycleHookAfter(task);

        public T Member<T>(T member) where T : IComponentVM => OwnMember(member);

        protected override void OnConstruct()
        {
            DuringConstruct?.Invoke();
            CompleteLifecycleHookAfter(TransitionChildrenAsync(ConstructMembers, construct: true));
        }

        protected override void OnDestruct()
            => CompleteLifecycleHookAfter(TransitionChildrenAsync(DestructMembers, construct: false));
    }

    private sealed class DisposeHookVM(string name, IMessageHub hub, Action onDispose)
        : ComponentVMBase(name, hub, NullDispatcher.Instance)
    {
        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnDispose() => onDispose();
    }

    private static ComponentVM Leaf(string name, IMessageHub hub, IDispatcher? dispatcher = null,
        bool background = false, Action? onDestruct = null)
    {
        var builder = ComponentVM.Builder()
            .Name(name)
            .Services(hub, dispatcher ?? NullDispatcher.Instance)
            .Background(background);
        if (onDestruct is not null) builder = builder.OnDestruct(onDestruct);
        return builder.Build();
    }

    private static ConcurrentQueue<string> Record(TestHub hub)
    {
        var recorded = new ConcurrentQueue<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is ConstructionStatusChangedMessage changed)
                recorded.Enqueue($"{changed.SenderName} {changed.Status}");
        });
        return recorded;
    }

    /// <summary>Runs a background hook, then its marshalled terminal status.</summary>
    private static void Drain(TestDispatcher dispatcher)
    {
        dispatcher.BackgroundScheduler.AdvanceBy(1);
        dispatcher.ForegroundScheduler.AdvanceBy(1);
    }

    // ── Usage guards ─────────────────────────────────────────────────────────

    [Fact]
    public void TransitionChildrenAsync_OutsideAHook_ThrowsSynchronously_AndStartsNoChild()
    {
        using var hub = new TestHub();
        var child = Leaf("child", hub);

        Task? walk = null;
        Action act = () => walk = ConsumerVM.Walk([child], construct: true);

        act.Should().Throw<InvalidOperationException>().WithMessage("*construct or destruct hook*");
        walk.Should().BeNull();
        child.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void CompleteLifecycleHookAfter_OutsideAHook_Throws()
    {
        using var hub = new TestHub();
        var vm = new ConsumerVM("vm", hub, NullDispatcher.Instance);

        var act = () => vm.Defer(Task.CompletedTask);

        act.Should().Throw<InvalidOperationException>().WithMessage("*construct or destruct hook of 'vm'*");
    }

    [Fact]
    public void CompleteLifecycleHookAfter_FromAnotherVMsHook_Throws()
    {
        using var hub = new TestHub();
        var other = new ConsumerVM("other", hub, NullDispatcher.Instance);
        var vm = new ConsumerVM("vm", hub, NullDispatcher.Instance)
        {
            DuringConstruct = () => other.Defer(Task.CompletedTask),
        };

        var act = vm.Construct;

        act.Should().Throw<InvalidOperationException>().WithMessage("*hook of 'other'*");
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── Joins, background hooks, and reconstruct ─────────────────────────────

    [Fact]
    public async Task Destruct_JoinsAChildAlreadyDestructing()
    {
        using var hub = new TestHub();
        var childDispatcher = new TestDispatcher();
        var hookRuns = 0;
        var child = Leaf("child", hub, childDispatcher, background: true,
            onDestruct: () => Interlocked.Increment(ref hookRuns));
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance)
        {
            ConstructMembers = [child],
            DestructMembers = [child],
        };
        var construct = parent.ConstructAsync();
        Drain(childDispatcher);
        await construct.WaitAsync(Liveness.HangGuard);
        child.Destruct();
        child.Status.Should().Be(ConstructionStatus.Destructing);

        var destruct = parent.DestructAsync();

        parent.Status.Should().Be(ConstructionStatus.Destructing);
        Drain(childDispatcher);
        await destruct.WaitAsync(Liveness.HangGuard);
        child.Status.Should().Be(ConstructionStatus.Destructed);
        parent.Status.Should().Be(ConstructionStatus.Destructed);
        Volatile.Read(ref hookRuns).Should().Be(1);
    }

    [Fact]
    public async Task BackgroundParentHook_DrivesItsMembers()
    {
        using var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var a = Leaf("a", hub);
        var b = Leaf("b", hub);
        var parent = new ConsumerVM("parent", hub, dispatcher, background: true)
        {
            ConstructMembers = [a, b],
            DestructMembers = [b, a],
        };

        var construct = parent.ConstructAsync();
        a.Status.Should().Be(ConstructionStatus.Destructed);
        Drain(dispatcher);
        await construct.WaitAsync(Liveness.HangGuard);
        parent.Status.Should().Be(ConstructionStatus.Constructed);
        a.Status.Should().Be(ConstructionStatus.Constructed);
        b.Status.Should().Be(ConstructionStatus.Constructed);

        var destruct = parent.DestructAsync();
        Drain(dispatcher);
        await destruct.WaitAsync(Liveness.HangGuard);
        parent.Status.Should().Be(ConstructionStatus.Destructed);
        a.Status.Should().Be(ConstructionStatus.Destructed);
        b.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Reconstruct_RunsTheDestructWalkThenTheConstructWalk()
    {
        using var hub = new TestHub();
        var a = Leaf("a", hub);
        var b = Leaf("b", hub);
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance)
        {
            ConstructMembers = [a, b],
            DestructMembers = [b, a],
        };
        parent.Construct();
        var recorded = Record(hub);

        parent.Reconstruct();

        recorded.Should().Equal(
            "parent Destructing",
            "b Destructing", "b Destructed",
            "a Destructing", "a Destructed",
            "parent Destructed",
            "parent Constructing",
            "a Constructing", "a Constructed",
            "b Constructing", "b Constructed",
            "parent Constructed");
    }

    // ── OwnMember ────────────────────────────────────────────────────────────

    [Fact]
    public void OwnMember_ReturnsTheMember_AndDoesNotConstructIt()
    {
        using var hub = new TestHub();
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance);
        var member = Leaf("member", hub);

        parent.Member(member).Should().BeSameAs(member);
        parent.Construct();

        member.Status.Should().Be(ConstructionStatus.Destructed);
        parent.Dispose();
        member.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void OwnMember_AfterDisposed_DisposesAtOnce_AndPropagatesItsFailure()
    {
        using var hub = new TestHub();
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance);
        parent.Dispose();
        var failure = new InvalidOperationException("late member failed");
        var late = new DisposeHookVM("late", hub, () => throw failure);

        var act = () => parent.Member(late);

        Assert.Same(failure, Assert.Throws<InvalidOperationException>(act));
        late.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void OwnMember_OfItself_Throws()
    {
        using var hub = new TestHub();
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance);

        var act = () => parent.Member(parent);

        act.Should().Throw<InvalidOperationException>().WithMessage("*cannot own itself*");
        parent.Dispose();
        parent.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void OwnMember_Null_Throws()
    {
        using var hub = new TestHub();
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance);

        var act = () => parent.Member<IComponentVM>(null!);

        act.Should().Throw<ArgumentNullException>();
    }

    [Fact]
    public void Dispose_ReentrantDuringMemberCascade_IsANoOp()
    {
        using var hub = new TestHub();
        var recorded = Record(hub);
        var statusDuringReentry = ConstructionStatus.Destructed;
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance);
        var first = parent.Member(new DisposeHookVM("first", hub, () =>
        {
            parent.Dispose();
            statusDuringReentry = parent.Status;
        }));
        var second = parent.Member(Leaf("second", hub));

        parent.Dispose();

        statusDuringReentry.Should().NotBe(ConstructionStatus.Disposed);
        recorded.Where(entry => entry.EndsWith(" Disposed", StringComparison.Ordinal))
            .Should().Equal("first Disposed", "second Disposed", "parent Disposed");
        first.Status.Should().Be(ConstructionStatus.Disposed);
        second.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public async Task Dispose_FromAnotherThreadDuringMemberCascade_ReturnsAtOnce_AndPublishesNothing()
    {
        using var hub = new TestHub();
        var recorded = Record(hub);
        using var firstDisposing = new ManualResetEventSlim();
        using var otherReturned = new ManualResetEventSlim();
        var otherReturnedInTime = false;
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance);
        parent.Member(new DisposeHookVM("m1", hub, () =>
        {
            firstDisposing.Set();
            otherReturnedInTime = otherReturned.Wait(Liveness.HangGuard);
        }));
        parent.Member(Leaf("m2", hub));
        var statusWhenOtherReturned = ConstructionStatus.Destructed;
        var other = Task.Run(() =>
        {
            firstDisposing.Wait(Liveness.HangGuard).Should().BeTrue();
            parent.Dispose();
            statusWhenOtherReturned = parent.Status;
            otherReturned.Set();
        });

        parent.Dispose();
        await other.WaitAsync(Liveness.HangGuard);

        otherReturnedInTime.Should().BeTrue("the second Dispose() must return while m1 is still disposing");
        statusWhenOtherReturned.Should().NotBe(ConstructionStatus.Disposed);
        recorded.Where(entry => entry.EndsWith(" Disposed", StringComparison.Ordinal))
            .Should().Equal("m1 Disposed", "m2 Disposed", "parent Disposed");
        parent.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void OwnMember_DuringTheDisposeCascade_DisposesAtOnce()
    {
        using var hub = new TestHub();
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance);
        var late = Leaf("late", hub);
        var lateStatusAfterRegistration = ConstructionStatus.Destructed;
        parent.Member(new DisposeHookVM("first", hub, () =>
        {
            parent.Member(late);
            lateStatusAfterRegistration = late.Status;
        }));

        parent.Dispose();

        lateStatusAfterRegistration.Should().Be(ConstructionStatus.Disposed);
        parent.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void Dispose_KeepsTheFirstMemberFailure()
    {
        using var hub = new TestHub();
        var firstFailure = new InvalidOperationException("first");
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance);
        var first = parent.Member(new DisposeHookVM("first", hub, () => throw firstFailure));
        var second = parent.Member(new DisposeHookVM("second", hub,
            () => throw new InvalidOperationException("second")));
        var third = parent.Member(Leaf("third", hub));

        Assert.Same(firstFailure, Assert.Throws<InvalidOperationException>(parent.Dispose));

        first.Status.Should().Be(ConstructionStatus.Disposed);
        second.Status.Should().Be(ConstructionStatus.Disposed);
        third.Status.Should().Be(ConstructionStatus.Disposed);
        parent.Status.Should().Be(ConstructionStatus.Disposed);
        parent.Dispose();
    }

    [Fact]
    public void Dispose_DuringAPendingWalk_AbandonsItBeforeDisposingMembers()
    {
        using var hub = new TestHub();
        var childDispatcher = new TestDispatcher();
        var background = Leaf("background", hub, childDispatcher, background: true);
        var next = Leaf("next", hub);
        var parent = new ConsumerVM("parent", hub, NullDispatcher.Instance)
        {
            ConstructMembers = [background, next],
        };
        parent.Member(background);
        parent.Member(next);
        _ = parent.ConstructAsync();
        parent.Status.Should().Be(ConstructionStatus.Constructing);

        parent.Dispose();
        Drain(childDispatcher);

        parent.Status.Should().Be(ConstructionStatus.Disposed);
        background.Status.Should().Be(ConstructionStatus.Disposed);
        next.Status.Should().Be(ConstructionStatus.Disposed);
    }
}
