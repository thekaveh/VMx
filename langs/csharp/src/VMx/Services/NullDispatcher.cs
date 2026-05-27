using System.Reactive.Concurrency;

namespace VMx.Services;

/// <summary>
/// Null-object variant of <see cref="IDispatcher"/>. Both schedulers are
/// <see cref="ImmediateScheduler"/> — work scheduled on either runs
/// synchronously on the calling thread. Stateless and safe to share via
/// <see cref="Instance"/>. See spec/11-threading.md §"Null variant" and
/// ADR-0017.
/// </summary>
public sealed class NullDispatcher : IDispatcher
{
    /// <summary>Shared singleton instance.</summary>
    public static NullDispatcher Instance { get; } = new();

    private NullDispatcher() { }

    /// <inheritdoc/>
    public IScheduler Foreground => ImmediateScheduler.Instance;

    /// <inheritdoc/>
    public IScheduler Background => ImmediateScheduler.Instance;
}
