using System.ComponentModel;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Tests.Composites;

/// <summary>
/// Replacing the current child, and the Constructed check of a selection. An
/// index replacement keeps the replaced child owned and current until its
/// commit, which frees the child and clears Current in one locked section. No
/// container can adopt the child while it is still current here, and a failed
/// replacement restores it silently (spec/06 §3, §4.2, §4.3 rule 6, #1219).
/// SelectComponent checks Constructed again at its commit, also at an
/// asynchronous delivery (spec/06 §3.1, §4.3 rule 7, #1220). Mirrors the Swift
/// CompositeVMMembershipTests and CompositeSelectionTests.
/// </summary>
public sealed class ReplaceAndSelectRaceTests
{
    private sealed class HookFailedException : Exception
    {
    }

    private static ComponentVM Leaf(string name, Action? onConstruct = null, IDispatcher? dispatcher = null)
    {
        var builder = ComponentVM.Builder().Name(name).Services(new TestHub(), dispatcher ?? NullDispatcher.Instance);
        if (onConstruct is not null) builder = builder.OnConstruct(onConstruct);
        return builder.Build();
    }

    private static CompositeVM<ComponentVM> Composite(
        IEnumerable<ComponentVM> children,
        List<string?>? changes = null,
        IDispatcher? dispatcher = null,
        bool asyncSelection = false)
    {
        var members = children.ToArray();
        return CompositeVM<ComponentVM>.Builder()
            .Name("composite").Services(new TestHub(), dispatcher ?? NullDispatcher.Instance)
            .Children(() => members)
            .AutoConstructOnAdd(true)
            .AsyncSelection(asyncSelection)
            .OnCurrentChanged(value => changes?.Add(value?.Name))
            .Build();
    }

    /// <summary>
    /// A Constructed composite [a, b] with a current, and a replacement whose
    /// construct hook runs inside the replacement's transaction.
    /// </summary>
    private sealed class Replacement
    {
        public Replacement(Action<ComponentVM, CompositeVM<ComponentVM>> hook)
        {
            A = Leaf("a");
            B = Leaf("b");
            Sut = Composite(new[] { A, B }, Changes);
            Sut.Construct();
            Sut.Current = A;
            Changes.Clear();
            ReplacementVM = Leaf("replacement", () => hook(A, Sut));
        }

        public ComponentVM A { get; }

        public ComponentVM B { get; }

        public CompositeVM<ComponentVM> Sut { get; }

        public ComponentVM ReplacementVM { get; }

        public List<string?> Changes { get; } = new();
    }

    private static CompositeVM<ComponentVM>[] Holders(ComponentVM child, params CompositeVM<ComponentVM>[] composites)
        => composites.Where(composite => composite.Any(member => ReferenceEquals(member, child))).ToArray();

    [Fact]
    public void Replacement_hook_sees_the_current_child_still_owned_and_flagged()
    {
        (bool Owned, bool Current, bool Flag)? observed = null;
        var scenario = new Replacement((a, sut) =>
            observed = (ReferenceEquals(a.Parent, sut), ReferenceEquals(sut.Current, a), a.IsCurrent));

        scenario.Sut[0] = scenario.ReplacementVM;

        observed.Should().NotBeNull("the replacement's construct hook ran");
        observed!.Value.Current.Should().BeTrue("Current changes only at the commit");
        observed.Value.Owned.Should().BeTrue("the composite still owns its current child");
        observed.Value.Flag.Should().Be(observed.Value.Current, "IsCurrent matches Current inside the hook");
        scenario.Sut.Current.Should().BeNull();
        scenario.A.IsCurrent.Should().BeFalse();
        scenario.A.Parent.Should().BeNull();
        scenario.Changes.Should().Equal(new string?[] { null });
    }

    [Fact]
    public void Replacement_hook_cannot_adopt_and_select_the_replaced_current_child()
    {
        var other = Composite(Array.Empty<ComponentVM>());
        other.Construct();
        var scenario = new Replacement((a, _) =>
        {
            try
            {
                other.Add(a);
                other.Current = a;
            }
            catch (InvalidOperationException)
            {
            }
        });

        scenario.Sut[0] = scenario.ReplacementVM;

        var child = scenario.A;
        scenario.Sut.Current.Should().BeNull();
        child.IsCurrent.Should().Be(ReferenceEquals(other.Current, child),
            "the commit's clear never resets a selection in another composite (COMP-006)");
        var holders = Holders(child, scenario.Sut, other);
        holders.Length.Should().BeLessThanOrEqualTo(1);
        if (holders.Length == 1) child.Parent.Should().BeSameAs(holders[0]);
    }

    [Fact]
    public void Failed_replacement_leaves_the_replaced_child_in_exactly_one_composite()
    {
        var other = Composite(Array.Empty<ComponentVM>());
        other.Construct();
        var scenario = new Replacement((a, _) =>
        {
            try { other.Add(a); }
            catch (InvalidOperationException) { }
            throw new HookFailedException();
        });

        var act = () => { scenario.Sut[0] = scenario.ReplacementVM; };

        act.Should().Throw<HookFailedException>();
        var child = scenario.A;
        var holders = Holders(child, scenario.Sut, other);
        holders.Should().HaveCount(1, "a is a member of exactly one composite");
        child.Parent.Should().BeSameAs(holders[0], "a's owner is the composite that holds it");
        scenario.Sut.Should().Equal(scenario.A, scenario.B);
        scenario.ReplacementVM.Parent.Should().BeNull();
    }

    [Fact]
    public void Failed_replacement_of_the_current_child_restores_it_silently()
    {
        var scenario = new Replacement((_, _) => throw new HookFailedException());
        var events = new List<string>();
        var properties = new List<string?>();
        scenario.Sut.CollectionChanged += (_, e) => events.Add(e.Action.ToString());
        ((INotifyPropertyChanged)scenario.Sut).PropertyChanged += (_, e) => properties.Add(e.PropertyName);
        ((INotifyPropertyChanged)scenario.A).PropertyChanged += (_, e) => properties.Add(e.PropertyName);

        var act = () => { scenario.Sut[0] = scenario.ReplacementVM; };

        act.Should().Throw<HookFailedException>();
        scenario.Sut.Should().Equal(scenario.A, scenario.B);
        scenario.Sut.Current.Should().BeSameAs(scenario.A);
        scenario.A.IsCurrent.Should().BeTrue();
        scenario.A.Parent.Should().BeSameAs(scenario.Sut);
        events.Should().BeEmpty();
        scenario.Changes.Should().BeEmpty();
        properties.Should().NotContain("Current").And.NotContain("IsCurrent");
    }

    [Fact]
    public void SelectComponent_refuses_a_child_destructed_after_the_entry_check()
    {
        var vm = Leaf("vm");
        var sut = Composite(new[] { vm });
        sut.Construct();
        Exception? error = null;
        var selector = new Thread(() =>
        {
            try { sut.SelectComponent(vm); }
            catch (Exception caught) { error = caught; }
        });

        // The selector passes the entry check, then waits for the lane while
        // this thread destructs vm, as another thread could (#1220).
        lock (CompositeCurrentChangeCoordinator.Gate)
        {
            selector.Start();
            SpinWait.SpinUntil(
                    () => (selector.ThreadState & ThreadState.WaitSleepJoin) != 0, HangGuard)
                .Should().BeTrue("the selector waits for the coordination lane");
            vm.Destruct();
        }

        selector.Join(HangGuard).Should().BeTrue("the selection returns within the hang guard");
        vm.Status.Should().Be(ConstructionStatus.Destructed);
        error.Should().BeOfType<InvalidOperationException>();
        sut.Current.Should().BeNull();
        vm.IsCurrent.Should().BeFalse();
    }

    [Fact]
    public void Async_SelectComponent_delivery_drops_a_child_destructed_after_the_call()
    {
        var dispatcher = new TestDispatcher();
        var vm = Leaf("vm", dispatcher: dispatcher);
        var sut = Composite(new[] { vm }, dispatcher: dispatcher, asyncSelection: true);
        sut.Construct();
        dispatcher.AdvanceAll();

        sut.SelectComponent(vm);
        vm.Destruct();
        dispatcher.ForegroundScheduler.AdvanceBy(1);

        vm.Status.Should().Be(ConstructionStatus.Destructed);
        sut.Current.Should().BeNull("the delivery checks Constructed again");
        vm.IsCurrent.Should().BeFalse();
    }

    [Fact]
    public void SelectComponent_selects_a_constructed_member()
    {
        var vm = Leaf("vm");
        var sut = Composite(new[] { vm });
        sut.Construct();

        sut.SelectComponent(vm);

        sut.Current.Should().BeSameAs(vm);
        vm.IsCurrent.Should().BeTrue();
    }
}
