using FluentAssertions;
using VMx.Services;
using VMx.State;
using Xunit;

namespace VMx.Tests;

/// <summary>
/// A timeout is a failure, not a cancellation: a loader that ends with an
/// <see cref="OperationCanceledException"/> whose inner exception is a
/// <see cref="TimeoutException"/> (the <c>HttpClient</c> timeout) installs
/// <c>Error</c> (ADR-0199, spec/23 §7).
/// </summary>
public sealed class AsyncResourceVMLoaderTimeoutTests
{
    [Fact]
    public async Task A_loader_timeout_installs_Error_carrying_the_exception()
    {
        using var hub = new MessageHub();
        var timeout = new TaskCanceledException("timeout", new TimeoutException());
        var vm = new AsyncResourceVM<string>(
            "r", _ => Task.FromException<string>(timeout), hub, NullDispatcher.Instance);
        vm.Construct();

        await vm.LoadAsync();

        vm.State.Status.Should().Be(AsyncResourceStatus.Error);
        vm.State.Error.Should().BeSameAs(timeout);
        vm.Dispose();
    }
}
