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
}
