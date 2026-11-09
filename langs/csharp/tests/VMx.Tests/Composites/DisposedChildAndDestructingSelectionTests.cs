using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Forwarding;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Composites;

/// <summary>
/// Regressions for the disposed-child and Destructing selection rules
/// (spec/02 §6, spec/06 §4.3 rules 2, 8 and 9, ADR-0188, ADR-0189): a walk
/// stops waiting for a child that reaches Disposed, a selection from another
/// thread or an asynchronous delivery while Destructing is dropped, a refused
/// child Select() at the commit is silent, and the dispose clear works through
/// a forwarding decorator and refuses a re-entrant selection of the disposed
/// child.
/// </summary>
public sealed class DisposedChildAndDestructingSelectionTests
{
    private sealed class NoOpForwardingVM(IComponentVM<string> wrapped) : ForwardingComponentVM<string>(wrapped)
    {
    }

    private static ComponentVM<string> Leaf(
        string name,
        IDispatcher? dispatcher = null,
        bool background = false,
        Action? onDestruct = null)
    {
        var builder = ComponentVM<string>.Builder()
            .Name(name).Services(new TestHub(), dispatcher ?? NullDispatcher.Instance)
            .Model(name).Background(background);
        if (onDestruct is not null) builder = builder.OnDestruct(onDestruct);
        return builder.Build();
    }

    [Fact]
    public async Task Construct_walk_stops_waiting_for_a_child_disposed_during_the_wait()
    {
        var childDispatcher = new TestDispatcher();
        var a = Leaf("a", childDispatcher, background: true);
        var b = Leaf("b");
        var sut = CompositeVM<ComponentVM<string>>.Builder()
            .Name("p").Services(new TestHub(), NullDispatcher.Instance)
            .Children(() => [a, b]).Build();

        var construct = sut.ConstructAsync();
        sut.Status.Should().Be(ConstructionStatus.Constructing);
        a.Status.Should().Be(ConstructionStatus.Constructing);

        a.Dispose();
        await construct.WaitAsync(HangGuard);

        sut.Status.Should().Be(ConstructionStatus.Constructed);
        a.Status.Should().Be(ConstructionStatus.Disposed);
        b.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void A_selection_from_another_thread_during_the_child_walk_is_dropped()
    {
        CompositeVM<ComponentVM<string>>? sut = null;
        ComponentVM<string>? b = null;
        Exception? error = null;
        var a = Leaf("a", onDestruct: () =>
        {
            var selector = new Thread(() =>
            {
                try { sut!.Current = b; }
                catch (Exception caught) { error = caught; }
            });
            selector.Start();
            selector.Join(HangGuard).Should().BeTrue("a selection never waits for the destruct");
        });
        b = Leaf("b");
        sut = CompositeVM<ComponentVM<string>>.Builder()
            .Name("p").Services(new TestHub(), NullDispatcher.Instance)
            .Children(() => [a, b]).Build();
        sut.Construct();
        sut.Current = a;

        sut.Destruct();

        error.Should().BeNull();
        sut.Current.Should().BeNull();
        b.IsCurrent.Should().BeFalse();
        sut.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void An_async_delivery_while_Destructing_is_dropped()
    {
        var dispatcher = new TestDispatcher();
        var b = Leaf("b", dispatcher);
        var a = Leaf("a", dispatcher, onDestruct: () => dispatcher.ForegroundScheduler.AdvanceBy(1));
        var sut = CompositeVM<ComponentVM<string>>.Builder()
            .Name("p").Services(new TestHub(), dispatcher)
            .AsyncSelection(true)
            .Children(() => [a, b]).Build();
        sut.Construct();
        dispatcher.AdvanceAll();
        sut.Status.Should().Be(ConstructionStatus.Constructed);

        sut.Current = b; // scheduled, delivered inside a's destruct hook
        sut.Destruct();
        dispatcher.AdvanceAll();

        sut.Status.Should().Be(ConstructionStatus.Destructed);
        sut.Current.Should().BeNull();
        b.IsCurrent.Should().BeFalse();
    }

    [Fact]
    public void A_child_Select_refused_at_the_commit_is_silent()
    {
        var vm = Leaf("vm");
        var sut = CompositeVM<ComponentVM<string>>.Builder()
            .Name("p").Services(new TestHub(), NullDispatcher.Instance)
            .Children(() => [vm]).Build();
        sut.Construct();
        Exception? error = null;
        var selector = new Thread(() =>
        {
            try { vm.Select(); }
            catch (Exception caught) { error = caught; }
        });

        // The selector passes the entry check, then waits for the lane while
        // this thread destructs vm, as another thread could (#1424).
        lock (CompositeCurrentChangeCoordinator.Gate)
        {
            selector.Start();
            SpinWait.SpinUntil(
                    () => (selector.ThreadState & ThreadState.WaitSleepJoin) != 0, HangGuard)
                .Should().BeTrue("the selector waits for the coordination lane");
            vm.Destruct();
        }

        selector.Join(HangGuard).Should().BeTrue("the selection returns within the hang guard");
        error.Should().BeNull();
        sut.Current.Should().BeNull();
        vm.IsCurrent.Should().BeFalse();
    }

    [Fact]
    public void Disposing_a_current_forwarding_decorator_clears_Current()
    {
        var inner = Leaf("inner");
        var decorator = new NoOpForwardingVM(inner);
        var changes = new List<IComponentVM?>();
        var sut = CompositeVM<IComponentVM>.Builder()
            .Name("p").Services(new TestHub(), NullDispatcher.Instance)
            .Children(() => [])
            .OnCurrentChanged(changes.Add)
            .Build();
        sut.Add(decorator);
        sut.Construct();
        sut.Current = decorator;
        changes.Clear();

        decorator.Dispose();

        sut.Current.Should().BeNull();
        decorator.IsCurrent.Should().BeFalse();
        changes.Should().Equal(new IComponentVM?[] { null });
    }

    [Fact]
    public void Dispose_clear_refuses_a_reentrant_selection_of_the_disposed_child()
    {
        CompositeVM<ComponentVM<string>>? sut = null;
        ComponentVM<string>? a = null;
        var errors = new List<Exception>();
        a = Leaf("a");
        var b = Leaf("b");
        sut = CompositeVM<ComponentVM<string>>.Builder()
            .Name("p").Services(new TestHub(), NullDispatcher.Instance)
            .Children(() => [a, b])
            .OnCurrentChanged(value =>
            {
                if (value is not null) return;
                try { sut!.Current = a; }
                catch (InvalidOperationException error) { errors.Add(error); }
            })
            .Build();
        sut.Construct();
        sut.Current = a;

        a.Dispose();

        errors.Should().ContainSingle().Which.Message.Should().Contain("not a member");
        sut.Current.Should().BeNull();
        a.IsCurrent.Should().BeFalse();
    }
}
