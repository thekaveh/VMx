using System.Diagnostics;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Runtime.ExceptionServices;
using VMx.Internal;
using VMx.Messages;

namespace VMx.Services;

/// <summary>
/// Default Subject-backed hub. Hot stream — late subscribers do not see
/// prior messages. Subscriber-handler exceptions are swallowed (per HUB-007).
/// </summary>
public sealed class MessageHub : ITransactionalMessageHub, IDisposable
{
#if DEBUG
    private const int DevelopmentDrainLimit = 10_000;
#endif
    private readonly object _gate = new();
    private readonly Queue<IMessage> _pending = new();
    private readonly Subject<IMessage> _subject = new();
    private bool _disposed;
    private bool _draining;
    private int _batchDepth;

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
        lock (_gate)
        {
            if (_disposed) return;
            _pending.Enqueue(message);
            if (_batchDepth == 0 && !_draining) DrainQueue();
        }
    }

    /// <inheritdoc/>
    public void Batch(Action transaction)
    {
        ThrowHelper.ThrowIfNull(transaction, nameof(transaction));
        ExceptionDispatchInfo? callbackError = null;
        Exception? drainError = null;

        lock (_gate)
        {
            _batchDepth++;
            try
            {
                transaction();
            }
            catch (Exception error)
            {
                callbackError = ExceptionDispatchInfo.Capture(error);
            }
            finally
            {
                _batchDepth--;
                if (_batchDepth == 0 && !_disposed && !_draining)
                {
                    try { DrainQueue(); }
                    catch (Exception error) { drainError = error; }
                }
            }
        }

        callbackError?.Throw();
        if (drainError is not null) ExceptionDispatchInfo.Capture(drainError).Throw();
    }

    private void DrainQueue()
    {
        _draining = true;
#if DEBUG
        var delivered = 0;
        var messageTypes = new HashSet<string>(StringComparer.Ordinal);
#endif
        try
        {
            while (!_disposed && _pending.Count > 0)
            {
                var message = _pending.Dequeue();
#if DEBUG
                messageTypes.Add(message.GetType().Name);
#endif
                try
                {
                    _subject.OnNext(message);
                }
                catch (ObjectDisposedException)
                {
                    Debug.Assert(_disposed, "A live MessageHub subject was unexpectedly disposed.");
                    if (!_disposed) throw;
                }
#if DEBUG
                delivered++;
                if (delivered >= DevelopmentDrainLimit && _pending.Count > 0)
                {
                    foreach (var pending in _pending) messageTypes.Add(pending.GetType().Name);
                    _pending.Clear();
                    throw new InvalidOperationException(
                        $"MessageHub drain exceeded {DevelopmentDrainLimit} messages; " +
                        $"possible publish cycle involving: " +
                        $"{string.Join(", ", messageTypes.OrderBy(name => name, StringComparer.Ordinal))}");
                }
#endif
            }
        }
        finally
        {
            _draining = false;
        }
    }

    /// <summary>Completes and disposes the underlying subject.</summary>
    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
            _pending.Clear();
            _subject.OnCompleted();
            _subject.Dispose();
        }
    }
}
