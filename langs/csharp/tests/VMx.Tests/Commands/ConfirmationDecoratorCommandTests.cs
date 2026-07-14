using System.Reactive.Linq;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Tests.Commands;

public class ConfirmationDecoratorCommandTests
{
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
        observerEntered.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();
        var dispose = Task.Run(() =>
        {
            disposeStarted.Set();
            command.Dispose();
        });
        disposeStarted.Wait(TimeSpan.FromSeconds(5)).Should().BeTrue();

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
