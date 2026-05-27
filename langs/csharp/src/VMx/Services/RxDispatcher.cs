using System.Reactive.Concurrency;

namespace VMx.Services;

/// <summary>
/// Default <see cref="IDispatcher"/>. Foreground uses the current SynchronizationContext
/// (typical UI thread), Background uses the task pool.
/// </summary>
public sealed class RxDispatcher : IDispatcher
{
    /// <inheritdoc/>
    public IScheduler Foreground { get; }

    /// <inheritdoc/>
    public IScheduler Background { get; }

    /// <summary>
    /// Creates a dispatcher with explicitly supplied schedulers. Useful in tests
    /// where deterministic <c>TestScheduler</c> instances are preferred.
    /// </summary>
    /// <param name="foreground">Scheduler for UI-thread work.</param>
    /// <param name="background">Scheduler for background work.</param>
    public RxDispatcher(IScheduler foreground, IScheduler background)
    {
        Foreground = foreground;
        Background = background;
    }

    /// <summary>
    /// Builds a dispatcher whose Foreground binds to the current
    /// <see cref="SynchronizationContext"/>. Background uses TaskPoolScheduler.
    /// </summary>
    public static RxDispatcher CreateForCurrentContext()
    {
        var ctx = SynchronizationContext.Current
            ?? throw new InvalidOperationException(
                "No SynchronizationContext on the current thread. Use the (foreground, background) " +
                "constructor explicitly, e.g., from a UI framework's dispatcher.");
        return new RxDispatcher(
            foreground: new SynchronizationContextScheduler(ctx),
            background: TaskPoolScheduler.Default);
    }

    /// <summary>
    /// Builds a dispatcher whose Foreground and Background are both
    /// <see cref="ImmediateScheduler.Instance"/>. Useful in console scripts,
    /// xUnit suites, and any context that has no UI thread. Parity with
    /// Python <c>RxDispatcher.immediate()</c> and TypeScript
    /// <c>RxDispatcher.immediate()</c>.
    /// </summary>
    public static RxDispatcher Immediate() =>
        new(foreground: ImmediateScheduler.Instance, background: ImmediateScheduler.Instance);
}
