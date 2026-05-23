using System.Reactive.Concurrency;

namespace VMx.Services;

/// <summary>
/// Paired Rx schedulers for foreground (UI) and background work.
/// See spec/11-threading.md.
/// </summary>
public interface IDispatcher
{
    /// <summary>Gets the scheduler used for UI-thread (foreground) work.</summary>
    IScheduler Foreground { get; }

    /// <summary>Gets the scheduler used for background work.</summary>
    IScheduler Background { get; }
}
