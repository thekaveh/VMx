using System.Reactive;
using System.Reactive.Concurrency;
using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Capabilities;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// SRCH-010: a constructor whose post-subscribe reconciliation fails releases
/// its source-change subscription before the failure reaches the caller
/// (spec/06 §8.2, ADR-0232).
/// </summary>
public class SRCH_010_FailedReconcileReleasesSourceSignal_Tests
{
    private sealed class ReconcileFailure() : Exception("reconcile failed");

    [Fact, Trait("Conformance", "SRCH-010")]
    public void SRCH_010_Failed_Reconcile_Releases_The_Source_Signal()
    {
        var reads = 0;
        var signal = new Subject<Unit>();
        Func<IEnumerable<string>> items = () =>
        {
            reads++;
            if (reads == 2) throw new ReconcileFailure();
            return ["a", "b"];
        };

        var act = () => new SearchableState<string>(
            items, (item, term) => item.Contains(term, StringComparison.Ordinal),
            TimeSpan.Zero, ImmediateScheduler.Instance, signal);

        act.Should().Throw<ReconcileFailure>();
        signal.HasObservers.Should().BeFalse();
        reads = 0;
        signal.OnNext(Unit.Default);
        reads.Should().Be(0);
    }
}
