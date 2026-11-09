using FluentAssertions;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: FORM-045 — an update runs its dirty comparisons only in
/// strict mode. A strict <c>SetModel</c> runs three equality comparisons and a
/// strict deny two. A non-strict <c>SetModel</c> runs one and a non-strict deny
/// none. A non-strict update commits even when the comparison of the
/// candidate with <c>Snapshot</c> would fail. See spec/20-form-vm.md §5.2 and
/// ADR-0216.
/// </summary>
public sealed class FORM_045_StrictOnlyDirtyComparisons_Tests
{
    private sealed class Counter
    {
        public int Calls;
    }

    // Counts each equality call. A snapshot copy is marked, and its equality
    // fails when FailOnSnapshot is set.
    private sealed record Counted(string Value, Counter Counter, bool IsSnapshot = false, bool FailOnSnapshot = false)
    {
        public static readonly Exception Failure = new InvalidOperationException("snapshot comparison");

        public bool Equals(Counted? other)
        {
            Counter.Calls++;
            if (FailOnSnapshot && (IsSnapshot || other?.IsSnapshot == true)) throw Failure;
            return other is not null && Value == other.Value;
        }

        public override int GetHashCode() => StringComparer.Ordinal.GetHashCode(Value);
    }

    // Snapshot copies are distinct instances, so object.Equals never
    // short-circuits on reference equality.
    private static FormVM<Counted> Form(Counter counter, bool strict, bool failOnSnapshot = false, IMessageHub? hub = null) =>
        new(
            new Counted("initial", counter, FailOnSnapshot: failOnSnapshot),
            _ => Task.CompletedTask,
            hub: hub,
            strict: strict,
            snapshotter: model => model with { IsSnapshot = true });

    [Theory, Trait("Conformance", "FORM-045")]
    [InlineData(true, 3)]
    [InlineData(false, 1)]
    public void FORM_045_SetModel_Runs_The_Dirty_Comparisons_Only_In_Strict_Mode(bool strict, int expected)
    {
        var counter = new Counter();
        using var form = Form(counter, strict);
        counter.Calls = 0;

        form.SetModel(new Counted("next", counter));

        counter.Calls.Should().Be(expected);
        form.Model.Value.Should().Be("next");
    }

    [Theory, Trait("Conformance", "FORM-045")]
    [InlineData(true, 2)]
    [InlineData(false, 0)]
    public void FORM_045_Deny_Runs_The_Dirty_Comparisons_Only_In_Strict_Mode(bool strict, int expected)
    {
        var counter = new Counter();
        using var form = Form(counter, strict);
        form.SetModel(new Counted("next", counter));
        counter.Calls = 0;

        form.DenyCommand.Execute(null);

        counter.Calls.Should().Be(expected);
        form.Model.Value.Should().Be("initial");
    }

    [Fact, Trait("Conformance", "FORM-045")]
    public void FORM_045_A_NonStrict_Update_Commits_When_The_Snapshot_Comparison_Would_Fail()
    {
        var counter = new Counter();
        using var hub = new MessageHub();
        using var form = Form(counter, strict: false, failOnSnapshot: true, hub: hub);
        var published = 0;
        using var subscription = hub.Messages.Subscribe(message =>
        {
            if (message is PropertyChangedMessage<FormVM<Counted>> { PropertyName: "Model" }) published++;
        });

        form.SetModel(new Counted("z", counter, FailOnSnapshot: true));
        form.DenyCommand.Execute(null);

        published.Should().Be(2, "both updates commit and publish");
        form.Model.Value.Should().Be("initial");
    }
}
