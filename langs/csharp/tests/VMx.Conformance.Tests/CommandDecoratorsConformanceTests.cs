using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for command decorators, CMDD-001..009.
/// See spec/04-commands.md §Decorators and ADR-0012.
/// </summary>
public class CommandDecoratorsConformanceTests
{
    private static RelayCommand BuildRecording(List<string> log, string label, bool predicate)
    {
        return RelayCommand.Builder()
            .Task(() => log.Add(label))
            .Predicate(() => predicate)
            .Build();
    }

    // ── CMDD-001 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-001: CompositeCommand.CanExecute is OR over inner commands.</summary>
    [Fact, Trait("Conformance", "CMDD-001")]
    public void CMDD_001_Composite_CanExecute_Is_OR()
    {
        var log = new List<string>();
        var c1 = BuildRecording(log, "c1", false);
        var c2 = BuildRecording(log, "c2", true);
        using var composite = new CompositeCommand(c1, c2);
        composite.CanExecute(null).Should().BeTrue();

        var c3 = BuildRecording(log, "c3", false);
        var c4 = BuildRecording(log, "c4", false);
        using var compositeFalse = new CompositeCommand(c3, c4);
        compositeFalse.CanExecute(null).Should().BeFalse();
    }

    // ── CMDD-002 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-002: CompositeCommand.Execute invokes only enabled inner commands.</summary>
    [Fact, Trait("Conformance", "CMDD-002")]
    public void CMDD_002_Composite_Execute_Invokes_Only_Enabled()
    {
        var log = new List<string>();
        var c1 = BuildRecording(log, "c1", true);
        var c2 = BuildRecording(log, "c2", false);
        var c3 = BuildRecording(log, "c3", true);
        using var composite = new CompositeCommand(c1, c2, c3);
        composite.Execute(null);
        log.Should().Equal("c1", "c3");
    }

    // ── CMDD-003 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-003: CompositeCommand propagates inner CanExecuteChanged.</summary>
    [Fact, Trait("Conformance", "CMDD-003")]
    public void CMDD_003_Composite_Propagates_CanExecuteChanged()
    {
        using var trigger = new Subject<System.Reactive.Unit>();
        var c1 = RelayCommand.Builder().Task(() => { }).Triggers(trigger).Build();
        using var composite = new CompositeCommand(c1);
        var fired = 0;
        composite.CanExecuteChanged += (_, _) => fired++;
        trigger.OnNext(System.Reactive.Unit.Default);
        fired.Should().Be(1);
    }

    // ── CMDD-004 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-004: DecoratorCommand.CanExecute is inner AND extra-predicate.</summary>
    [Fact, Trait("Conformance", "CMDD-004")]
    public void CMDD_004_Decorator_CanExecute_Combines()
    {
        var log = new List<string>();
        var inner = BuildRecording(log, "inner", true);
        using var extraFalse = new DecoratorCommand(inner, extraPredicate: () => false);
        using var extraTrue = new DecoratorCommand(inner, extraPredicate: () => true);
        var innerFalse = BuildRecording(log, "innerF", false);
        using var extraTrueInnerFalse = new DecoratorCommand(innerFalse, extraPredicate: () => true);
        extraFalse.CanExecute(null).Should().BeFalse();
        extraTrue.CanExecute(null).Should().BeTrue();
        extraTrueInnerFalse.CanExecute(null).Should().BeFalse();
    }

    // ── CMDD-005 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-005: DecoratorCommand.Execute invokes pre, inner, post in order.</summary>
    [Fact, Trait("Conformance", "CMDD-005")]
    public void CMDD_005_Decorator_Execute_Order()
    {
        var log = new List<string>();
        var inner = BuildRecording(log, "inner", true);
        using var dec = new DecoratorCommand(
            inner,
            preExecute: () => log.Add("pre"),
            postExecute: () => log.Add("post"));
        dec.Execute(null);
        log.Should().Equal("pre", "inner", "post");
    }

    // ── CMDD-006 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-006: DecoratorCommand.Execute is no-op when CanExecute is false.</summary>
    [Fact, Trait("Conformance", "CMDD-006")]
    public void CMDD_006_Decorator_Execute_NoOp_When_False()
    {
        var log = new List<string>();
        var inner = BuildRecording(log, "inner", true);
        using var dec = new DecoratorCommand(
            inner,
            preExecute: () => log.Add("pre"),
            postExecute: () => log.Add("post"),
            extraPredicate: () => false);
        dec.Execute(null);
        log.Should().BeEmpty();
    }

    // ── CMDD-007 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-007: ConfirmationDecoratorCommand invokes inner only when confirmed.</summary>
    [Fact, Trait("Conformance", "CMDD-007")]
    public async Task CMDD_007_Confirmation_Invokes_Inner_Only_When_Confirmed()
    {
        var log = new List<string>();
        var inner = BuildRecording(log, "inner", true);
        using var confirmed = new ConfirmationDecoratorCommand(inner, () => Task.FromResult(true));
        await confirmed.ExecuteAsync(null);
        log.Should().Equal("inner");

        log.Clear();
        using var declined = new ConfirmationDecoratorCommand(inner, () => Task.FromResult(false));
        await declined.ExecuteAsync(null);
        log.Should().BeEmpty();
    }

    // ── CMDD-008 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-008: ConfirmationDecoratorCommand.CanExecute delegates to inner.</summary>
    [Fact, Trait("Conformance", "CMDD-008")]
    public void CMDD_008_Confirmation_CanExecute_Delegates()
    {
        var log = new List<string>();
        var innerT = BuildRecording(log, "x", true);
        var innerF = BuildRecording(log, "x", false);
        using var confT = new ConfirmationDecoratorCommand(innerT, () => Task.FromResult(true));
        using var confF = new ConfirmationDecoratorCommand(innerF, () => Task.FromResult(true));
        confT.CanExecute(null).Should().BeTrue();
        confF.CanExecute(null).Should().BeFalse();
    }

    // ── CMDD-009 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-009: decorators compose (decorator of confirmation of relay).</summary>
    [Fact, Trait("Conformance", "CMDD-009")]
    public async Task CMDD_009_Decorators_Compose()
    {
        var log = new List<string>();
        var relay = BuildRecording(log, "relay", true);
        using var conf = new ConfirmationDecoratorCommand(relay, () => Task.FromResult(true));
        using var dec = new DecoratorCommand(conf);

        dec.CanExecute(null).Should().BeTrue();
        await conf.ExecuteAsync(null);
        log.Should().Equal("relay");
    }

    // ── CMDD-010 ────────────────────────────────────────────────────────────

    /// <summary>CMDD-010: ConfirmationDecoratorCommand surfaces a rejecting confirm
    /// delegate (and a throwing inner command) on the Errors channel from the
    /// fire-and-forget Execute path instead of swallowing it.</summary>
    [Fact, Trait("Conformance", "CMDD-010")]
    public async Task CMDD_010_Confirmation_Surfaces_Errors_On_Errors_Channel()
    {
        // (a) the confirm delegate rejects
        var confirmBoom = new InvalidOperationException("confirm rejected");
        var inner = RelayCommand.Builder().Task(() => { }).Build();
        using var rejecting = new ConfirmationDecoratorCommand(
            inner, () => Task.FromException<bool>(confirmBoom));
        var observedReject = new TaskCompletionSource<Exception>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var sub1 = rejecting.Errors.Subscribe(e => observedReject.TrySetResult(e));

        rejecting.Execute(null); // fire-and-forget across the async confirm gate

        var done1 = await Task.WhenAny(observedReject.Task, Task.Delay(TimeSpan.FromSeconds(5)));
        done1.Should().BeSameAs(observedReject.Task, "a rejecting confirm must surface on Errors, not be swallowed");
        (await observedReject.Task).Should().BeSameAs(confirmBoom);

        // (b) the inner command throws once confirmed
        var innerBoom = new InvalidOperationException("inner boom");
        var throwing = RelayCommand.Builder().Task(() => throw innerBoom).Build();
        using var confirming = new ConfirmationDecoratorCommand(
            throwing, () => Task.FromResult(true));
        var observedInner = new TaskCompletionSource<Exception>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var sub2 = confirming.Errors.Subscribe(e => observedInner.TrySetResult(e));

        confirming.Execute(null);

        var done2 = await Task.WhenAny(observedInner.Task, Task.Delay(TimeSpan.FromSeconds(5)));
        done2.Should().BeSameAs(observedInner.Task, "a throwing inner command must surface on Errors");
        (await observedInner.Task).Should().BeSameAs(innerBoom);
    }
}
