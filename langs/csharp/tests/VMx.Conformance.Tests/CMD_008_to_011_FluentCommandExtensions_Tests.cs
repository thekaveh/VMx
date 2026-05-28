using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for CMD-008..CMD-011 — fluent command extension methods.
/// See spec/04-commands.md §9 and ADR-0027.
/// </summary>
public class CMD_008_to_011_FluentCommandExtensions_Tests
{
    private static System.Windows.Input.ICommand BuildRecording(List<string> log, string label, bool predicate)
    {
        return RelayCommand.Builder()
            .Task(() => log.Add(label))
            .Predicate(() => predicate)
            .Build();
    }

    // ── CMD-008 ────────────────────────────────────────────────────────────

    /// <summary>CMD-008: Confirm(delegate) is equivalent to explicit ConfirmationDecoratorCommand.</summary>
    [Fact, Trait("Conformance", "CMD-008")]
    public async Task CMD_008_Confirm_Equivalent_To_Explicit_Constructor()
    {
        var log = new List<string>();
        var inner = BuildRecording(log, "inner", true);

        Func<Task<bool>> confirmYes = () => Task.FromResult(true);
        Func<Task<bool>> confirmNo = () => Task.FromResult(false);

        // fluent form
        var fluent = inner.Confirm(confirmYes);
        fluent.Should().BeOfType<ConfirmationDecoratorCommand>();
        fluent.CanExecute(null).Should().BeTrue();
        await ((ConfirmationDecoratorCommand)fluent).ExecuteAsync(null);
        log.Should().Equal("inner");

        // fluent rejected path
        log.Clear();
        var fluentNo = inner.Confirm(confirmNo);
        await ((ConfirmationDecoratorCommand)fluentNo).ExecuteAsync(null);
        log.Should().BeEmpty();

        // equivalent to explicit constructor
        using var explicit_ = new ConfirmationDecoratorCommand(inner, confirmYes);
        fluent.CanExecute(null).Should().Be(explicit_.CanExecute(null));
    }

    // ── CMD-009 ────────────────────────────────────────────────────────────

    /// <summary>CMD-009: PrecedeWith(other) is equivalent to CompositeCommand(other, receiver).</summary>
    [Fact, Trait("Conformance", "CMD-009")]
    public void CMD_009_PrecedeWith_Equivalent_To_Explicit_Constructor()
    {
        var log = new List<string>();
        var receiver = BuildRecording(log, "receiver", true);
        var other = BuildRecording(log, "other", true);

        var fluent = receiver.PrecedeWith(other);
        fluent.Should().BeOfType<CompositeCommand>();

        fluent.Execute(null);
        // other executes first, then receiver
        log.Should().Equal("other", "receiver");
    }

    // ── CMD-010 ────────────────────────────────────────────────────────────

    /// <summary>CMD-010: SucceedWith(other) is equivalent to CompositeCommand(receiver, other).</summary>
    [Fact, Trait("Conformance", "CMD-010")]
    public void CMD_010_SucceedWith_Equivalent_To_Explicit_Constructor()
    {
        var log = new List<string>();
        var receiver = BuildRecording(log, "receiver", true);
        var other = BuildRecording(log, "other", true);

        var fluent = receiver.SucceedWith(other);
        fluent.Should().BeOfType<CompositeCommand>();

        fluent.Execute(null);
        // receiver executes first, then other
        log.Should().Equal("receiver", "other");
    }

    // ── CMD-011 ────────────────────────────────────────────────────────────

    /// <summary>CMD-011: WrapWith(predicate?, pre?, post?) is equivalent to explicit DecoratorCommand.</summary>
    [Fact, Trait("Conformance", "CMD-011")]
    public void CMD_011_WrapWith_Equivalent_To_Explicit_Constructor()
    {
        var log = new List<string>();
        var inner = BuildRecording(log, "inner", true);

        // all-null → transparent decorator
        var allNull = inner.WrapWith();
        allNull.Should().BeOfType<DecoratorCommand>();
        allNull.CanExecute(null).Should().BeTrue();
        allNull.Execute(null);
        log.Should().Equal("inner");

        // with pre/post/predicate
        log.Clear();
        var decorated = inner.WrapWith(
            predicate: () => true,
            pre: () => log.Add("pre"),
            post: () => log.Add("post"));
        decorated.Should().BeOfType<DecoratorCommand>();
        decorated.Execute(null);
        log.Should().Equal("pre", "inner", "post");

        // predicate returning false blocks execution
        log.Clear();
        var blocked = inner.WrapWith(predicate: () => false);
        blocked.CanExecute(null).Should().BeFalse();
        blocked.Execute(null);
        log.Should().BeEmpty();
    }
}
