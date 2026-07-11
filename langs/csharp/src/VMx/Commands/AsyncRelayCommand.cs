using System.Collections.Immutable;
using System.Reactive;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using System.Reactive.Subjects;

namespace VMx.Commands;

/// <summary>
/// Concrete cancellable async <see cref="IAsyncCommand"/> implementation.
///
/// Spec: spec/04-commands.md §10, ADR-0056.
/// - Task receives a <see cref="CancellationToken"/> linked to both the in-flight
///   <see cref="Cancel"/> source and any token supplied to <see cref="ExecuteAsync"/>.
/// - Predicate null → <see cref="CanExecute"/> returns true when idle.
/// - While an execution is in flight, <see cref="CanExecute"/> returns false (so the
///   command cannot double-run), and <see cref="CanExecuteChanged"/> fires when the
///   in-flight state flips on start and on completion.
/// - Cancellation is NON-THROWING by default (DIA-007 alignment): the awaited
///   <see cref="ExecuteAsync"/> completes normally on cancel. Opt into the throwing
///   mode via the builder's <c>ThrowOnCancel()</c>.
/// - A faulted task (non-cancellation) propagates to the awaiter of
///   <see cref="ExecuteAsync"/>; on the fire-and-forget <see cref="Execute"/> path —
///   which has no caller to propagate to — it is routed to <see cref="Errors"/>
///   instead of being swallowed (mirrors ConfirmationDecoratorCommand, ADR-0049).
/// - Builder is IMMUTABLE (BLD-001): every setter returns a NEW builder instance.
/// </summary>
public sealed class AsyncRelayCommand : IAsyncCommand, IDisposable
{
    private readonly Func<CancellationToken, Task> _task;
    private readonly Func<bool>? _predicate;
    private readonly bool _throwOnCancel;
    private readonly CompositeDisposable _triggerSubscriptions = new();
    private readonly Subject<Exception> _errors = new();
    private readonly object _gate = new();
    private CancellationTokenSource? _cts;
    private bool _isExecuting;
    private bool _disposed;
    // Set by Cancel()/Dispose() so the catch block swallows only a cancellation we
    // requested through the command's own channel; an externally-supplied token's
    // cancellation (flag unset) is re-raised per spec/04 §10.3.
    private volatile bool _cancelRequested;

    internal AsyncRelayCommand(
        Func<CancellationToken, Task>? task,
        Func<bool>? predicate,
        bool throwOnCancel,
        IReadOnlyList<IObservable<Unit>> triggers)
    {
        _task = task ?? (_ => Task.CompletedTask);
        _predicate = predicate;
        _throwOnCancel = throwOnCancel;
        foreach (var t in triggers)
            _triggerSubscriptions.Add(t.Subscribe(_ => RaiseCanExecuteChanged()));
    }

    /// <inheritdoc/>
    public event EventHandler? CanExecuteChanged;

    /// <inheritdoc/>
    public bool IsExecuting
    {
        get
        {
            lock (_gate)
            {
                return _isExecuting;
            }
        }
    }

    /// <summary>
    /// Surfaces a fault from the fire-and-forget <see cref="Execute"/> path (a throwing
    /// task that is not a cancellation). The awaitable <see cref="ExecuteAsync"/> path
    /// keeps its throw behavior — await it directly to handle the error inline.
    /// Cancellations never reach this channel. Completes on <see cref="Dispose"/>.
    /// </summary>
    public IObservable<Exception> Errors => _errors.AsObservable();

    /// <summary>
    /// Returns false while an execution is in flight; otherwise true if no predicate is
    /// configured, or the predicate's result. A throwing predicate returns false.
    /// </summary>
    public bool CanExecute(object? parameter)
    {
        lock (_gate)
        {
            if (_disposed || _isExecuting) return false;
        }
        if (_predicate is null) return true;
        try { return _predicate(); }
        catch { return false; }
    }

    /// <summary>
    /// Fire-and-forget entry-point: starts <see cref="ExecuteAsync"/> and returns
    /// immediately. A faulting task is routed to <see cref="Errors"/> (cancellation is
    /// already swallowed by the non-throwing default).
    /// </summary>
    public void Execute(object? parameter) =>
        _ = ExecuteAsync(parameter).ContinueWith(
            t => EmitError(t.Exception!.GetBaseException()),
            CancellationToken.None,
            TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);

    // Routes a fire-and-forget fault to the Errors channel. The disposed check
    // is taken under _gate — the continuation runs on TaskScheduler.Default,
    // concurrently with a possible Dispose() (whose _disposed write is gated).
    // Reading _disposed off-gate was a data race on a non-volatile field. The
    // try/catch closes the residual window where Dispose() completes+disposes
    // _errors between the gated check and the emit: System.Reactive's
    // Subject.OnNext throws ObjectDisposedException post-dispose, whereas the
    // other flavors' subjects no-op — dropping the fault here restores parity
    // rather than surfacing an unobserved task exception.
    private void EmitError(Exception error)
    {
        lock (_gate)
        {
            if (_disposed) return;
        }
        try
        {
            _errors.OnNext(error);
        }
        catch (ObjectDisposedException)
        {
            // Concurrent Dispose() tore down the error subject; drop the fault.
        }
    }

    /// <inheritdoc/>
    public async Task ExecuteAsync(object? parameter = null, CancellationToken cancellationToken = default)
    {
        var cts = TryBeginExecution(cancellationToken);
        if (cts is null) return;

        RaiseCanExecuteChanged();
        try
        {
            await _task(cts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!_throwOnCancel && _cancelRequested)
        {
            // Non-throwing cancellation (DIA-007 alignment): the cancel was requested
            // through this command's own channel (Cancel()/Dispose()), so complete
            // normally. An externally-supplied token's cancellation leaves
            // _cancelRequested false and is re-raised (spec/04 §10.3, parity with
            // Python/Swift).
        }
        finally
        {
            lock (_gate)
            {
                if (ReferenceEquals(_cts, cts))
                    _cts = null;
                _isExecuting = false;
            }
            cts.Dispose();
            RaiseCanExecuteChanged();
        }
    }

    /// <inheritdoc/>
    public void Cancel()
    {
        CancellationTokenSource? cts;
        lock (_gate)
        {
            _cancelRequested = true;
            cts = _cts;
        }
        cts?.Cancel();
    }

    /// <summary>
    /// Cancels any in-flight execution, disposes trigger subscriptions, and completes
    /// the <see cref="Errors"/> channel. Idempotent.
    /// </summary>
    public void Dispose()
    {
        CancellationTokenSource? cts;
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
            _cancelRequested = true;
            cts = _cts;
        }
        cts?.Cancel();
        _triggerSubscriptions.Dispose();
        _errors.OnCompleted();
        _errors.Dispose();
    }

    private CancellationTokenSource? TryBeginExecution(CancellationToken cancellationToken)
    {
        lock (_gate)
        {
            if (_disposed || _isExecuting) return null;
            if (_predicate is not null)
            {
                bool allowed;
                try { allowed = _predicate(); }
                catch { return null; }
                if (!allowed) return null;
            }

            var cts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            _cts = cts;
            _cancelRequested = false;
            _isExecuting = true;
            return cts;
        }
    }

    /// <summary>
    /// Notifies subscribers that <see cref="CanExecute"/> may have changed without
    /// evaluating the predicate or invoking the task. A no-op after disposal and
    /// valid both while idle and while an execution is in flight.
    /// </summary>
    public void RaiseCanExecuteChanged()
    {
        lock (_gate)
        {
            if (_disposed) return;
        }
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>Returns a new immutable builder for <see cref="AsyncRelayCommand"/>.</summary>
    public static AsyncRelayCommandBuilder Builder() => new();
}

/// <summary>
/// Immutable fluent builder for <see cref="AsyncRelayCommand"/> (BLD-001). Each setter
/// returns a NEW builder instance; the original is unchanged.
/// </summary>
public sealed class AsyncRelayCommandBuilder
{
    private readonly Func<CancellationToken, Task>? _task;
    private readonly Func<bool>? _predicate;
    private readonly bool _throwOnCancel;
    private readonly ImmutableList<IObservable<Unit>> _triggers;

    /// <summary>Creates an empty builder (no task, predicate, or triggers).</summary>
    public AsyncRelayCommandBuilder()
        : this(null, null, false, ImmutableList<IObservable<Unit>>.Empty)
    {
    }

    private AsyncRelayCommandBuilder(
        Func<CancellationToken, Task>? task,
        Func<bool>? predicate,
        bool throwOnCancel,
        ImmutableList<IObservable<Unit>> triggers)
    {
        _task = task;
        _predicate = predicate;
        _throwOnCancel = throwOnCancel;
        _triggers = triggers;
    }

    /// <summary>Sets the cancellable async task. Returns a new builder.</summary>
    public AsyncRelayCommandBuilder Task(Func<CancellationToken, Task> task)
        => new(task, _predicate, _throwOnCancel, _triggers);

    /// <summary>Sets the predicate gating <c>CanExecute</c>. Returns a new builder.</summary>
    public AsyncRelayCommandBuilder Predicate(Func<bool> predicate)
        => new(_task, predicate, _throwOnCancel, _triggers);

    /// <summary>Adds a trigger observable (additive). Returns a new builder.</summary>
    public AsyncRelayCommandBuilder Triggers(IObservable<Unit> trigger)
        => new(_task, _predicate, _throwOnCancel, _triggers.Add(trigger));

    /// <summary>
    /// Opts into the throwing-on-cancel mode (default off): when enabled, a cancelled
    /// execution surfaces the <see cref="OperationCanceledException"/> to the awaiter of
    /// <c>ExecuteAsync</c> rather than completing normally. Returns a new builder.
    /// </summary>
    public AsyncRelayCommandBuilder ThrowOnCancel(bool throwOnCancel = true)
        => new(_task, _predicate, throwOnCancel, _triggers);

    /// <summary>Builds the <see cref="AsyncRelayCommand"/> (succeeds even with no task).</summary>
    public AsyncRelayCommand Build()
        => new(_task, _predicate, _throwOnCancel, _triggers);
}
