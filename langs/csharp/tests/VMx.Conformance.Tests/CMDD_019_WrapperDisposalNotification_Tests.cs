using System.Windows.Input;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// CMDD-019: disposing a live wrapper command raises its own
/// <c>CanExecuteChanged</c> exactly once (spec/04 §8.4, ADR-0222, #1459). A
/// second <c>Dispose()</c> raises nothing, and the inner command's handlers
/// receive nothing.
/// </summary>
public class CMDD_019_WrapperDisposalNotification_Tests
{
    public static TheoryData<string> Kinds() => new() { "composite", "decorator", "confirmation" };

    [Theory, Trait("Conformance", "CMDD-019")]
    [MemberData(nameof(Kinds))]
    public void CMDD_019_Wrapper_Disposal_Notifies_Wrapper_Handlers_Once(string kind)
    {
        var inner = RelayCommand.Builder().Task(() => { }).Build();
        var innerSeen = 0;
        inner.CanExecuteChanged += (_, _) => innerSeen++;
        ICommand wrapper = kind switch
        {
            "composite" => new CompositeCommand(inner),
            "decorator" => new DecoratorCommand(inner),
            _ => new ConfirmationDecoratorCommand(inner, () => Task.FromResult(true)),
        };
        var wrapperSeen = 0;
        object? sender = null;
        var canExecuteInside = true;
        wrapper.CanExecuteChanged += (s, _) =>
        {
            wrapperSeen++;
            sender = s;
            canExecuteInside = wrapper.CanExecute(null);
        };

        ((IDisposable)wrapper).Dispose();
        ((IDisposable)wrapper).Dispose();

        wrapperSeen.Should().Be(1);
        sender.Should().BeSameAs(wrapper);
        canExecuteInside.Should().BeFalse("the wrapper is inert when it notifies");
        innerSeen.Should().Be(0);
    }
}
