using FluentAssertions;
using Microsoft.Extensions.DependencyInjection;
using System.Reactive.Concurrency;
using VMx.Extensions.DependencyInjection;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Extensions;

public class DependencyInjectionTests
{
    [Fact]
    public void AddVMx_Registers_Singleton_MessageHub()
    {
        var services = new ServiceCollection();
        services.AddVMx(opts => opts.UseDispatcher(_ =>
            new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance)));
        var sp = services.BuildServiceProvider();
        var hub1 = sp.GetRequiredService<IMessageHub>();
        var hub2 = sp.GetRequiredService<IMessageHub>();
        hub1.Should().BeSameAs(hub2);
    }

    [Fact]
    public void AddVMx_Registers_IDispatcher_From_Factory()
    {
        var services = new ServiceCollection();
        var stubDispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        services.AddVMx(opts => opts.UseDispatcher(_ => stubDispatcher));
        var sp = services.BuildServiceProvider();
        var resolved = sp.GetRequiredService<IDispatcher>();
        resolved.Should().BeSameAs(stubDispatcher);
    }

    [Fact]
    public async Task AddVMx_Default_Dispatcher_Binds_To_Context_Captured_At_Registration()
    {
        // The default (no UseDispatcher) branch captures SynchronizationContext.Current
        // at AddVMx time, so the IDispatcher singleton resolves correctly even when the
        // first resolution happens on a worker thread with no current context.
        var previous = SynchronizationContext.Current;
        SynchronizationContext.SetSynchronizationContext(new SynchronizationContext());
        try
        {
            var services = new ServiceCollection();
            services.AddVMx(); // no factory → captures the current context now

            var sp = services.BuildServiceProvider();

            // Resolve on a worker thread whose SynchronizationContext.Current is null.
            // A successful resolution proves the context was captured at registration:
            // the fallback path (CreateForCurrentContext) would throw on this thread.
            var resolved = await Task.Run(() => sp.GetRequiredService<IDispatcher>());

            resolved.Should().BeOfType<RxDispatcher>();
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(previous);
        }
    }

    [Fact]
    public void AddVMx_Is_Idempotent_Does_Not_Double_Register()
    {
        // A library and the host app may both call AddVMx; TryAdd* must keep a
        // single registration so the container builds only one MessageHub /
        // RxDispatcher singleton (VMX-136).
        var services = new ServiceCollection();
        services.AddVMx(opts => opts.UseDispatcher(_ =>
            new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance)));
        services.AddVMx(opts => opts.UseDispatcher(_ =>
            new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance)));

        services.Count(d => d.ServiceType == typeof(IMessageHub))
            .Should().Be(1, "AddVMx must not double-register IMessageHub");
        services.Count(d => d.ServiceType == typeof(IDispatcher))
            .Should().Be(1, "AddVMx must not double-register IDispatcher");
    }

    [Fact]
    public void AddVMx_Preserves_A_Host_Registration_Made_First()
    {
        // TryAdd* means the first registration wins: a host that registers its own
        // IMessageHub before calling AddVMx keeps it (VMX-136).
        var hostHub = new MessageHub();
        var services = new ServiceCollection();
        services.AddSingleton<IMessageHub>(hostHub);
        services.AddVMx(opts => opts.UseDispatcher(_ =>
            new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance)));

        var sp = services.BuildServiceProvider();
        sp.GetRequiredService<IMessageHub>().Should().BeSameAs(hostHub);
    }
}
