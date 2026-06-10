using System.Reactive.Linq;
using System.Reactive.Subjects;
using VMx.Messages;

namespace VMx.Services;

/// <summary>
/// Default Subject-backed hub. Hot stream — late subscribers do not see
/// prior messages. Subscriber-handler exceptions are swallowed (per HUB-007).
/// </summary>
public sealed class MessageHub : IMessageHub, IDisposable
{
    private readonly Subject<IMessage> _subject = new();
    private bool _disposed;

    /// <inheritdoc/>
    public IObservable<IMessage> Messages =>
        // Per HUB-007: wrap each subscription so a handler exception is isolated
        // per subscriber; the outer subject is never terminated by a bad handler.
        System.Reactive.Linq.Observable.Create<IMessage>(observer =>
        {
            return _subject.Subscribe(
                onNext: msg =>
                {
                    try { observer.OnNext(msg); }
                    catch { /* swallow — spec/03-messages.md §Subscriber resilience */ }
                },
                onError: observer.OnError,
                onCompleted: observer.OnCompleted);
        });

    /// <inheritdoc/>
    public void Send<TMessage>(TMessage message) where TMessage : IMessage
    {
        if (_disposed) return;
        try
        {
            _subject.OnNext(message);
        }
        catch (ObjectDisposedException)
        {
            // Send racing Dispose on another thread: the _disposed pre-check is
            // not atomic with OnNext, so the subject may be disposed in between.
            // Shutdown-time messages are dropped, same as the pre-check path
            // (sibling of the NotificationHub Post-after-Dispose fix).
        }
    }

    /// <summary>Completes and disposes the underlying subject.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _subject.OnCompleted();
        _subject.Dispose();
    }
}
