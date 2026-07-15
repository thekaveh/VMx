using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Tests.Commands;

/// <summary>
/// Unit tests for <see cref="RelayCommand"/> and <see cref="RelayCommand{T}"/>.
/// Each Fact covers one independently verifiable behavioral requirement.
/// </summary>
public class RelayCommandTests
{
    // -----------------------------------------------------------------------
    // RelayCommand — non-parameterized
    // -----------------------------------------------------------------------

    [Fact]
    public void Build_Without_Task_Or_Predicate_CanExecute_True_Execute_NoOp()
    {
        var cmd = RelayCommand.Builder().Build();
        cmd.CanExecute(null).Should().BeTrue("no predicate → CanExecute returns true");

        // Execute must not throw and must produce no side-effect.
        var act = () => cmd.Execute(null);
        act.Should().NotThrow();
    }

    [Fact]
    public void Build_With_Task_Execute_Invokes_Task()
    {
        var invoked = false;
        var cmd = RelayCommand.Builder()
            .Task(() => invoked = true)
            .Build();

        cmd.Execute(null);

        invoked.Should().BeTrue("Execute must invoke the configured task");
    }

    [Fact]
    public void Build_With_Predicate_False_CanExecute_False_And_Execute_Does_Not_Invoke_Task()
    {
        var invoked = false;
        var cmd = RelayCommand.Builder()
            .Task(() => invoked = true)
            .Predicate(() => false)
            .Build();

        cmd.CanExecute(null).Should().BeFalse();
        cmd.Execute(null);
        invoked.Should().BeFalse("Execute must NOT invoke task when CanExecute returns false");
    }

    [Fact]
    public void Build_With_Predicate_True_And_Task_Execute_Invokes_Task()
    {
        var invoked = false;
        var cmd = RelayCommand.Builder()
            .Task(() => invoked = true)
            .Predicate(() => true)
            .Build();

        cmd.CanExecute(null).Should().BeTrue();
        cmd.Execute(null);
        invoked.Should().BeTrue();
    }

    [Fact]
    public void Trigger_Emission_Fires_CanExecuteChanged()
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

    [Fact]
    public void Multiple_Triggers_Calls_Are_Additive()
    {
        var t1 = new Subject<System.Reactive.Unit>();
        var t2 = new Subject<System.Reactive.Unit>();
        var cmd = RelayCommand.Builder().Triggers(t1).Triggers(t2).Build();

        var fired = 0;
        cmd.CanExecuteChanged += (_, _) => fired++;

        t1.OnNext(System.Reactive.Unit.Default);
        t2.OnNext(System.Reactive.Unit.Default);

        fired.Should().Be(2, "both triggers should fire CanExecuteChanged independently");

        ((IDisposable)cmd).Dispose();
        t1.Dispose();
        t2.Dispose();
    }

    [Fact]
    public void Dispose_Releases_Triggers_When_Terminal_Observer_Throws()
    {
        using var trigger = new Subject<System.Reactive.Unit>();
        var cmd = RelayCommand.Builder().Triggers(trigger).Build();
        cmd.CanExecuteChanged += (_, _) => throw new InvalidOperationException("terminal observer");

        Action dispose = cmd.Dispose;

        dispose.Should().Throw<InvalidOperationException>().WithMessage("terminal observer");
        trigger.HasObservers.Should().BeFalse("terminal cleanup must release trigger subscriptions");
        dispose.Should().NotThrow("the command was fully disposed before rethrowing");
    }

    [Fact]
    public void Predicate_That_Throws_CanExecute_Returns_False()
    {
        var cmd = RelayCommand.Builder()
            .Predicate(() => throw new InvalidOperationException("boom"))
            .Build();

        // Must not propagate — returns false defensively.
        var act = () => cmd.CanExecute(null);
        act.Should().NotThrow();
        cmd.CanExecute(null).Should().BeFalse("throwing predicate is treated as false");
    }

    [Fact]
    public void Builder_Setter_Returns_New_Instance_BLD001()
    {
        var b1 = RelayCommand.Builder();
        var b2 = b1.Task(() => { });

        b2.Should().NotBeSameAs(b1, "each setter must return a NEW builder instance (BLD-001)");
    }

    [Fact]
    public void Builder_Remains_Compatible_With_Legacy_Interface_And_Concrete_Result()
    {
        ICommandBuilder legacyBuilder = RelayCommand.Builder();
        System.Windows.Input.ICommand legacyCommand = legacyBuilder.Task(() => { }).Build();
        legacyCommand.Should().BeOfType<RelayCommand>();

        RelayCommandBuilder concreteBuilder = RelayCommand.Builder();
        RelayCommand concreteCommand = concreteBuilder.Task(() => { }).Build();
        concreteCommand.Should().BeOfType<RelayCommand>();
    }

    // -----------------------------------------------------------------------
    // RelayCommand<T> — parameterized
    // -----------------------------------------------------------------------

    [Fact]
    public void Parameterized_Command_Threads_Parameter_Through_To_Task()
    {
        int? received = null;
        var cmd = RelayCommand<int>.Builder()
            .Task(p => received = p)
            .Build();

        cmd.Execute(42);

        received.Should().Be(42, "RelayCommand<T> must pass the parameter to the task");
    }

    [Fact]
    public void Parameterized_Dispose_Releases_Triggers_When_Terminal_Observer_Throws()
    {
        using var trigger = new Subject<System.Reactive.Unit>();
        var cmd = RelayCommand<int>.Builder().Triggers(trigger).Build();
        cmd.CanExecuteChanged += (_, _) => throw new InvalidOperationException("terminal observer");

        Action dispose = cmd.Dispose;

        dispose.Should().Throw<InvalidOperationException>().WithMessage("terminal observer");
        trigger.HasObservers.Should().BeFalse("terminal cleanup must release trigger subscriptions");
        dispose.Should().NotThrow("the command was fully disposed before rethrowing");
    }

    [Fact]
    public void Parameterized_Command_CanExecute_Uses_Predicate_Parameter()
    {
        var cmd = RelayCommand<int>.Builder()
            .Predicate(p => p > 0)
            .Build();

        cmd.CanExecute(5).Should().BeTrue();
        cmd.CanExecute(-1).Should().BeFalse();
    }

    [Fact]
    public void Parameterized_Builder_Setter_Returns_New_Instance_BLD001()
    {
        var b1 = RelayCommand<int>.Builder();
        var b2 = b1.Task(_ => { });

        b2.Should().NotBeSameAs(b1, "each setter must return a NEW builder instance (BLD-001)");
    }

    [Fact]
    public void Parameterized_Builder_Remains_Compatible_With_Legacy_Interface_And_Concrete_Result()
    {
        ICommandBuilder<int> legacyBuilder = RelayCommand<int>.Builder();
        System.Windows.Input.ICommand legacyCommand = legacyBuilder.Task(_ => { }).Build();
        legacyCommand.Should().BeOfType<RelayCommand<int>>();

        RelayCommandBuilder<int> concreteBuilder = RelayCommand<int>.Builder();
        RelayCommand<int> concreteCommand = concreteBuilder.Task(_ => { }).Build();
        concreteCommand.Should().BeOfType<RelayCommand<int>>();
    }

    [Fact]
    public void Parameterized_Command_Null_Or_Mismatched_Parameter_Is_Inert_VMX063()
    {
        var executed = false;
        var cmd = RelayCommand<int>.Builder()
            .Task(_ => executed = true)
            .Build();

        // A value-type command can never be satisfied by null or a foreign type:
        // it must NOT coerce them to default(int) and run.
        cmd.CanExecute(null).Should().BeFalse("null is not an int (VMX-063)");
        cmd.CanExecute("nope").Should().BeFalse("a string is not an int (VMX-063)");

        cmd.Execute(null);
        cmd.Execute("nope");
        executed.Should().BeFalse("Execute must be a no-op for a non-T parameter — never run with a fabricated default(int)");
    }

    [Fact]
    public void Parameterized_Command_Predicate_Never_Sees_A_Fabricated_Default_VMX063()
    {
        string? sawParameter = null;
        var cmd = RelayCommand<string>.Builder()
            .Predicate(s => { sawParameter = s; return true; })
            .Build();

        // null / wrong type → CanExecute false WITHOUT invoking the predicate
        // (the old code handed the predicate a coerced default!).
        cmd.CanExecute(null).Should().BeFalse("null is not a string (VMX-063)");
        cmd.CanExecute(123).Should().BeFalse("an int is not a string (VMX-063)");
        sawParameter.Should().BeNull("predicate must never receive a fabricated default(T)");

        // a genuine T still flows through to the predicate.
        cmd.CanExecute("ok").Should().BeTrue();
        sawParameter.Should().Be("ok");
    }
}
