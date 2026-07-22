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
    private static readonly object s_waitGraphGate = new();
    private static readonly Dictionary<int, int> s_waitGraph = [];
    private readonly object _gate = new();
    private readonly Queue<IMessage> _pending = new();
    private readonly Subject<IMessage> _subject = new();
    private bool _disposeRequested;
    private bool _disposed;
    private bool _subjectTerminationClaimed;
    private int _drainerThreadId;
    private int _batchOwnerThreadId;
    private int _batchDepth;
    private int _borrowedBatchDepth;

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
            while (!_disposed && !_disposeRequested)
            {
                var owner = ConflictingOwnerLocked(caller);
                if (owner != 0)
                {
                    // Only an edge that closes a real cross-hub wait cycle may
                    // defer this send into the target's existing FIFO drain.
                    if (WaitForOwnerLocked(caller, owner)) break;
                    continue;
                }
                if (_borrowedBatchDepth > 0)
                {
                    if (s_deliveryDepth > 0) break;
                    Monitor.Wait(_gate);
                    continue;
                }
                break;
            }
            if (_disposed || _disposeRequested) return;

            _pending.Enqueue(message);
            if (_batchOwnerThreadId != 0 || _borrowedBatchDepth > 0) return;
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
        var borrowed = false;
        lock (_gate)
        {
            while (!_disposed && !_disposeRequested)
            {
                var owner = ConflictingOwnerLocked(caller);
                if (owner != 0)
                {
                    if (WaitForOwnerLocked(caller, owner))
                    {
                        // A cyclic batch borrows the target: its body may enqueue,
                        // but the target owner cannot resume draining until this
                        // borrowed scope exits.
                        _borrowedBatchDepth++;
                        borrowed = true;
                        entered = true;
                        break;
                    }
                    continue;
                }
                if (_borrowedBatchDepth > 0 && _batchOwnerThreadId != caller)
                {
                    Monitor.Wait(_gate);
                    continue;
                }
                break;
            }
            if (!_disposed && !_disposeRequested && !borrowed)
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
        var shouldTerminateSubject = false;
        if (entered)
        {
            lock (_gate)
            {
                bool outermost;
                if (borrowed)
                {
                    _borrowedBatchDepth--;
                    outermost = _borrowedBatchDepth == 0;
                }
                else
                {
                    _batchDepth--;
                    outermost = _batchDepth == 0;
                    if (outermost) _batchOwnerThreadId = 0;
                }

                if (outermost && _disposeRequested)
                    shouldTerminateSubject = FinishDisposeLocked();

                if (outermost && !_disposed && _pending.Count > 0 &&
                    _batchOwnerThreadId == 0 && _borrowedBatchDepth == 0 &&
                    _drainerThreadId == 0)
                {
                    _drainerThreadId = caller;
                    shouldDrain = true;
                }
                if (outermost)
                    Monitor.PulseAll(_gate);
            }
        }

        if (shouldTerminateSubject) TerminateSubject();
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
                while (_borrowedBatchDepth > 0 && !_disposed)
                    Monitor.Wait(_gate);
                if (_disposeRequested)
                    _ = FinishDisposeLocked();
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
        if (_disposeRequested)
        {
            _disposeRequested = false;
            _disposed = true;
            _pending.Clear();
        }
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
            _subject.Dispose();
        }
    }

    /// <summary>Completes and disposes the underlying subject.</summary>
    public void Dispose()
    {
        var caller = Environment.CurrentManagedThreadId;
        var shouldTerminateSubject = false;
        lock (_gate)
        {
            if (_disposed || _disposeRequested) return;
            while (!_disposed && !_disposeRequested)
            {
                var owner = ConflictingOwnerLocked(caller);
                if (owner != 0)
                {
                    if (WaitForOwnerLocked(caller, owner))
                    {
                        _disposeRequested = true;
                        Monitor.PulseAll(_gate);
                        return;
                    }
                    continue;
                }
                if (_borrowedBatchDepth > 0)
                {
                    Monitor.Wait(_gate);
                    continue;
                }
                break;
            }
            if (_disposed || _disposeRequested) return;
            shouldTerminateSubject = FinishDisposeLocked();
            Monitor.PulseAll(_gate);
        }
        if (shouldTerminateSubject) TerminateSubject();
    }

    private int ConflictingOwnerLocked(int caller)
    {
        if (_batchOwnerThreadId != 0 && _batchOwnerThreadId != caller)
            return _batchOwnerThreadId;
        if (_drainerThreadId != 0 && _drainerThreadId != caller)
            return _drainerThreadId;
        return 0;
    }

    private bool WaitForOwnerLocked(int caller, int owner)
    {
        lock (s_waitGraphGate)
        {
            s_waitGraph[caller] = owner;
            var cursor = owner;
            var visited = new HashSet<int>();
            while (s_waitGraph.TryGetValue(cursor, out var next))
            {
                if (next == caller)
                {
                    s_waitGraph.Remove(caller);
                    return true;
                }
                if (!visited.Add(cursor)) break;
                cursor = next;
            }
        }

        try
        {
            Monitor.Wait(_gate);
        }
        finally
        {
            lock (s_waitGraphGate)
                s_waitGraph.Remove(caller);
        }
        return false;
    }

    private bool FinishDisposeLocked()
    {
        _disposeRequested = false;
        _disposed = true;
        _pending.Clear();
        if (_drainerThreadId != 0 || _subjectTerminationClaimed) return false;

        _subjectTerminationClaimed = true;
        return true;
    }
}
