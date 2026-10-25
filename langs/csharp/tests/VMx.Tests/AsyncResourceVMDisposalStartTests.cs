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

    // #729: Cancel() from a Loading observer prevents the loader call, as in
    // Python, TypeScript, Swift and Rust.
    [Fact]
    public async Task Cancel_from_the_Loading_publication_does_not_call_the_loader()
    {
        using var hub = new MessageHub();
        var loaderCalls = 0;
        var cleaned = new List<string>();
        var vm = new AsyncResourceVM<string>(
            "r",
            _ => { loaderCalls++; return Task.FromResult("expensive-value"); },
            hub,
            NullDispatcher.Instance,
            cleanupValue: cleaned.Add);
        vm.Construct();
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == "State" && vm.State.Status == AsyncResourceStatus.Loading)
                vm.Cancel();
        };

        await vm.LoadAsync();

        loaderCalls.Should().Be(0);
        vm.State.Status.Should().Be(AsyncResourceStatus.Idle);
        cleaned.Should().BeEmpty();
    }

    [Fact]
    public async Task Cancel_from_a_retained_reload_Loading_publication_restores_Ready_without_the_loader()
    {
        using var hub = new MessageHub();
        var loaderCalls = 0;
        var vm = new AsyncResourceVM<string>(
            "r",
            _ => { loaderCalls++; return Task.FromResult($"v{loaderCalls}"); },
            hub,
            NullDispatcher.Instance,
            retention: AsyncResourceRetention.RetainPrevious);
        vm.Construct();
        await vm.LoadAsync();
        vm.State.Status.Should().Be(AsyncResourceStatus.Ready);
        var ready = vm.State;
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == "State" && vm.State.Status == AsyncResourceStatus.Loading)
                vm.Cancel();
        };

        await vm.ReloadAsync();

        loaderCalls.Should().Be(1, "the cancelled reload never calls the loader");
        vm.State.Should().BeSameAs(ready);
        vm.State.Value.Should().Be("v1");
    }
}
