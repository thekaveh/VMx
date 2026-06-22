using FluentAssertions;
using VMx.Capabilities;
using VMx.Components;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for capability micro-interfaces, CAP-001..020.
/// See spec/14-capabilities.md and ADR-0010.
/// </summary>
public class CapabilitiesConformanceTests
{
    private static ComponentVM BuildBareComponentVM()
    {
        return ComponentVM.Builder()
            .Name("bare")
            .Services(new TestHub(), new TestDispatcher())
            .Build();
    }

    // ── CAP-001 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-001: ISelectable contract.</summary>
    [Fact, Trait("Conformance", "CAP-001")]
    public void CAP_001_ISelectable_Contract()
    {
        var f = new SelectableFixture();
        f.CanSelect().Should().BeTrue();
        f.Select();
        f.Calls.Should().Be(1);
    }

    private sealed class SelectableFixture : ISelectable
    {
        public int Calls;
        public bool CanSelect() => true;
        public void Select() => Calls++;
    }

    // ── CAP-002 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-002: IDeselectable contract.</summary>
    [Fact, Trait("Conformance", "CAP-002")]
    public void CAP_002_IDeselectable_Contract()
    {
        var f = new DeselectableFixture();
        f.CanDeselect().Should().BeTrue();
        f.Deselect();
        f.Calls.Should().Be(1);
    }

    private sealed class DeselectableFixture : IDeselectable
    {
        public int Calls;
        public bool CanDeselect() => true;
        public void Deselect() => Calls++;
    }

    // ── CAP-003 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-003: ISelectionTogglable contract.</summary>
    [Fact, Trait("Conformance", "CAP-003")]
    public void CAP_003_ISelectionTogglable_Contract()
    {
        var f = new SelectionTogglableFixture();
        var initial = f.Selected;
        f.CanToggleSelection().Should().BeTrue();
        f.ToggleSelection();
        f.ToggleSelection();
        f.Selected.Should().Be(initial);
    }

    private sealed class SelectionTogglableFixture : ISelectionTogglable
    {
        public bool Selected;
        public bool CanToggleSelection() => true;
        public void ToggleSelection() => Selected = !Selected;
    }

    // ── CAP-004 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-004: IExpandable contract.</summary>
    [Fact, Trait("Conformance", "CAP-004")]
    public void CAP_004_IExpandable_Contract()
    {
        var f = new ExpandableFixture();
        f.IsExpanded.Should().BeFalse();
        f.CanExpand().Should().BeTrue();
        f.Expand();
        f.IsExpanded.Should().BeTrue();
    }

    private sealed class ExpandableFixture : IExpandable
    {
        public bool IsExpanded { get; private set; }
        public bool CanExpand() => true;
        public void Expand() => IsExpanded = true;
    }

    // ── CAP-005 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-005: ICollapsible contract.</summary>
    [Fact, Trait("Conformance", "CAP-005")]
    public void CAP_005_ICollapsible_Contract()
    {
        var f = new CollapsibleFixture();
        f.CanCollapse().Should().BeTrue();
        f.Collapse();
        f.Calls.Should().Be(1);
    }

    private sealed class CollapsibleFixture : ICollapsible
    {
        public int Calls;
        public bool CanCollapse() => true;
        public void Collapse() => Calls++;
    }

    // ── CAP-006 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-006: IExpansionTogglable contract.</summary>
    [Fact, Trait("Conformance", "CAP-006")]
    public void CAP_006_IExpansionTogglable_Contract()
    {
        var f = new ExpansionTogglableFixture();
        var initial = f.Expanded;
        f.CanToggleExpansion().Should().BeTrue();
        f.ToggleExpansion();
        f.ToggleExpansion();
        f.Expanded.Should().Be(initial);
    }

    private sealed class ExpansionTogglableFixture : IExpansionTogglable
    {
        public bool Expanded;
        public bool CanToggleExpansion() => true;
        public void ToggleExpansion() => Expanded = !Expanded;
    }

    // ── CAP-007 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-007: IClosable contract.</summary>
    [Fact, Trait("Conformance", "CAP-007")]
    public void CAP_007_IClosable_Contract()
    {
        var f = new ClosableFixture();
        f.CanClose().Should().BeTrue();
        f.Close();
        f.Calls.Should().Be(1);
    }

    private sealed class ClosableFixture : IClosable
    {
        public int Calls;
        public bool CanClose() => true;
        public void Close() => Calls++;
    }

    // ── CAP-008 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-008: ISearchable contract.</summary>
    [Fact, Trait("Conformance", "CAP-008")]
    public void CAP_008_ISearchable_Contract()
    {
        var f = new SearchableFixture();
        f.SearchTerm = "abc";
        f.CanSearch().Should().BeTrue();
        f.Search();
        f.SearchTerm.Should().Be("abc");
        f.Searched.Should().ContainSingle().Which.Should().Be("abc");
    }

    private sealed class SearchableFixture : ISearchable
    {
        public string SearchTerm { get; set; } = "";
        public List<string> Searched { get; } = new();
        public bool CanSearch() => true;
        public void Search() => Searched.Add(SearchTerm);
    }

    // ── CAP-009 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-009: IApprovable contract.</summary>
    [Fact, Trait("Conformance", "CAP-009")]
    public void CAP_009_IApprovable_Contract()
    {
        var f = new ApprovableFixture();
        f.CanApprove().Should().BeTrue();
        f.Approve();
        f.Calls.Should().Be(1);
    }

    private sealed class ApprovableFixture : IApprovable
    {
        public int Calls;
        public bool CanApprove() => true;
        public void Approve() => Calls++;
    }

    // ── CAP-010 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-010: ICancelable contract.</summary>
    [Fact, Trait("Conformance", "CAP-010")]
    public void CAP_010_ICancelable_Contract()
    {
        var f = new CancelableFixture();
        f.CanCancel().Should().BeTrue();
        f.Cancel();
        f.Calls.Should().Be(1);
    }

    private sealed class CancelableFixture : ICancelable
    {
        public int Calls;
        public bool CanCancel() => true;
        public void Cancel() => Calls++;
    }

    // ── CAP-011 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-011: ISavable&lt;T&gt; contract.</summary>
    [Fact, Trait("Conformance", "CAP-011")]
    public void CAP_011_ISavable_Contract()
    {
        var f = new SavableFixture();
        f.CanSave("a").Should().BeTrue();
        f.Save("a");
        f.Saved.Should().ContainSingle().Which.Should().Be("a");
    }

    private sealed class SavableFixture : ISavable<string>
    {
        public List<string> Saved { get; } = new();
        public bool CanSave(string item) => true;
        public void Save(string item) => Saved.Add(item);
    }

    // ── CAP-012 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-012: IManagable&lt;T&gt; contract.</summary>
    [Fact, Trait("Conformance", "CAP-012")]
    public void CAP_012_IManagable_Contract()
    {
        var f = new ManagableFixture();
        f.CanManage("x").Should().BeTrue();
        f.Manage("x");
        f.Managed.Should().ContainSingle().Which.Should().Be("x");
    }

    private sealed class ManagableFixture : IManagable<string>
    {
        public List<string> Managed { get; } = new();
        public bool CanManage(string item) => true;
        public void Manage(string item) => Managed.Add(item);
    }

    // ── CAP-013 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-013: INewCreatable contract.</summary>
    [Fact, Trait("Conformance", "CAP-013")]
    public void CAP_013_INewCreatable_Contract()
    {
        var f = new NewCreatableFixture();
        f.CanCreateNew().Should().BeTrue();
        f.CreateNew();
        f.Calls.Should().Be(1);
    }

    private sealed class NewCreatableFixture : INewCreatable
    {
        public int Calls;
        public bool CanCreateNew() => true;
        public void CreateNew() => Calls++;
    }

    // ── CAP-014 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-014: IDeletable&lt;T&gt; contract.</summary>
    [Fact, Trait("Conformance", "CAP-014")]
    public void CAP_014_IDeletable_Contract()
    {
        var f = new DeletableFixture();
        f.CanDelete("a").Should().BeTrue();
        f.Delete("a");
        f.Deleted.Should().ContainSingle().Which.Should().Be("a");
    }

    private sealed class DeletableFixture : IDeletable<string>
    {
        public List<string> Deleted { get; } = new();
        public bool CanDelete(string item) => true;
        public void Delete(string item) => Deleted.Add(item);
    }

    // ── CAP-015 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-015: IUpdatable&lt;T&gt; contract.</summary>
    [Fact, Trait("Conformance", "CAP-015")]
    public void CAP_015_IUpdatable_Contract()
    {
        var f = new UpdatableFixture();
        f.CanUpdate("a").Should().BeTrue();
        f.Update("a");
        f.Updated.Should().ContainSingle().Which.Should().Be("a");
    }

    private sealed class UpdatableFixture : IUpdatable<string>
    {
        public List<string> Updated { get; } = new();
        public bool CanUpdate(string item) => true;
        public void Update(string item) => Updated.Add(item);
    }

    // ── CAP-016 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-016: ICurrentDeletable contract.</summary>
    [Fact, Trait("Conformance", "CAP-016")]
    public void CAP_016_ICurrentDeletable_Contract()
    {
        var f = new CurrentDeletableFixture();
        f.CanDeleteCurrent().Should().BeTrue();
        f.DeleteCurrent();
        f.Calls.Should().Be(1);
    }

    private sealed class CurrentDeletableFixture : ICurrentDeletable
    {
        public int Calls;
        public bool CanDeleteCurrent() => true;
        public void DeleteCurrent() => Calls++;
    }

    // ── CAP-017 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-017: ICurrentUpdatable contract.</summary>
    [Fact, Trait("Conformance", "CAP-017")]
    public void CAP_017_ICurrentUpdatable_Contract()
    {
        var f = new CurrentUpdatableFixture();
        f.CanUpdateCurrent().Should().BeTrue();
        f.UpdateCurrent();
        f.Calls.Should().Be(1);
    }

    private sealed class CurrentUpdatableFixture : ICurrentUpdatable
    {
        public int Calls;
        public bool CanUpdateCurrent() => true;
        public void UpdateCurrent() => Calls++;
    }

    // ── CAP-018 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-018: lifecycle capability set — F implements all three.</summary>
    [Fact, Trait("Conformance", "CAP-018")]
    public void CAP_018_Lifecycle_Capability_Set()
    {
        var f = new LifecycleFixture();
        ((IConstructable)f).CanConstruct().Should().BeTrue();
        ((IDestructable)f).CanDestruct().Should().BeTrue();
        ((IReconstructable)f).CanReconstruct().Should().BeTrue();
        ((IConstructable)f).Construct();
        ((IDestructable)f).Destruct();
        ((IReconstructable)f).Reconstruct();
    }

    private sealed class LifecycleFixture : IConstructable, IDestructable, IReconstructable
    {
        public bool CanConstruct() => true;
        public void Construct() { }
        public Task ConstructAsync() => Task.CompletedTask;
        public bool CanDestruct() => true;
        public void Destruct() { }
        public Task DestructAsync() => Task.CompletedTask;
        public bool CanReconstruct() => true;
        public void Reconstruct() { }
        public Task ReconstructAsync() => Task.CompletedTask;
    }

    // ── CAP-019 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-019: a single VM may implement multiple capabilities.</summary>
    [Fact, Trait("Conformance", "CAP-019")]
    public void CAP_019_Multiple_Capabilities()
    {
        var f = new MultiCapabilityFixture();
        // Query the runtime type for each interface (spec §15: "queried true for
        // all five"). Cast through object so the check is a real runtime `is`
        // test, not a tautological upcast of a statically-typed reference
        // (mirrors the CAP-020 pattern in this file).
        object vm = f;
        (vm is ISelectable).Should().BeTrue();
        (vm is IExpandable).Should().BeTrue();
        (vm is IClosable).Should().BeTrue();
        (vm is IApprovable).Should().BeTrue();
        (vm is ICancelable).Should().BeTrue();

        ((ISelectable)f).Select();
        ((IExpandable)f).Expand();
        ((IClosable)f).Close();
        ((IApprovable)f).Approve();
        ((ICancelable)f).Cancel();

        (f.Selects, f.Expands, f.Closes, f.Approves, f.Cancels)
            .Should().Be((1, 1, 1, 1, 1));
    }

    private sealed class MultiCapabilityFixture
        : ISelectable, IExpandable, IClosable, IApprovable, ICancelable
    {
        public int Selects;
        public int Expands;
        public int Closes;
        public int Approves;
        public int Cancels;
        public bool IsExpanded { get; private set; }

        public bool CanSelect() => true;
        public void Select() => Selects++;
        public bool CanExpand() => true;
        public void Expand() { IsExpanded = true; Expands++; }
        public bool CanClose() => true;
        public void Close() => Closes++;
        public bool CanApprove() => true;
        public void Approve() => Approves++;
        public bool CanCancel() => true;
        public void Cancel() => Cancels++;
    }

    // ── CAP-020 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-020: bare ComponentVM does NOT implement non-baseline capabilities.</summary>
    [Fact, Trait("Conformance", "CAP-020")]
    public void CAP_020_Bare_ComponentVM_Opt_In_Only()
    {
        // Cast to object so the compiler can't constant-fold the type check —
        // the result (false) being known statically is itself a stronger form
        // of CAP-020 confirmation; here we exercise it at runtime as well.
        object vm = BuildBareComponentVM();

        // Non-baseline capabilities — must be false
        (vm is ISelectable).Should().BeFalse();
        (vm is IExpandable).Should().BeFalse();
        (vm is IClosable).Should().BeFalse();
        (vm is INewCreatable).Should().BeFalse();
        (vm is ICurrentDeletable).Should().BeFalse();
        (vm is ISearchable).Should().BeFalse();

        // Lifecycle capabilities — must be true per spec rule 2
        (vm is IConstructable).Should().BeTrue();
        (vm is IDestructable).Should().BeTrue();
        (vm is IReconstructable).Should().BeTrue();
    }

    // ── CAP-021 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-021: IFilterable&lt;TItem&gt; contract surface and opt-in behavior.</summary>
    [Fact, Trait("Conformance", "CAP-021")]
    public void CAP_021_IFilterable_Contract_Surface()
    {
        var sut = new FilterableFixture<int>();
        sut.Filter.Should().BeNull();
        sut.CanFilter().Should().BeTrue();

        Predicate<int> p = x => x > 0;
        sut.Filter = p;
        sut.Filter.Should().BeSameAs(p);

        sut.Filter = null;
        sut.Filter.Should().BeNull();
    }

    private sealed class FilterableFixture<TItem> : IFilterable<TItem>
    {
        public Predicate<TItem>? Filter { get; set; }
        public bool CanFilter() => true;
    }

    // ── CAP-022 ─────────────────────────────────────────────────────────────

    /// <summary>CAP-022: IPageable capability contract surface and clamping/navigation behavior.</summary>
    [Fact, Trait("Conformance", "CAP-022")]
    public void CAP_022_IPageable_Contract_Surface()
    {
        // ── 1. Initial state ────────────────────────────────────────────────
        var sut = new PageableFixture(itemCount: 25);
        sut.PageSize.Should().Be(10);
        sut.CurrentPageIndex.Should().Be(0);
        sut.IsPagingEnabled.Should().BeTrue();
        sut.PageCount.Should().Be(3);  // ceil(25/10)

        // ── 2. PageSize = 0 ─────────────────────────────────────────────────
        sut.PageSize = 0;
        sut.IsPagingEnabled.Should().BeFalse();
        sut.PageCount.Should().Be(1);  // disabled → everything is one page

        // Navigation while paging disabled — no-ops, index stays 0
        sut.MoveToFirstPage();
        sut.MoveToLastPage();
        sut.CurrentPageIndex.Should().Be(0);

        // ── 3. Clamping CurrentPageIndex ────────────────────────────────────
        sut.PageSize = 10;  // re-enable; PageCount = 3 again
        sut.CurrentPageIndex = 99;
        sut.CurrentPageIndex.Should().Be(2);  // clamped to PageCount - 1

        sut.CurrentPageIndex = -1;
        sut.CurrentPageIndex.Should().Be(0);  // clamped to 0

        // ── 4. Navigation ───────────────────────────────────────────────────
        sut.CurrentPageIndex = 1;
        sut.MoveToFirstPage();
        sut.CurrentPageIndex.Should().Be(0);

        sut.MoveToLastPage();
        sut.CurrentPageIndex.Should().Be(2);

        // MoveToNextPage at upper bound is a no-op
        sut.MoveToNextPage();
        sut.CurrentPageIndex.Should().Be(2);

        // MoveToPreviousPage
        sut.MoveToPreviousPage();
        sut.CurrentPageIndex.Should().Be(1);

        // MoveToPreviousPage at lower bound is a no-op
        sut.MoveToFirstPage();
        sut.MoveToPreviousPage();
        sut.CurrentPageIndex.Should().Be(0);

        // MoveToNextPage advances
        sut.MoveToNextPage();
        sut.CurrentPageIndex.Should().Be(1);

        // ── 5. PageSize resize clamps CurrentPageIndex ──────────────────────
        sut.CurrentPageIndex = 2;  // move to page 3 of 3
        sut.PageSize = 20;         // now PageCount = ceil(25/20) = 2 → pages 0..1
        sut.CurrentPageIndex.Should().Be(1);  // clamped from 2 to 1

        // ── 6. PageCount derivation: itemCount=0 with PageSize>0 yields PageCount=0 ─
        var empty = new PageableFixture(itemCount: 0);
        empty.PageSize = 5;
        empty.PageCount.Should().Be(0);  // ceil(0/5) = 0 (empty source has no pages)
    }

    /// <summary>
    /// Minimal opt-in implementer of IPageable used only by CAP-022.
    /// Demonstrates correct clamping, navigation, and PageCount derivation.
    /// </summary>
    private sealed class PageableFixture : IPageable
    {
        private int _itemCount;
        private int _pageSize;
        private int _currentPageIndex;

        public PageableFixture(int itemCount)
        {
            _itemCount = itemCount;
            _pageSize = 10;
            _currentPageIndex = 0;
        }

        public int PageSize
        {
            get => _pageSize;
            set
            {
                _pageSize = value < 0 ? 0 : value;
                // Clamp CurrentPageIndex after page size change
                _currentPageIndex = ClampIndex(_currentPageIndex);
            }
        }

        public int CurrentPageIndex
        {
            get => _currentPageIndex;
            set => _currentPageIndex = ClampIndex(value);
        }

        public int PageCount => _pageSize > 0
            ? (int)Math.Ceiling((double)_itemCount / _pageSize)
            : 1;

        public bool IsPagingEnabled => _pageSize > 0;

        public void MoveToFirstPage() => _currentPageIndex = 0;

        public void MoveToPreviousPage()
        {
            if (_currentPageIndex > 0) _currentPageIndex--;
        }

        public void MoveToNextPage()
        {
            if (_currentPageIndex < PageCount - 1) _currentPageIndex++;
        }

        public void MoveToLastPage() => _currentPageIndex = PageCount - 1;

        private int ClampIndex(int index)
        {
            if (PageCount == 0) return 0;  // empty source: index stays at 0
            var max = PageCount - 1;
            if (index < 0) return 0;
            if (index > max) return max;
            return index;
        }
    }
}
