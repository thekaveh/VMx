using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Services;
using Xunit;

namespace VMx.Conformance.Tests;

public class COMP_028_to_037_FilteredCompositeTests
{
    private sealed class EqualByNameVM(string name)
        : ComponentVMBase(
            name,
            "",
            NullMessageHub.Instance,
            NullDispatcher.Instance,
            null,
            null)
    {
        public override ViewModelType Type => ViewModelType.Component;

        public override bool Equals(object? obj) =>
            obj is EqualByNameVM other && other.Name == Name;

        public override int GetHashCode() => Name.GetHashCode(StringComparison.Ordinal);
    }

    private static ComponentVM Child(string name) =>
        ComponentVM.Builder().Name(name).WithNullServices().Build();

    private static CompositeVM<ComponentVM> Source(params string[] names)
    {
        var vm = CompositeVM<ComponentVM>.Builder()
            .Name("source")
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Children(() => [])
            .Build();
        foreach (var name in names) vm.Add(Child(name));
        return vm;
    }

    [Fact, Trait("Conformance", "COMP-028")]
    public void COMP_028_FilteredVisibleProjection()
    {
        var sut = new FilteredCompositeVM<ComponentVM>(Source("alpha", "beta"), vm => vm.Name.Contains('a'));
        sut.Visible.Select(vm => vm.Name).Should().Equal("alpha", "beta");
    }

    [Fact, Trait("Conformance", "COMP-029")]
    public void COMP_029_VisibleCount()
    {
        var sut = new FilteredCompositeVM<ComponentVM>(Source("alpha", "bee"), vm => vm.Name.Contains('a'));
        sut.VisibleCount.Should().Be(1);
    }

    [Fact, Trait("Conformance", "COMP-030")]
    public void COMP_030_CurrentMapsToVisibleDomain()
    {
        var src = Source("alpha", "bee");
        var sut = new FilteredCompositeVM<ComponentVM>(src, vm => vm.Name.Contains('a'));
        sut.Current = sut.Visible[0];
        sut.Current.Should().BeSameAs(src[0]);
    }

    [Fact, Trait("Conformance", "COMP-030")]
    public void COMP_030_CurrentRejectsEqualButForeignIdentity()
    {
        var child = new EqualByNameVM("same");
        var foreign = new EqualByNameVM("same");
        var source = CompositeVM<EqualByNameVM>.Builder()
            .Name("source")
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Children(() => [])
            .Build();
        source.Add(child);
        var sut = new FilteredCompositeVM<EqualByNameVM>(source);

        Action setForeign = () => sut.Current = foreign;

        setForeign.Should().Throw<InvalidOperationException>();
        sut.Current.Should().BeSameAs(child);
    }

    [Fact, Trait("Conformance", "COMP-031")]
    public void COMP_031_PredicateChangeRecomputesProjection()
    {
        var sut = new FilteredCompositeVM<ComponentVM>(Source("alpha", "bee"), vm => vm.Name.Contains('a'));
        sut.SetPredicate(vm => vm.Name.Contains('e'));
        sut.Visible.Select(vm => vm.Name).Should().Equal("bee");
    }

    [Fact, Trait("Conformance", "COMP-032")]
    public void COMP_032_SourceMutationReconcilesProjection()
    {
        var src = Source("alpha");
        var sut = new FilteredCompositeVM<ComponentVM>(src, vm => vm.Name.Contains('z'));
        src.Add(Child("zulu"));
        sut.Visible.Select(vm => vm.Name).Should().Equal("zulu");
    }

    [Fact, Trait("Conformance", "COMP-033")]
    public void COMP_033_CursorPolicies()
    {
        var src = Source("alpha", "bee");
        var snap = new FilteredCompositeVM<ComponentVM>(src, _ => true);
        snap.Current = src[1];
        snap.SetPredicate(vm => vm.Name == "alpha");
        snap.Current.Should().BeSameAs(src[0]);

        var clear = new FilteredCompositeVM<ComponentVM>(
            src,
            _ => true,
            FilteredCursorPolicy.Clear);
        clear.Current = src[1];
        clear.SetPredicate(vm => vm.Name == "alpha");
        clear.Current.Should().BeNull();
    }

    [Fact, Trait("Conformance", "COMP-034")]
    public void COMP_034_VisibleNavigation()
    {
        var sut = new FilteredCompositeVM<ComponentVM>(Source("alpha", "bee", "gamma"), vm => vm.Name.Contains('a'));
        sut.Current = sut.Visible[0];
        sut.MoveToNextVisible();
        sut.Current.Should().BeSameAs(sut.Visible[1]);
        sut.MoveToPreviousVisible();
        sut.Current.Should().BeSameAs(sut.Visible[0]);
    }

    [Fact, Trait("Conformance", "COMP-035")]
    public void COMP_035_DisposeStopsSourceSubscription()
    {
        var src = Source("alpha");
        var sut = new FilteredCompositeVM<ComponentVM>(src, _ => true);
        sut.Dispose();
        src.Add(Child("bee"));
        sut.Visible.Select(vm => vm.Name).Should().Equal("alpha");
    }

    [Fact, Trait("Conformance", "COMP-036")]
    public void COMP_036_ScoredFilterSortsByScoreWithStableTies()
    {
        var sut = new ScoredFilteredCompositeVM<ComponentVM>(
            Source("alpha", "bee", "ax"),
            vm => vm.Name.StartsWith('a') ? 1 : null);
        sut.Visible.Select(vm => vm.Name).Should().Equal("alpha", "ax");
    }

    [Fact, Trait("Conformance", "COMP-037")]
    public void COMP_037_ScoredFilterRecomputesOrderWhenScoresChange()
    {
        var weights = new Dictionary<string, int> { ["alpha"] = 1, ["bee"] = 2 };
        var sut = new ScoredFilteredCompositeVM<ComponentVM>(
            Source("alpha", "bee"),
            vm => weights[vm.Name]);
        sut.Visible.Select(vm => vm.Name).Should().Equal("bee", "alpha");
        weights["alpha"] = 3;
        sut.RefreshScores();
        sut.Visible.Select(vm => vm.Name).Should().Equal("alpha", "bee");
    }
}
