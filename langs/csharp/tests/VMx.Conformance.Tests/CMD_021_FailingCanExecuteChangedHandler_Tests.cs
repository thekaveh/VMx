using System.Reactive;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Windows.Input;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// CMD-021: a failing <c>CanExecuteChanged</c> handler stops neither the
/// other handlers nor a trigger. C# discards a trigger-fed failure and
/// rethrows a raise-call failure after every handler has run (spec/04 §4,
/// spec/03 §3.6, ADR-0191).
/// </summary>
public class CMD_021_FailingCanExecuteChangedHandler_Tests
{
    private sealed class HandlerFailure() : Exception("handler failed");

    public static TheoryData<string> Commands() => new() { "relay", "relay<T>", "async" };

    private static (ICommand Command, Action Raise) Build(string kind, IObservable<Unit> trigger) => kind switch
    {
        "relay" => Wrap(RelayCommand.Builder().Triggers(trigger).Build()),
        "relay<T>" => Wrap(RelayCommand<int>.Builder().Triggers(trigger).Build()),
        _ => Wrap(AsyncRelayCommand.Builder().Triggers(trigger).Build()),
    };

    private static (ICommand, Action) Wrap(RelayCommand command) => (command, command.RaiseCanExecuteChanged);

    private static (ICommand, Action) Wrap(RelayCommand<int> command) => (command, command.RaiseCanExecuteChanged);

    private static (ICommand, Action) Wrap(AsyncRelayCommand command) => (command, command.RaiseCanExecuteChanged);

    [Theory, Trait("Conformance", "CMD-021")]
    [MemberData(nameof(Commands))]
    public void CMD_021_Failing_Handler_Stops_Neither_Handlers_Nor_Trigger(string kind)
    {
        using var source = new Subject<int>();
        var (command, raise) = Build(kind, source.Select(_ => Unit.Default));
        var a = 0;
        var b = 0;
        var failing = true;
        command.CanExecuteChanged += (_, _) =>
        {
            a++;
            if (failing) throw new HandlerFailure();
        };
        command.CanExecuteChanged += (_, _) => b++;

        source.Invoking(s => s.OnNext(1)).Should().NotThrow();
        source.Invoking(s => s.OnNext(2)).Should().NotThrow();
        a.Should().Be(2);
        b.Should().Be(2);

        raise.Should().Throw<HandlerFailure>();
        a.Should().Be(3);
        b.Should().Be(3);

        failing = false;
        ((IDisposable)command).Dispose();
    }
}
