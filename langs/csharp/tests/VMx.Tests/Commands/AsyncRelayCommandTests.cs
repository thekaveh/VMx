using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Reflection;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Tests.Commands;

public class AsyncRelayCommandTests
{
    [Fact]
    public void Dispose_Disposes_Error_Channel_When_Completion_Observer_Throws()
    {
        var command = AsyncRelayCommand.Builder().Build();
        using var subscription = command.Errors.Subscribe(
            _ => { },
            () => throw new InvalidOperationException("terminal observer"));

        Action dispose = command.Dispose;

        dispose.Should().Throw<InvalidOperationException>().WithMessage("terminal observer");
        var errors = (Subject<Exception>)typeof(AsyncRelayCommand)
            .GetField("_errors", BindingFlags.Instance | BindingFlags.NonPublic)!
            .GetValue(command)!;
        errors.IsDisposed.Should().BeTrue();
        dispose.Should().NotThrow("all terminal cleanup completed before rethrowing");
    }
}
