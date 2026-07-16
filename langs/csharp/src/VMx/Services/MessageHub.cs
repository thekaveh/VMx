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
    private readonly object _gate = new();
    private readonly Queue<IMessage> _pending = new();
    private readonly Subject<IMessage> _subject = new();
    private bool _disposed;
    private bool _subjectTerminationClaimed;
    private bool _subjectTerminated;
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
        var caller = Environment.CurrentManagedThreadId;
        var shouldDrain = false;
        lock (_gate)
        {
            while (((_batchOwnerThreadId != 0 && _batchOwnerThreadId != caller) ||
                    (_drainerThreadId != 0 && _drainerThreadId != caller)) && !_disposed)
            {
                if (s_deliveryDepth > 0) break;
                Monitor.Wait(_gate);
            }
            if (_disposed) return;

            _pending.Enqueue(message);
            if (_batchOwnerThreadId != 0) return;
            if (_drainerThreadId == 0)
            {
                _drainerThreadId = caller;
                shouldDrain = true;
            }
            else if (_drainerThreadId == caller)
            {
                return;
            }
        }

        if (shouldDrain) DrainQueue();
    }

    /// <inheritdoc/>
    public void Batch(Action transaction)
    {
        ThrowHelper.ThrowIfNull(transaction, nameof(transaction));
        var caller = Environment.CurrentManagedThreadId;
        var entered = false;
        lock (_gate)
        {
            while (((_batchOwnerThreadId != 0 && _batchOwnerThreadId != caller) ||
                    (_drainerThreadId != 0 && _drainerThreadId != caller)) && !_disposed)
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
            IMessage? message = null;
            var stopDraining = false;
            var shouldTerminateSubject = false;
            lock (_gate)
            {
                if (_disposed || _pending.Count == 0)
                {
                    shouldTerminateSubject = ReleaseDrainerLocked();
                    stopDraining = true;
                }
                else
                {
                    message = _pending.Dequeue();
                }
            }
            if (shouldTerminateSubject) TerminateSubject();
            if (stopDraining) return;
#if DEBUG
            messageTypes.Add(message!.GetType().Name);
#endif
            try
            {
                s_deliveryDepth++;
                _subject.OnNext(message!);
            }
            catch
            {
                try { AbandonPending(); }
                catch { /* preserve the original delivery failure */ }
                throw;
            }
            finally
            {
                s_deliveryDepth--;
            }
#if DEBUG
            delivered++;
            lock (_gate)
            {
                if (delivered < DevelopmentDrainLimit || _pending.Count == 0) continue;
                foreach (var pending in _pending)
                    messageTypes.Add(pending.GetType().Name);
            }
            var cycleError = new InvalidOperationException(
                $"MessageHub drain exceeded {DevelopmentDrainLimit} messages; " +
                $"possible publish cycle involving: " +
                $"{string.Join(", ", messageTypes.OrderBy(name => name, StringComparer.Ordinal))}");
            AbandonPending();
            throw cycleError;
#endif
        }
    }

    private void AbandonPending()
    {
        var shouldTerminateSubject = false;
        lock (_gate)
        {
            _pending.Clear();
            shouldTerminateSubject = ReleaseDrainerLocked();
        }
        if (shouldTerminateSubject) TerminateSubject();
    }

    /// <summary>
    /// Releases the active drainer and atomically transfers terminal-stream
    /// ownership to it when disposal arrived during delivery.
    /// Caller must hold <see cref="_gate"/>.
    /// </summary>
    private bool ReleaseDrainerLocked()
    {
        _drainerThreadId = 0;
        var shouldTerminateSubject = _disposed && !_subjectTerminationClaimed;
        if (shouldTerminateSubject) _subjectTerminationClaimed = true;
        Monitor.PulseAll(_gate);
        return shouldTerminateSubject;
    }

    private void TerminateSubject()
    {
        try
        {
            _subject.OnCompleted();
        }
        finally
        {
            try
            {
                _subject.Dispose();
            }
            finally
            {
                lock (_gate)
                {
                    _subjectTerminated = true;
                    Monitor.PulseAll(_gate);
                }
            }
        }
    }

    /// <summary>Completes and disposes the underlying subject.</summary>
    public void Dispose()
    {
        var caller = Environment.CurrentManagedThreadId;
        var shouldTerminateSubject = false;
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
            _pending.Clear();
            Monitor.PulseAll(_gate);

            if (_drainerThreadId == 0)
            {
                _subjectTerminationClaimed = true;
                shouldTerminateSubject = true;
            }
            else if (_drainerThreadId != caller && s_deliveryDepth == 0)
            {
                while (!_subjectTerminated)
                    Monitor.Wait(_gate);
                return;
            }
        }
        if (shouldTerminateSubject) TerminateSubject();
    }
}
