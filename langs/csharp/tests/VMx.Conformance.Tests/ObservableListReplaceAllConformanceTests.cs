using System.ComponentModel;
using FluentAssertions;
using VMx.Collections;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>Conformance tests for ObservableList.ReplaceAll (COL-040..047).</summary>
public class ObservableListReplaceAllConformanceTests
{
    private static (ObservableList<int> List, List<string> Events) Observed(params int[] items)
    {
        var list = new ObservableList<int>();
        foreach (int item in items) list.Add(item);
        var events = new List<string>();
        list.ItemAdded += (_, _) => events.Add("add");
        list.ItemRemoved += (_, _) => events.Add("remove");
        list.ItemReplaced += (_, _) => events.Add("replace");
        list.Reset += (_, _) => events.Add("reset");
        ((INotifyPropertyChanged)list).PropertyChanged += (_, e) => events.Add($"property:{e.PropertyName}");
        return (list, events);
    }

    [Fact, Trait("Conformance", "COL-040")]
    public void COL_040_GrowthEmitsOneResetAndCount()
    {
        var (sut, events) = Observed(1);
        sut.ReplaceAll([2, 3, 4]);
        sut.Should().Equal(2, 3, 4);
        events.Should().Equal("reset", "property:Count");
    }

    [Fact, Trait("Conformance", "COL-041")]
    public void COL_041_ShrinkEmitsOneResetAndCount()
    {
        var (sut, events) = Observed(1, 2, 3);
        sut.ReplaceAll([9]);
        sut.Should().Equal(9);
        events.Should().Equal("reset", "property:Count");
    }

    [Fact, Trait("Conformance", "COL-042")]
    public void COL_042_EqualCountAndIdenticalContentsEmitResetWithoutEqualityConstraint()
    {
        var (sut, events) = Observed(1, 2);
        sut.ReplaceAll([3, 4]);
        sut.ReplaceAll([3, 4]);
        events.Should().Equal("reset", "reset");

        var bomb = new EqualityBomb();
        var unconstrained = new ObservableList<EqualityBomb>();
        unconstrained.Add(bomb);
        unconstrained.ReplaceAll([bomb]);
    }

    [Fact, Trait("Conformance", "COL-043")]
    public void COL_043_EmptyCasesDistinguishNoOpFromEffectiveReplacement()
    {
        var (empty, emptyEvents) = Observed();
        empty.ReplaceAll([]);
        emptyEvents.Should().BeEmpty();

        var (sut, events) = Observed(1);
        sut.ReplaceAll([]);
        events.Should().Equal("reset", "property:Count");
    }

    [Fact, Trait("Conformance", "COL-044")]
    public void COL_044_InputIsSnapshottedBeforeMutation()
    {
        var (sut, events) = Observed(1, 2, 3);
        sut.ReplaceAll(sut);
        sut.Should().Equal(1, 2, 3);
        events.Should().Equal("reset");
    }

    [Fact, Trait("Conformance", "COL-045")]
    public void COL_045_NestedReplacementEmitsOnlyOutermostReset()
    {
        var (sut, events) = Observed(1);
        using (sut.BatchUpdate())
        {
            sut.ReplaceAll([2, 3]);
            events.Should().BeEmpty();
        }
        events.Should().Equal("reset", "property:Count");
    }

    [Fact, Trait("Conformance", "COL-046")]
    public void COL_046_ExceptionalBatchExitRestoresScopeAndPublishesMutation()
    {
        var (sut, events) = Observed(1);
        Action action = () =>
        {
            using (sut.BatchUpdate())
            {
                sut.ReplaceAll([2, 3]);
                throw new InvalidOperationException("boom");
            }
        };
        action.Should().Throw<InvalidOperationException>();
        events.Should().Equal("reset", "property:Count");

        sut.ReplaceAll([4, 5]);
        events.Should().Equal("reset", "property:Count", "reset");
    }

    [Fact, Trait("Conformance", "COL-047")]
    public void COL_047_ResetPrecedesCountAndBothObserveFinalState()
    {
        var sut = new ObservableList<int>();
        sut.Add(1);
        var observations = new List<string>();
        sut.Reset += (_, _) => observations.Add($"reset:{string.Join(',', sut)}");
        ((INotifyPropertyChanged)sut).PropertyChanged += (_, e) =>
            observations.Add($"{e.PropertyName}:{string.Join(',', sut)}");

        sut.ReplaceAll([7, 8]);

        observations.Should().Equal("reset:7,8", "Count:7,8");
    }

    [Fact]
    public void ReplaceAll_InputEnumerationFailure_IsAtomic()
    {
        var (sut, events) = Observed(1, 2);

        Action action = () => sut.ReplaceAll(FailingInput());

        action.Should().Throw<InvalidOperationException>().WithMessage("iteration failed");
        sut.Should().Equal(1, 2);
        events.Should().BeEmpty();

        static IEnumerable<int> FailingInput()
        {
            yield return 9;
            throw new InvalidOperationException("iteration failed");
        }
    }

    private sealed class EqualityBomb
    {
        public override bool Equals(object? obj) => throw new InvalidOperationException("equality invoked");

        public override int GetHashCode() => 0;
    }
}
