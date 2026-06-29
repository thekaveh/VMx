using VMx.Internal;
using VMx.Services;

namespace VMx.Builders;

/// <summary>
/// Shared resolution helper backing the <c>Services(IServiceProvider)</c> builder
/// overloads (VMX-021). Resolves <see cref="IMessageHub"/> and
/// <see cref="IDispatcher"/> from a DI container via the framework-agnostic
/// <see cref="IServiceProvider"/> contract, so the core library needs no
/// dependency on a specific DI package. Pair with
/// <c>services.AddVMx()</c> from VMx.Extensions.DependencyInjection (or any
/// container that registers the two services).
/// </summary>
internal static class BuilderServices
{
    /// <summary>
    /// Resolves the <see cref="IMessageHub"/> and <see cref="IDispatcher"/> pair
    /// from <paramref name="serviceProvider"/>.
    /// </summary>
    /// <exception cref="ArgumentNullException"><paramref name="serviceProvider"/> is null.</exception>
    /// <exception cref="InvalidOperationException">Either service is unregistered.</exception>
    internal static (IMessageHub Hub, IDispatcher Dispatcher) Resolve(IServiceProvider serviceProvider)
    {
        ThrowHelper.ThrowIfNull(serviceProvider, nameof(serviceProvider));

        var hub = serviceProvider.GetService(typeof(IMessageHub)) as IMessageHub
            ?? throw new InvalidOperationException(
                "No IMessageHub is registered in the service provider. "
                + "Call services.AddVMx() (VMx.Extensions.DependencyInjection) before resolving builders.");
        var dispatcher = serviceProvider.GetService(typeof(IDispatcher)) as IDispatcher
            ?? throw new InvalidOperationException(
                "No IDispatcher is registered in the service provider. "
                + "Call services.AddVMx() (VMx.Extensions.DependencyInjection) before resolving builders.");

        return (hub, dispatcher);
    }
}
