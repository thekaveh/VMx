using Microsoft.Extensions.DependencyInjection;
using VMx.Services;

namespace VMx.Extensions.DependencyInjection;

/// <summary>
/// Extension methods for registering VMx services with <see cref="IServiceCollection"/>.
/// </summary>
public static class ServiceCollectionExtensions
{
    /// <summary>
    /// Registers IMessageHub and IDispatcher with the host DI container.
    /// IMessageHub → singleton MessageHub.
    /// IDispatcher → singleton RxDispatcher.CreateForCurrentContext() (or a custom one).
    /// </summary>
    /// <param name="services">The service collection to configure.</param>
    /// <param name="configure">Optional action to configure VMx options.</param>
    /// <returns>The <paramref name="services"/> instance for chaining.</returns>
    public static IServiceCollection AddVMx(
        this IServiceCollection services,
        Action<VMxOptions>? configure = null)
    {
        var options = new VMxOptions();
        configure?.Invoke(options);

        services.AddSingleton<IMessageHub, MessageHub>();
        if (options.DispatcherFactory is not null)
            services.AddSingleton(options.DispatcherFactory);
        else
            services.AddSingleton<IDispatcher>(_ => RxDispatcher.CreateForCurrentContext());

        return services;
    }
}

/// <summary>
/// Configuration options for <see cref="ServiceCollectionExtensions.AddVMx"/>.
/// </summary>
public sealed class VMxOptions
{
    /// <summary>
    /// Gets or sets the factory used to create the <see cref="IDispatcher"/> singleton.
    /// When <see langword="null"/>, defaults to <see cref="RxDispatcher.CreateForCurrentContext"/>.
    /// </summary>
    public Func<IServiceProvider, IDispatcher>? DispatcherFactory { get; set; }

    /// <summary>
    /// Configures a custom dispatcher factory.
    /// </summary>
    /// <param name="factory">A factory that receives the <see cref="IServiceProvider"/> and returns an <see cref="IDispatcher"/>.</param>
    /// <returns>This options instance for chaining.</returns>
    public VMxOptions UseDispatcher(Func<IServiceProvider, IDispatcher> factory)
    {
        DispatcherFactory = factory;
        return this;
    }
}
