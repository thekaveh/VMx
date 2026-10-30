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
    private IObservable<IMessage>? _messages;
    private bool _disposeRequested;
    private bool _disposed;
    private bool _subjectTerminationClaimed;
    private int _drainerThreadId;
    private int _batchOwnerThreadId;
    private int _batchDepth;
    private int _borrowedBatchDepth;
    // Threads with a wait edge on this hub; the shared graph is touched on a
    // wake only while one exists.
    private int _registeredWaits;
    // Borrowed scope depth per borrowing thread. A borrower's own sends,
    // batches and disposal on this hub never wait for the owner it borrowed
    // from (spec/03: the borrowed body may enqueue).
    private readonly Dictionary<int, int> _borrowers = new();

    /// <inheritdoc/>
    /// <remarks>
    /// Subscribing attaches the caller's observer directly to the hub subject
    /// through an isolating observer rather than through
    /// <c>Observable.Create</c>: Rx's auto-detach safeguard would otherwise
    /// dispose a raw subscriber the first time its handler threw, before the
    /// hub could swallow the exception (spec/03 §3.4, HUB-007).
    /// </remarks>
    public IObservable<IMessage> Messages => _messages ??= new IsolatedMessages(_subject);

    /// <inheritdoc/>
    public void Send<TMessage>(TMessage message) where TMessage : IMessage
    {
        var caller = Environment.CurrentManagedThreadId;
        var shouldDrain = false;
        lock (_gate)
        {
            var waiting = false;
            try
            {
                while (!_disposed && !_disposeRequested)
                {
                    // A borrowed body enqueues for the owner's drain.
                    if (_borrowers.ContainsKey(caller)) break;
                    var owner = ConflictingOwnerLocked(caller);
                    if (owner != 0)
                    {
                        // Only a wait that would close a real wait-for cycle,
                        // across hubs or through a container membership or
                        // ownership wait (#1055), may defer this send into the
                        // owner's FIFO drain.
                        if (WaitForOwnerLocked(caller, owner, ref waiting)) break;
                        continue;
                    }
                    EndWaitLocked(caller, ref waiting);
                    if (_borrowedBatchDepth > 0)
                    {
                        if (s_deliveryDepth > 0) break;
                        Monitor.Wait(_gate);
                        continue;
                    }
                    break;
                }
            }
            finally
            {
                EndWaitLocked(caller, ref waiting);
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
            var waiting = false;
            try
            {
                while (!_disposed && !_disposeRequested)
                {
                    // A batch inside a borrowed body nests in that borrow.
                    var owner = _borrowers.ContainsKey(caller) ? 0 : ConflictingOwnerLocked(caller);
                    if (_borrowers.ContainsKey(caller) ||
                        (owner != 0 && WaitForOwnerLocked(caller, owner, ref waiting)))
                    {
                        // A cyclic batch borrows the target: its body may
                        // enqueue, but the target owner cannot resume
                        // draining until this borrowed scope exits.
                        _borrowedBatchDepth++;
                        _borrowers[caller] = _borrowers.TryGetValue(caller, out var depth) ? depth + 1 : 1;
                        borrowed = true;
                        entered = true;
                        break;
                    }
                    if (owner != 0) continue;
                    EndWaitLocked(caller, ref waiting);
                    if (_borrowedBatchDepth > 0 && _batchOwnerThreadId != caller)
                    {
                        Monitor.Wait(_gate);
                        continue;
                    }
                    break;
                }
            }
            finally
            {
                EndWaitLocked(caller, ref waiting);
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
                    if (_borrowers[caller] == 1) _borrowers.Remove(caller);
                    else _borrowers[caller]--;
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
                    WakeWaitersLocked();
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
        WakeWaitersLocked();
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
            var waiting = false;
            try
            {
                while (!_disposed && !_disposeRequested)
                {
                    // A borrowed body records the intent for the owner to finish.
                    var owner = _borrowers.ContainsKey(caller) ? 0 : ConflictingOwnerLocked(caller);
                    if (_borrowers.ContainsKey(caller) ||
                        (owner != 0 && WaitForOwnerLocked(caller, owner, ref waiting)))
                    {
                        _disposeRequested = true;
                        WakeWaitersLocked();
                        return;
                    }
                    if (owner != 0) continue;
                    EndWaitLocked(caller, ref waiting);
                    if (_borrowedBatchDepth > 0)
                    {
                        Monitor.Wait(_gate);
                        continue;
                    }
                    break;
                }
            }
            finally
            {
                EndWaitLocked(caller, ref waiting);
            }
            if (_disposed || _disposeRequested) return;
            shouldTerminateSubject = FinishDisposeLocked();
            WakeWaitersLocked();
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

    // Waits for the hub's batch or drain owner, unless the wait would close a
    // wait-for cycle in the shared graph, which also holds container
    // membership and ownership waits (#1055). Returns true for such a cycle,
    // so the caller takes its escape instead of waiting. The caller's edge
    // stays across wakes, so a woken waiter that must wait again leaves no gap
    // in the chain; EndWaitLocked removes it once the caller stops waiting.
    private bool WaitForOwnerLocked(int caller, int owner, ref bool waiting)
    {
        if (!WaitForGraph.Shared.TryBeginWait(_gate, owner, caller))
        {
            EndWaitLocked(caller, ref waiting);
            return true;
        }
        if (!waiting)
        {
            waiting = true;
            _registeredWaits++;
        }
        Monitor.Wait(_gate);
        return false;
    }

    // Removes the caller's wait edge on this hub, if it has one.
    private void EndWaitLocked(int caller, ref bool waiting)
    {
        if (!waiting) return;
        WaitForGraph.Shared.EndWait(caller);
        waiting = false;
        _registeredWaits--;
    }

    // Wakes every thread that waits for this hub. Edges to a thread that no
    // longer owns the hub go first, so no woken waiter keeps an edge to an
    // owner that no longer blocks it. Edges to a current owner stay. Once the
    // hub is disposing, every edge goes: no waiter waits for it again.
    private void WakeWaitersLocked()
    {
        if (_registeredWaits > 0)
        {
            if (_disposed || _disposeRequested) WaitForGraph.Shared.ReleaseWaiters(_gate);
            else WaitForGraph.Shared.ReleaseWaiters(_gate, _drainerThreadId, _batchOwnerThreadId);
        }
        Monitor.PulseAll(_gate);
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
    private sealed class IsolatedMessages(Subject<IMessage> subject) : IObservable<IMessage>
    {
        public IDisposable Subscribe(IObserver<IMessage> observer)
        {
            ThrowHelper.ThrowIfNull(observer, nameof(observer));
            try
            {
                return subject.Subscribe(new IsolatingObserver(observer));
            }
            catch (ObjectDisposedException error)
            {
                // A late subscriber after Dispose gets OnError, as Rx
                // Observable.Create delivered it, instead of a caller throw.
                observer.OnError(error);
                return System.Reactive.Disposables.Disposable.Empty;
            }
        }
    }

    private sealed class IsolatingObserver(IObserver<IMessage> inner) : IObserver<IMessage>
    {
        public void OnNext(IMessage value)
        {
            try { inner.OnNext(value); }
            catch { /* isolate the failing subscriber per HUB-007; keep it attached */ }
        }

        public void OnError(Exception error) => inner.OnError(error);

        public void OnCompleted() => inner.OnCompleted();
    }
}
