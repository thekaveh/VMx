using System.Reactive.Concurrency;

namespace VMx.Services;

/// <summary>
/// Minimal interface for the dispatcher. Replaced by the full definition in Task 3.
/// </summary>
public interface IDispatcher
{
    /// <summary>Gets the scheduler used for UI-thread (foreground) work.</summary>
    IScheduler Foreground { get; }

    /// <summary>Gets the scheduler used for background work.</summary>
    IScheduler Background { get; }
}
