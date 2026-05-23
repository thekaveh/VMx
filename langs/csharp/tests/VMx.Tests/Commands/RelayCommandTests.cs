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
}
