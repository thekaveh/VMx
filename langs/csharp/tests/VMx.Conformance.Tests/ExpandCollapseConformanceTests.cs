using System.Collections;
using FluentAssertions;
using VMx.Capabilities;
using VMx.Components;
using VMx.Lifecycle;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for expand / collapse, EXP-001..008.
/// See spec/05-component-vm.md, spec/13-tree-utilities.md, ADR-0015, ADR-0159.
/// </summary>
public class ExpandCollapseConformanceTests
{
    // ── EXP-001 ─────────────────────────────────────────────────────────────

    /// <summary>EXP-001: ExpandableState defaults to collapsed.</summary>
    [Fact, Trait("Conformance", "EXP-001")]
    public void EXP_001_Defaults_To_Collapsed()
    {
        using var e = new ExpandableState();
        e.IsExpanded.Should().BeFalse();
        e.CanExpand().Should().BeTrue();
        e.CanCollapse().Should().BeFalse();
    }

    // ── EXP-002 ─────────────────────────────────────────────────────────────

    /// <summary>EXP-002: Expand flips state, emits change once.</summary>
    [Fact, Trait("Conformance", "EXP-002")]
    public void EXP_002_Expand_Flips_And_Emits()
    {
        using var e = new ExpandableState();
        var observed = new List<bool>();
        using var sub = e.IsExpandedChanged.Subscribe(observed.Add);
        e.Expand();
        e.IsExpanded.Should().BeTrue();
        observed.Should().Equal(true);
        e.Expand(); // no-op
        observed.Should().Equal(true);
    }

    // ── EXP-003 ─────────────────────────────────────────────────────────────

    /// <summary>EXP-003: Collapse flips state back.</summary>
    [Fact, Trait("Conformance", "EXP-003")]
    public void EXP_003_Collapse_Flips_Back()
    {
        using var e = new ExpandableState(initiallyExpanded: true);
        var observed = new List<bool>();
        using var sub = e.IsExpandedChanged.Subscribe(observed.Add);
        e.Collapse();
        e.IsExpanded.Should().BeFalse();
        observed.Should().Equal(false);
    }

    // ── EXP-004 ─────────────────────────────────────────────────────────────

    /// <summary>EXP-004: ToggleExpansion alternates state.</summary>
    [Fact, Trait("Conformance", "EXP-004")]
    public void EXP_004_Toggle_Alternates()
    {
        using var e = new ExpandableState();
        e.ToggleExpansion();
        e.ToggleExpansion();
        e.IsExpanded.Should().BeFalse();
        e.ToggleExpansion();
        e.IsExpanded.Should().BeTrue();
    }

    // ── EXP-005 ─────────────────────────────────────────────────────────────

    /// <summary>EXP-005: walk_expanded skips descendants of collapsed nodes.</summary>
    [Fact, Trait("Conformance", "EXP-005")]
    public void EXP_005_WalkExpanded_Skips_Collapsed()
    {
        var a = new FakeLeaf("a");
        var b1 = new FakeLeaf("b1");
        var b2 = new FakeLeaf("b2");
        var bCollapsed = new ExpandableComposite("b", new[] { b1, b2 }, expanded: false);
        var root = new ExpandableComposite("root", new IComponentVM[] { a, bCollapsed }, expanded: true);

        var visited = VMx.Tree.Tree.WalkExpanded(root).ToList();
        visited.Should().Contain((IComponentVM)root);
        visited.Should().Contain((IComponentVM)a);
        visited.Should().Contain((IComponentVM)bCollapsed);
        visited.Should().NotContain((IComponentVM)b1);
        visited.Should().NotContain((IComponentVM)b2);
    }

    // ── EXP-006 ─────────────────────────────────────────────────────────────

    /// <summary>EXP-006: command predicates track the can* checks and re-fire on each change.</summary>
    [Fact, Trait("Conformance", "EXP-006")]
    public void EXP_006_CommandPredicates_Track_CanChecks_And_Refire()
    {
        var state = new ExpandableState();
        var expand = state.ExpandCommand;
        var collapse = state.CollapseCommand;
        var toggle = state.ToggleExpansionCommand;
        var counts = new int[3];
        expand.CanExecuteChanged += (_, _) => counts[0]++;
        collapse.CanExecuteChanged += (_, _) => counts[1]++;
        toggle.CanExecuteChanged += (_, _) => counts[2]++;

        expand.CanExecute(null).Should().BeTrue();
        collapse.CanExecute(null).Should().BeFalse();
        toggle.CanExecute(null).Should().BeTrue();

        state.Expand();
        counts.Should().Equal(1, 1, 1);
        expand.CanExecute(null).Should().BeFalse();
        collapse.CanExecute(null).Should().BeTrue();
        toggle.CanExecute(null).Should().BeTrue();

        // A no-op verb is not an expansion change.
        state.Expand();
        counts.Should().Equal(1, 1, 1);

        state.Collapse();
        counts.Should().Equal(2, 2, 2);
        expand.CanExecute(null).Should().BeTrue();
        collapse.CanExecute(null).Should().BeFalse();

        state.ExpandCommand.Should().BeSameAs(expand);
        state.CollapseCommand.Should().BeSameAs(collapse);
        state.ToggleExpansionCommand.Should().BeSameAs(toggle);
    }

    // ── EXP-007 ─────────────────────────────────────────────────────────────

    /// <summary>EXP-007: executing each command performs its verb.</summary>
    [Fact, Trait("Conformance", "EXP-007")]
    public void EXP_007_Executing_Each_Command_Performs_Its_Verb()
    {
        var state = new ExpandableState();
        var observed = new List<bool>();
        using var sub = state.IsExpandedChanged.Subscribe(observed.Add);

        state.ExpandCommand.Execute(null);
        state.IsExpanded.Should().BeTrue();
        // The predicate is false while expanded, so a second execute is a no-op.
        state.ExpandCommand.Execute(null);
        observed.Should().Equal(true);

        state.CollapseCommand.Execute(null);
        state.IsExpanded.Should().BeFalse();
        state.CollapseCommand.Execute(null);
        observed.Should().Equal(true, false);

        state.ToggleExpansionCommand.Execute(null);
        state.IsExpanded.Should().BeTrue();
        state.ToggleExpansionCommand.Execute(null);
        state.IsExpanded.Should().BeFalse();
        observed.Should().Equal(true, false, true, false);
    }

    // ── EXP-008 ─────────────────────────────────────────────────────────────

    /// <summary>EXP-008: helper dispose makes its commands inert.</summary>
    [Fact, Trait("Conformance", "EXP-008")]
    public void EXP_008_Helper_Dispose_Makes_Commands_Inert()
    {
        var state = new ExpandableState();
        var commands = new[] { state.ExpandCommand, state.CollapseCommand, state.ToggleExpansionCommand };
        var observed = new List<bool>();
        using var sub = state.IsExpandedChanged.Subscribe(observed.Add);

        state.Dispose();

        foreach (var command in commands)
        {
            command.CanExecute(null).Should().BeFalse();
            command.Execute(null);
        }
        state.IsExpanded.Should().BeFalse();
        observed.Should().BeEmpty();

        // A command first read after disposal is inert as well.
        var late = new ExpandableState();
        late.Dispose();
        foreach (var command in new[] { late.ExpandCommand, late.CollapseCommand, late.ToggleExpansionCommand })
        {
            command.CanExecute(null).Should().BeFalse();
            command.Execute(null);
        }
        late.IsExpanded.Should().BeFalse();
        late.ExpandCommand.Should().BeSameAs(late.ExpandCommand);
    }

    // ── fixtures ────────────────────────────────────────────────────────────

    private sealed class FakeLeaf(string name) : FakeVm
    {
        public override string Name => name;
    }

    private sealed class ExpandableComposite(string name, IEnumerable<IComponentVM> children, bool expanded)
        : FakeVm, IEnumerable<IComponentVM>, IExpandable
    {
        public override string Name => name;
        private readonly IComponentVM[] _children = children.ToArray();
        public bool IsExpanded { get; private set; } = expanded;
        public bool CanExpand() => !IsExpanded;
        public void Expand() => IsExpanded = true;
        public IEnumerator<IComponentVM> GetEnumerator() => ((IEnumerable<IComponentVM>)_children).GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }

    // Minimal IComponentVM stub for tree-walk tests (avoids the full ComponentVMBase wiring).
    private abstract class FakeVm : IComponentVM
    {
        public abstract string Name { get; }
        public string Hint => "";
        public ViewModelType Type => ViewModelType.Component;
        public bool IsCurrent => false;
        public bool IsConstructed => true;
        public ConstructionStatus Status => ConstructionStatus.Constructed;
        public VMx.Services.IMessageHub Hub => VMx.Services.NullMessageHub.Instance;
        public System.Windows.Input.ICommand SelectCommand => null!;
        public System.Windows.Input.ICommand DeselectCommand => null!;
        public System.Windows.Input.ICommand SelectNextCommand => null!;
        public System.Windows.Input.ICommand SelectPreviousCommand => null!;
        public System.Windows.Input.ICommand ReconstructCommand => null!;
        public bool CanConstruct() => false;
        public void Construct() { }
        public Task ConstructAsync() => Task.CompletedTask;
        public bool CanDestruct() => false;
        public void Destruct() { }
        public Task DestructAsync() => Task.CompletedTask;
        public bool CanReconstruct() => false;
        public void Reconstruct() { }
        public Task ReconstructAsync() => Task.CompletedTask;
        public bool CanSelect() => false;
        public void Select() { }
        public bool CanDeselect() => false;
        public void Deselect() { }
        public void Dispose() { }
        public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged
        {
            add { }
            remove { }
        }
    }

    // ----- Dispose path — not a conformance ID, but a regression guard for
    // the _disposed idempotence guard and the Subject completion in
    // ExpandableState.Dispose(). Mirrors the Python tests in
    // tests/conformance/test_expand_collapse.py.
    [Fact]
    public void ExpandableState_Dispose_IsIdempotent()
    {
        var state = new ExpandableState(initiallyExpanded: true);
        state.Dispose();
        Action act = () => state.Dispose();
        act.Should().NotThrow();
    }

    [Fact]
    public void ExpandableState_Dispose_CompletesChangeObservable()
    {
        var state = new ExpandableState(initiallyExpanded: false);
        var completed = false;
        using var sub = state.IsExpandedChanged.Subscribe(_ => { }, () => completed = true);
        state.Dispose();
        completed.Should().BeTrue();
    }

    [Fact]
    public void ExpandableState_Dispose_MakesLaterMutationsInert()
    {
        var state = new ExpandableState(initiallyExpanded: false);
        state.Dispose();

        state.Expand();
        state.Collapse();
        state.ToggleExpansion();

        state.IsExpanded.Should().BeFalse();
    }
}
