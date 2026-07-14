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
    [ThreadStatic]
    private static int s_deliveryDepth;

    private sealed class PendingDelivery(IMessage message)
    {
        public IMessage Message { get; } = message;
        public ManualResetEventSlim Completed { get; } = new(false);
        public Exception? Error { get; set; }
    }

    private readonly object _gate = new();
    private readonly Queue<PendingDelivery> _pending = new();
    private readonly Subject<IMessage> _subject = new();
    private bool _disposed;
    private int _drainerThreadId;
    private int _batchOwnerThreadId;
    private int _batchDepth;

    /// <inheritdoc/>
    public IObservable<IMessage> Messages =>
        Observable.Create<IMessage>(observer =>
            _subject.Subscribe(
                onNext: message =>
                {
                    try { observer.OnNext(message); }
                    catch { /* isolate the failing subscriber per HUB-007 */ }
                },
                onError: observer.OnError,
                onCompleted: observer.OnCompleted));

    /// <inheritdoc/>
    public void Send<TMessage>(TMessage message) where TMessage : IMessage
    {
        var delivery = new PendingDelivery(message);
        var caller = Environment.CurrentManagedThreadId;
        var shouldDrain = false;
        lock (_gate)
        {
            while (_batchOwnerThreadId != 0 && _batchOwnerThreadId != caller && !_disposed)
                Monitor.Wait(_gate);
            if (_disposed)
            {
                delivery.Completed.Dispose();
                return;
            }

            _pending.Enqueue(delivery);
            if (_batchOwnerThreadId == caller) return;
            if (_drainerThreadId == 0)
            {
                _drainerThreadId = caller;
                shouldDrain = true;
            }
            else if (_drainerThreadId == caller || s_deliveryDepth > 0)
            {
                return;
            }
        }

        if (shouldDrain)
            DrainQueue();
        else
            delivery.Completed.Wait();
        if (delivery.Error is not null)
            ExceptionDispatchInfo.Capture(delivery.Error).Throw();
        delivery.Completed.Dispose();
    }

    /// <inheritdoc/>
    public void Batch(Action transaction)
    {
        ThrowHelper.ThrowIfNull(transaction, nameof(transaction));
        var caller = Environment.CurrentManagedThreadId;
        var entered = false;
        lock (_gate)
        {
            while (_batchOwnerThreadId != 0 && _batchOwnerThreadId != caller && !_disposed)
                Monitor.Wait(_gate);
            if (!_disposed)
            {
                _batchOwnerThreadId = caller;
                _batchDepth++;
                entered = true;
            }
        }

        ExceptionDispatchInfo? callbackError = null;
        try { transaction(); }
        catch (Exception error) { callbackError = ExceptionDispatchInfo.Capture(error); }

        var shouldDrain = false;
        if (entered)
        {
            lock (_gate)
            {
                _batchDepth--;
                if (_batchDepth == 0)
                {
                    _batchOwnerThreadId = 0;
                    if (!_disposed && _pending.Count > 0 && _drainerThreadId == 0)
                    {
                        _drainerThreadId = caller;
                        shouldDrain = true;
                    }
                    Monitor.PulseAll(_gate);
                }
            }
        }

        ExceptionDispatchInfo? drainError = null;
        if (shouldDrain)
        {
            try { DrainQueue(); }
            catch (Exception error) { drainError = ExceptionDispatchInfo.Capture(error); }
        }
        callbackError?.Throw();
        drainError?.Throw();
    }

    private void DrainQueue()
    {
#if DEBUG
        var delivered = 0;
        var messageTypes = new HashSet<string>(StringComparer.Ordinal);
#endif
        while (true)
        {
            PendingDelivery delivery;
            lock (_gate)
            {
                if (_disposed || _pending.Count == 0)
                {
                    _drainerThreadId = 0;
                    Monitor.PulseAll(_gate);
                    return;
                }
                delivery = _pending.Dequeue();
            }
#if DEBUG
            messageTypes.Add(delivery.Message.GetType().Name);
#endif
            try
            {
                s_deliveryDepth++;
                _subject.OnNext(delivery.Message);
            }
            catch (Exception error)
            {
                delivery.Error = error;
                AbandonPending(error);
                throw;
            }
            finally
            {
                s_deliveryDepth--;
                delivery.Completed.Set();
            }
#if DEBUG
            delivered++;
            lock (_gate)
            {
                if (delivered < DevelopmentDrainLimit || _pending.Count == 0) continue;
                foreach (var pending in _pending)
                    messageTypes.Add(pending.Message.GetType().Name);
            }
            var cycleError = new InvalidOperationException(
                $"MessageHub drain exceeded {DevelopmentDrainLimit} messages; " +
                $"possible publish cycle involving: " +
                $"{string.Join(", ", messageTypes.OrderBy(name => name, StringComparer.Ordinal))}");
            AbandonPending(cycleError);
            throw cycleError;
#endif
        }
    }

    private void AbandonPending(Exception error)
    {
        PendingDelivery[] abandoned;
        lock (_gate)
        {
            abandoned = _pending.ToArray();
            _pending.Clear();
            _drainerThreadId = 0;
            Monitor.PulseAll(_gate);
        }
        foreach (var delivery in abandoned)
        {
            delivery.Error = error;
            delivery.Completed.Set();
        }
    }

    /// <summary>Completes and disposes the underlying subject.</summary>
    public void Dispose()
    {
        PendingDelivery[] abandoned;
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
            abandoned = _pending.ToArray();
            _pending.Clear();
            Monitor.PulseAll(_gate);
        }
        foreach (var delivery in abandoned) delivery.Completed.Set();
        _subject.OnCompleted();
        _subject.Dispose();
    }
}
