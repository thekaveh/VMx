using System.Collections.Specialized;
using FluentAssertions;
using VMx.Components;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for GroupVM covering GRP-001..004.
/// See spec/07-group-vm.md and spec/12-conformance.md.
/// </summary>
public class GroupVMConformanceTests
{
    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (GroupVM<ComponentVM<string>> group, TestHub hub, TestDispatcher dispatcher)
        BuildGroup(string name = "root")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        return (group, hub, dispatcher);
    }

    private static ComponentVM<string> BuildChild(
        TestHub hub, TestDispatcher dispatcher, string name = "child")
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, dispatcher).Model("m").Build();

    // ── GRP-001 — Add emits CollectionChanged(action=Add) ────────────────────

    /// <summary>
    /// GRP-001: Add on an empty Constructed GroupVM emits CollectionChanged with
    /// action=Add, newItems=[vm], newIndex=0.
    /// </summary>
    [Fact, Trait("Conformance", "GRP-001")]
    public void GRP_001_Add_Emits_CollectionChanged_Add()
    {
        var (group, hub, dispatcher) = BuildGroup();
        group.Construct();
        var child = BuildChild(hub, dispatcher);

        NotifyCollectionChangedEventArgs? evt = null;
        group.CollectionChanged += (_, e) => evt = e;

        group.Add(child);

        evt.Should().NotBeNull();
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Add);
        evt.NewItems.Should().NotBeNull();
        evt.NewItems![0].Should().BeSameAs(child);
        evt.NewStartingIndex.Should().Be(0);
    }

    // ── GRP-002 — Group lacks child-navigation/child-selection members ────────

    /// <summary>
    /// GRP-002: The API surface of GroupVM must:
    /// - have no <c>Current</c> property
    /// - have no <c>SelectComponent</c>, <c>DeselectComponent</c>, or
    ///   <c>CanSelectComponent</c> methods
    /// - DO have <c>SelectCommand</c> and <c>DeselectCommand</c> (IComponentVM baseline)
    /// - DO have <c>SelectNextCommand</c> and <c>SelectPreviousCommand</c> (inherited from
    ///   the IComponentVM baseline) but always-disabled — their predicates return false,
    ///   since the group exposes no internal navigation slot.
    /// </summary>
    [Fact, Trait("Conformance", "GRP-002")]
    public void GRP_002_Group_Lacks_Child_Navigation_And_Selection_Members()
    {
        var type = typeof(GroupVM<ComponentVM<string>>);

        // No Current property.
        type.GetProperty("Current")
            .Should().BeNull("GroupVM must not expose a Current property");

        // No select_component / deselect_component / can_select_component methods.
        type.GetMethod("SelectComponent")
            .Should().BeNull("GroupVM must not expose SelectComponent");
        type.GetMethod("DeselectComponent")
            .Should().BeNull("GroupVM must not expose DeselectComponent");
        type.GetMethod("CanSelectComponent")
            .Should().BeNull("GroupVM must not expose CanSelectComponent");

        // SelectCommand and DeselectCommand ARE present (from IComponentVM baseline).
        var (group, _, _) = BuildGroup();
        group.SelectCommand.Should().NotBeNull("SelectCommand must be present (IComponentVM baseline)");
        group.DeselectCommand.Should().NotBeNull("DeselectCommand must be present (IComponentVM baseline)");

        // SelectNextCommand and SelectPreviousCommand ARE present (inherited from the
        // IComponentVM baseline) but always-disabled: the group has no internal
        // navigation slot, so their predicates return false (spec GRP-002).
        group.SelectNextCommand.Should().NotBeNull("SelectNextCommand must be present (IComponentVM baseline)");
        group.SelectNextCommand.CanExecute(null).Should()
            .BeFalse("SelectNextCommand must be always-disabled for GroupVM");
        group.SelectPreviousCommand.Should().NotBeNull("SelectPreviousCommand must be present (IComponentVM baseline)");
        group.SelectPreviousCommand.CanExecute(null).Should()
            .BeFalse("SelectPreviousCommand must be always-disabled for GroupVM");
    }

    // ── GRP-003 — Construct waits until all children reach Constructed ────────

    /// <summary>
    /// GRP-003: after group.construct() returns, every child has Status==Constructed
    /// and the group has Status==Constructed.
    /// </summary>
    [Fact, Trait("Conformance", "GRP-003")]
    public void GRP_003_Construct_Waits_Until_All_Children_Constructed()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        var c3 = BuildChild(hub, dispatcher, "c3");
        group.Add(c1);
        group.Add(c2);
        group.Add(c3);

        group.Construct();

        c1.Status.Should().Be(ConstructionStatus.Constructed);
        c2.Status.Should().Be(ConstructionStatus.Constructed);
        c3.Status.Should().Be(ConstructionStatus.Constructed);
        group.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── GRP-004 — Destruct waits until all children reach Destructed ──────────

    /// <summary>
    /// GRP-004: after group.destruct() returns, every child has Status==Destructed
    /// and the group has Status==Destructed.
    /// </summary>
    [Fact, Trait("Conformance", "GRP-004")]
    public void GRP_004_Destruct_Waits_Until_All_Children_Destructed()
    {
        var (group, hub, dispatcher) = BuildGroup();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        var c3 = BuildChild(hub, dispatcher, "c3");
        group.Add(c1);
        group.Add(c2);
        group.Add(c3);
        group.Construct();

        group.Destruct();

        c1.Status.Should().Be(ConstructionStatus.Destructed);
        c2.Status.Should().Be(ConstructionStatus.Destructed);
        c3.Status.Should().Be(ConstructionStatus.Destructed);
        group.Status.Should().Be(ConstructionStatus.Destructed);
    }
}
