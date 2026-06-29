using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Commands;
using VMx.Conformance.Tests.Fixtures;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// CMD-001 through CMD-007 — see spec/12-conformance.md §Commands.
/// </summary>
public class CommandConformanceTests
{
    // CMD-001 — Execute invokes the configured task.
    [Fact, Trait("Conformance", "CMD-001")]
    public void CMD_001_Execute_Invokes_Task()
    {
        var invoked = false;
        var cmd = RelayCommand.Builder()
            .Task(() => invoked = true)
            .Build();

        cmd.Execute(null);

        invoked.Should().BeTrue("Execute must invoke the configured task exactly once");
    }

    // CMD-002 — CanExecute with no predicate returns true.
    [Fact, Trait("Conformance", "CMD-002")]
    public void CMD_002_CanExecute_Without_Predicate_Returns_True()
    {
        var cmd = RelayCommand.Builder().Build();
        cmd.CanExecute(null).Should().BeTrue("null predicate → CanExecute always true");
    }

    // CMD-003 — CanExecute returns the predicate result.
    [Fact, Trait("Conformance", "CMD-003")]
    public void CMD_003_CanExecute_Returns_Predicate_Result()
    {
        var cmd = RelayCommand.Builder()
            .Predicate(() => false)
            .Build();

        cmd.CanExecute(null).Should().BeFalse("predicate returns false → CanExecute is false");
    }

    // CMD-004 — Trigger emission fires CanExecuteChanged.
    [Fact, Trait("Conformance", "CMD-004")]
    public void CMD_004_Trigger_Emission_Fires_CanExecuteChanged()
    {
        var trigger = new Subject<System.Reactive.Unit>();
        var cmd = RelayCommand.Builder().Triggers(trigger).Build();

        var fired = 0;
        cmd.CanExecuteChanged += (_, _) => fired++;

        trigger.OnNext(System.Reactive.Unit.Default);

        fired.Should().Be(1, "one trigger emission → exactly one CanExecuteChanged event");

        ((IDisposable)cmd).Dispose();
        trigger.Dispose();
    }

    // CMD-005 — Parameterized variant passes parameter through.
    [Fact, Trait("Conformance", "CMD-005")]
    public void CMD_005_Parameterized_Variant_Passes_Parameter()
    {
        int? received = null;
        var cmd = RelayCommand<int>.Builder()
            .Task(p => received = p)
            .Build();

        cmd.Execute(42);

        received.Should().Be(42, "RelayCommand<int>.Execute(42) must pass 42 to the task");
    }

    // CMD-006 — Execute with null task is a no-op.
    [Fact, Trait("Conformance", "CMD-006")]
    public void CMD_006_Execute_Without_Task_Is_NoOp()
    {
        var cmd = RelayCommand.Builder().Build();

        // Must not throw, must produce no observable side effect.
        var act = () => cmd.Execute(null);
        act.Should().NotThrow("Execute without a configured task must be a no-op");
    }

    // CMD-007 — Command truth-table matches fixture.
    [Fact, Trait("Conformance", "CMD-007")]
    public void CMD_007_Command_Truth_Table()
    {
        var root = FixtureLoader.Load<CommandTruthTable>("command-truthtable.json");
        foreach (var c in root.Cases)
        {
            var taskInvoked = false;
            var changedCount = 0;
            var trigger = new Subject<System.Reactive.Unit>();

            var b = RelayCommand.Builder().Triggers(trigger);
            if (c.Predicate is not null)
                b = b.Predicate(() => c.Predicate.Value);
            if (c.Task == "noop")
                b = b.Task(() => taskInvoked = true);

            var cmd = b.Build();
            cmd.CanExecuteChanged += (_, _) => changedCount++;

            cmd.CanExecute(null).Should().Be(c.CanExecute, $"case {c.Id}: CanExecute");

            if (c.TriggerEmits)
                trigger.OnNext(System.Reactive.Unit.Default);

            cmd.Execute(null);
            taskInvoked.Should().Be(c.ExecuteInvokesTask, $"case {c.Id}: ExecuteInvokesTask");
            (changedCount > 0).Should().Be(c.CanExecuteChangedFires, $"case {c.Id}: CanExecuteChangedFires");

            ((IDisposable)cmd).Dispose();
            trigger.Dispose();
        }
    }

    // CMD-012 — cancel() cancels an in-flight async command task; the command returns
    // to a non-executing state; no exception surfaces by default (spec §11, ADR-0056).
    [Fact, Trait("Conformance", "CMD-012")]
    public async Task CMD_012_Cancel_Cancels_InFlight_Async_Task_NonThrowing()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var observedCancel = false;

        using var cmd = AsyncRelayCommand.Builder()
            .Task(async ct =>
            {
                started.SetResult();
                try
                {
                    await Task.Delay(Timeout.Infinite, ct);
                }
                catch (OperationCanceledException)
                {
                    observedCancel = true;
                    throw; // propagate up to ExecuteAsync, which swallows it by default
                }
            })
            .Build();

        cmd.CanExecute(null).Should().BeTrue("the command is executable before it starts");

        var run = cmd.ExecuteAsync();
        await started.Task; // the task is now in flight

        cmd.IsExecuting.Should().BeTrue("the command is executing while the task runs");
        cmd.CanExecute(null).Should().BeFalse("an in-flight async command must not be re-executable");

        cmd.Cancel();
        await run; // MUST complete without throwing (non-throwing default, DIA-007 alignment)

        observedCancel.Should().BeTrue("the task observed cancellation through its CancellationToken");
        cmd.IsExecuting.Should().BeFalse("the command returns to a non-executing state after cancel");
        cmd.CanExecute(null).Should().BeTrue("CanExecute reflects the cleared in-flight state");
    }

    // CMD-012 (opt-in throwing variant) — ThrowOnCancel() surfaces the cancellation to
    // the awaiter instead of completing normally (spec §11 opt-in clause, ADR-0056).
    [Fact, Trait("Conformance", "CMD-012")]
    public async Task CMD_012_ThrowOnCancel_Surfaces_OperationCanceledException()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);

        using var cmd = AsyncRelayCommand.Builder()
            .ThrowOnCancel()
            .Task(async ct =>
            {
                started.SetResult();
                await Task.Delay(Timeout.Infinite, ct);
            })
            .Build();

        var run = cmd.ExecuteAsync();
        await started.Task;
        cmd.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () => await run);
        cmd.IsExecuting.Should().BeFalse("the command still returns to a non-executing state when throwing");
    }

    // -----------------------------------------------------------------------
    // Fixture DTOs
    // -----------------------------------------------------------------------

    private sealed class CommandTruthTable
    {
        public List<Case> Cases { get; init; } = new();
    }

    private sealed class Case
    {
        public string Id { get; init; } = "";
        public bool? Predicate { get; init; }
        public string? Task { get; init; }
        public bool TriggerEmits { get; init; }
        public bool CanExecute { get; init; }
        public bool ExecuteInvokesTask { get; init; }
        public bool CanExecuteChangedFires { get; init; }
    }
}
