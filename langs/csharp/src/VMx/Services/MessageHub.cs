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
    // Borrowed scope depth per borrowing thread. A borrower is a wait-for
    // owner of this hub with the batch owner and the drainer, so a wait for a
    // borrowed scope records an edge to it. A borrower's own sends, batches
    // and disposal on this hub never wait (spec/03 §4.2, ADR-0172).
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
                    // A borrowed body enqueues for the drain at the borrowed
                    // scope's exit.
                    if (_borrowers.ContainsKey(caller)) break;
                    var owner = ConflictingOwnerLocked(caller, includeBorrowers: true);
                    if (owner == 0) break;
                    // Only a wait that would close a live wait-for cycle, across
                    // hubs or through a lifecycle, container membership or
                    // ownership wait, may defer this send into the owner's FIFO
                    // drain (#1055, ADR-0172). A send from inside a hub callback
                    // waits like any other (#1159).
                    if (WaitForOwnerLocked(caller, owner, ref waiting)) break;
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
                    // A batch inside a borrowed body nests in that borrow. The
                    // batch owner's own nested batch does not wait for a
                    // borrowed scope.
                    var owner = _borrowers.ContainsKey(caller)
                        ? 0
                        : ConflictingOwnerLocked(caller, includeBorrowers: _batchOwnerThreadId != caller);
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
                var borrowerLeft = false;
                if (borrowed)
                {
                    _borrowedBatchDepth--;
                    borrowerLeft = _borrowers[caller] == 1;
                    if (borrowerLeft) _borrowers.Remove(caller);
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
                // A borrower that leaves while other borrowers remain also
                // wakes the waiters: their edges to it go, and each one names
                // a current owner again (spec/03 §4.1 rule 4).
                if (outermost || borrowerLeft)
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
        var caller = Environment.CurrentManagedThreadId;
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
                if (!WaitForBorrowedScopesLocked(caller))
                {
                    // The exit of the last borrowed scope drains the queue and
                    // finishes a requested disposal (spec/03 §4.2).
                    _drainerThreadId = 0;
                    WakeWaitersLocked();
                    return;
                }
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
                _subject.OnNext(message!);
            }
            catch
            {
                try { AbandonPending(); }
                catch { /* preserve the original delivery failure */ }
                throw;
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

    // The drainer's wait for the open borrowed scopes (spec/03 §4.2). Returns
    // true when no borrowed scope is open, or the hub is disposed, so the
    // drainer goes on. Returns false when the drainer must release the drain
    // to the exit of the last borrowed scope instead: its queue is empty
    // (rule 2), a disposal is requested, which that exit finishes and which
    // discards the queue, or its wait for a borrower would close a live
    // wait-for cycle (rule 5). In the last case the queued messages stay
    // queued, and that exit delivers them on the borrower's thread. Call
    // under _gate.
    private bool WaitForBorrowedScopesLocked(int caller)
    {
        var waiting = false;
        try
        {
            while (_borrowedBatchDepth > 0 && !_disposed)
            {
                if (_pending.Count == 0 || _disposeRequested) return false;
                var borrower = ForeignBorrowerLocked(caller);
                if (borrower == 0 || WaitForOwnerLocked(caller, borrower, ref waiting)) return false;
            }
            return true;
        }
        finally
        {
            EndWaitLocked(caller, ref waiting);
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
                    // A borrowed body records the intent for the exit of the
                    // last borrowed scope to finish.
                    var owner = _borrowers.ContainsKey(caller)
                        ? 0
                        : ConflictingOwnerLocked(caller, includeBorrowers: true);
                    if (_borrowers.ContainsKey(caller) ||
                        (owner != 0 && WaitForOwnerLocked(caller, owner, ref waiting)))
                    {
                        _disposeRequested = true;
                        WakeWaitersLocked();
                        return;
                    }
                    if (owner != 0) continue;
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

    // The one owner that a wait by caller names (spec/03 §4.1 rule 2): the
    // batch owner, then the drainer, then a borrower other than the caller.
    // Returns 0 when no other thread owns the hub.
    private int ConflictingOwnerLocked(int caller, bool includeBorrowers)
    {
        if (_batchOwnerThreadId != 0 && _batchOwnerThreadId != caller)
            return _batchOwnerThreadId;
        if (_drainerThreadId != 0 && _drainerThreadId != caller)
            return _drainerThreadId;
        return includeBorrowers ? ForeignBorrowerLocked(caller) : 0;
    }

    private int ForeignBorrowerLocked(int caller)
    {
        if (_borrowedBatchDepth == 0) return 0;
        foreach (var borrower in _borrowers.Keys)
            if (borrower != caller) return borrower;
        return 0;
    }

    // Waits for one owner of the hub (its batch owner, drainer or a
    // borrower), unless the wait would close a live wait-for cycle in the
    // shared graph, which holds every lifecycle, container membership,
    // ownership and hub wait (ADR-0172). Returns true for such a cycle, so the
    // caller takes its escape instead of waiting. The caller's edge stays
    // across a wake while its owner still owns the hub; a woken waiter records
    // its wait again on every pass, naming a current owner. EndWaitLocked
    // removes the edge once the caller stops waiting.
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
    // owner that no longer blocks it. Edges to a current owner (the drainer,
    // the batch owner or a borrower) stay. Once the hub is disposing, every
    // edge goes: no waiter waits for it again.
    private void WakeWaitersLocked()
    {
        if (_registeredWaits > 0)
        {
            if (_disposed || _disposeRequested) WaitForGraph.Shared.ReleaseWaiters(_gate);
            else WaitForGraph.Shared.ReleaseWaiters(_gate, _drainerThreadId, _batchOwnerThreadId, _borrowers);
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
