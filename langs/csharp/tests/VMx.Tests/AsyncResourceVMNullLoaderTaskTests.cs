using FluentAssertions;
using VMx.Services;
using VMx.State;
using Xunit;

namespace VMx.Tests;

/// <summary>
/// A loader that returns a null task fails the load like a throwing loader:
/// the state becomes <c>Error</c> and the intent completes (spec/23 §7, ARES-003).
/// </summary>
public sealed class AsyncResourceVMNullLoaderTaskTests
{
    [Fact]
    public async Task A_null_loader_task_installs_Error_and_completes_the_load()
    {
        using var hub = new MessageHub();
        var vm = new AsyncResourceVM<string>("r", _ => null!, hub, NullDispatcher.Instance);
        vm.Construct();

        await vm.LoadAsync();

        vm.State.Status.Should().Be(AsyncResourceStatus.Error);
        vm.State.Error.Should().BeOfType<InvalidOperationException>();
        vm.Dispose();
    }
}
