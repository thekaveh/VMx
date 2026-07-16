using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Reflection;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Tests.Commands;

public class ConfirmationDecoratorCommandTests
{
    [Fact]
    public void Dispose_Disposes_Error_Channel_When_Completion_Observer_Throws()
    {
        var inner = RelayCommand.Builder().Build();
        var command = new ConfirmationDecoratorCommand(
            inner,
            () => Task.FromResult(true));
        using var subscription = command.Errors.Subscribe(
            _ => { },
            () => throw new InvalidOperationException("terminal observer"));

        Action dispose = command.Dispose;

        dispose.Should().Throw<InvalidOperationException>().WithMessage("terminal observer");
        var errors = (Subject<Exception>)typeof(ConfirmationDecoratorCommand)
            .GetField("_errors", BindingFlags.Instance | BindingFlags.NonPublic)!
            .GetValue(command)!;
        errors.IsDisposed.Should().BeTrue();
        dispose.Should().NotThrow("all terminal cleanup completed before rethrowing");
    }

    [Fact]
    public async Task Dispose_Waits_For_InFlight_Error_Delivery()
    {
        using var observerEntered = new ManualResetEventSlim();
        using var releaseObserver = new ManualResetEventSlim();
        using var disposeStarted = new ManualResetEventSlim();
        var inner = RelayCommand.Builder().Task(() => { }).Build();
        var command = new ConfirmationDecoratorCommand(
            inner,
            () => Task.FromException<bool>(new InvalidOperationException("boom")));
        using var subscription = command.Errors.Subscribe(_ =>
        {
            observerEntered.Set();
            releaseObserver.Wait();
        });

        var execute = Task.Run(() => command.Execute(null));
        observerEntered.Wait(TimeSpan.FromSeconds(15)).Should().BeTrue();
        var dispose = Task.Run(() =>
        {
            disposeStarted.Set();
            command.Dispose();
        });
        disposeStarted.Wait(TimeSpan.FromSeconds(15)).Should().BeTrue();

        try
        {
            var first = await Task.WhenAny(dispose, Task.Delay(TimeSpan.FromMilliseconds(100)));
            first.Should().NotBeSameAs(dispose,
                "error-channel teardown must serialize with an admitted delivery");
        }
        finally
        {
            releaseObserver.Set();
        }

        await Task.WhenAll(execute, dispose);
    }
}
