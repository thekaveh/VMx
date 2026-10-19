using System.ComponentModel;
using FluentAssertions;
using VMx.Lifecycle;
using VMx.Services;
using VMx.State;
using Xunit;

namespace VMx.Tests;

/// <summary>
/// A load requested while the VM is being disposed never calls the loader
/// (spec/23 §4, ARES-011).
/// </summary>
public sealed class AsyncResourceVMDisposalStartTests
{
    [Fact]
    public async Task Load_from_a_Disposed_status_observer_does_not_call_the_loader()
    {
        using var hub = new MessageHub();
        var loaderCalls = 0;
        var vm = new AsyncResourceVM<string>(
            "r", _ => { loaderCalls++; return Task.FromResult("v"); }, hub, NullDispatcher.Instance);
        vm.Construct();
        Task? late = null;
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == "Status" && vm.Status == ConstructionStatus.Disposed && late is null)
                late = vm.LoadAsync();
        };

        vm.Dispose();
        if (late is not null) await late;

        loaderCalls.Should().Be(0);
        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
    }

    [Fact]
    public async Task Dispose_from_the_Loading_publication_does_not_call_the_loader()
    {
        using var hub = new MessageHub();
        var loaderCalls = 0;
        var vm = new AsyncResourceVM<string>(
            "r", _ => { loaderCalls++; return Task.FromResult("v"); }, hub, NullDispatcher.Instance);
        vm.Construct();
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == "State" && vm.State.Status == AsyncResourceStatus.Loading)
                vm.Dispose();
        };

        await vm.LoadAsync();

        loaderCalls.Should().Be(0);
    }
}
