using System.Reactive.Concurrency;
using Microsoft.Extensions.DependencyInjection;
using VMx.Services;

namespace VMx.Extensions.DependencyInjection;

/// <summary>
/// Extension methods for registering VMx services with <see cref="IServiceCollection"/>.
/// </summary>
public static class ServiceCollectionExtensions
{
    /// <summary>
    /// Registers <see cref="IMessageHub"/> and <see cref="IDispatcher"/> with the host
    /// DI container.
    /// <see cref="IMessageHub"/> → singleton <see cref="MessageHub"/>.
    /// <see cref="IDispatcher"/> → singleton built lazily on first resolution.
    /// <para>
    /// The default dispatcher captures <see cref="SynchronizationContext.Current"/>
    /// at the moment <c>AddVMx</c> is invoked (typically the host's UI-thread
    /// startup path). The singleton factory then uses that captured context, so the
    /// IDispatcher is bound to the correct foreground even if the first resolution
    /// happens on a worker thread (background hosted service, test, etc.). When no
    /// <see cref="SynchronizationContext"/> exists at <c>AddVMx</c>-time and no
    /// custom factory is supplied via <see cref="VMxOptions.UseDispatcher"/>, the
    /// factory falls back to <see cref="RxDispatcher.CreateForCurrentContext"/>
    /// at resolution time (which throws if there is still no context).
    /// </para>
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
        {
            services.AddSingleton(options.DispatcherFactory);
        }
        else
        {
            // Capture SynchronizationContext NOW (typically host's UI-thread
            // startup) rather than later, when the singleton's first resolution
            // could happen on any thread.
            var capturedContext = SynchronizationContext.Current;
            services.AddSingleton<IDispatcher>(_ =>
            {
                if (capturedContext is not null)
                {
                    return new RxDispatcher(
                        foreground: new SynchronizationContextScheduler(capturedContext),
                        background: TaskPoolScheduler.Default);
                }
                // Fallback: no context at AddVMx time. Defer to legacy
                // behavior (throws if still no SynchronizationContext on the
                // thread that first resolves IDispatcher).
                return RxDispatcher.CreateForCurrentContext();
            });
        }

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
    /// When <see langword="null"/>, the dispatcher binds to the
    /// <see cref="SynchronizationContext"/> captured at <c>AddVMx</c> time,
    /// falling back to <see cref="RxDispatcher.CreateForCurrentContext"/> at
    /// resolution time only when no context was captured (see the
    /// <c>AddVMx</c> remarks).
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
