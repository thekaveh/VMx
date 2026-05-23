using System.Reactive.Concurrency;
using Microsoft.Reactive.Testing;
using VMx.Services;

namespace VMx.Tests.Helpers;

/// <summary>
/// IDispatcher backed by deterministic Rx TestSchedulers so tests can
/// advance virtual time precisely. Foreground and Background each get
/// their own scheduler so cross-scheduler dispatch is observable.
/// </summary>
public sealed class TestDispatcher : IDispatcher
{
    public TestScheduler ForegroundScheduler { get; } = new();
    public TestScheduler BackgroundScheduler { get; } = new();

    public IScheduler Foreground => ForegroundScheduler;
    public IScheduler Background => BackgroundScheduler;

    public void AdvanceAll(long ticks = 1)
    {
        ForegroundScheduler.AdvanceBy(ticks);
        BackgroundScheduler.AdvanceBy(ticks);
    }
}
