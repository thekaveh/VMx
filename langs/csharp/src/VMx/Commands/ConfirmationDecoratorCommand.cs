using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Runtime.ExceptionServices;
using System.Windows.Input;

namespace VMx.Commands;

/// <summary>
/// Wraps a single inner <see cref="ICommand"/> with an async confirmation gate.
/// See spec/04-commands.md §Decorators and ADR-0012.
///
/// The confirm delegate is intentionally UI-agnostic: it returns a Task&lt;bool&gt;
/// that resolves to true if the user accepted, false otherwise. Bridge helpers
/// to a notification hub live in the optional VMx.Notifications assembly.
///
/// An inner command is asynchronous when it implements <see cref="IAsyncCommand"/>
/// or is another <see cref="ConfirmationDecoratorCommand"/> (spec §8.3.2,
/// ADR-0145). The awaitable <see cref="ExecuteAsync"/> awaits such an inner
/// operation to completion; the fire-and-forget <see cref="Execute"/> starts it
/// through the inner's own <see cref="ICommand.Execute"/>. The decorator adds no
/// admission or cancellation of its own beyond confirmation and disposal, and it
/// never owns, cancels, or disposes the inner command.
/// </summary>
public sealed class ConfirmationDecoratorCommand : ICommand, IDisposable
{
    private readonly ICommand _inner;
    private readonly Func<Task<bool>> _confirm;
    private readonly EventHandler _innerHandler;
    private readonly Subject<Exception> _errors = new();
    private readonly object _errorGate = new();
    private volatile bool _disposed;

    /// <summary>Creates a new <see cref="ConfirmationDecoratorCommand"/>.</summary>
    public ConfirmationDecoratorCommand(ICommand inner, Func<Task<bool>> confirm)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _confirm = confirm ?? throw new ArgumentNullException(nameof(confirm));
        _innerHandler = (sender, args) => CanExecuteChanged?.Invoke(this, args);
        _inner.CanExecuteChanged += _innerHandler;
    }

    /// <inheritdoc/>
    public event EventHandler? CanExecuteChanged;

    /// <summary>
    /// Observable that surfaces an error from the fire-and-forget <see cref="Execute"/>
    /// path — either the confirm delegate faulting or a synchronous inner command
    /// throwing from <see cref="ICommand.Execute"/>.
    /// <see cref="ICommand.Execute"/> is <c>void</c>, so it cannot propagate the
    /// failure across the async confirm gate the way <see cref="RelayCommand"/>'s
    /// task does; instead of swallowing it (a discarded faulted <see cref="Task"/>
    /// would otherwise surface only as an <c>UnobservedTaskException</c> at GC) the
    /// error is emitted here (VMX-009). An asynchronous inner command started on
    /// that path reports its own operation's faults on its own error channel, so
    /// they are not re-emitted here (spec §8.3.2, ADR-0145). The awaitable
    /// <see cref="ExecuteAsync"/> path keeps its throw behavior — await it directly
    /// to handle the error inline. Completes on <see cref="Dispose"/>.
    /// </summary>
    public IObservable<Exception> Errors => _errors.AsObservable();

    /// <inheritdoc/>
    /// <remarks>Re-checks disposal after the call-out, because the inner predicate
    /// may dispose this wrapper (spec/04 §8.4).</remarks>
    public bool CanExecute(object? parameter) =>
        !_disposed && _inner.CanExecute(parameter) && !_disposed;

    /// <inheritdoc/>
    /// <remarks>
    /// Synchronous <c>Execute</c> kicks off the confirmation flow and returns immediately.
    /// Once confirmed, it invokes the inner command's own <see cref="ICommand.Execute"/>,
    /// which starts an asynchronous inner command without awaiting it; that inner
    /// command reports its operation's faults on its own error channel (spec §8.3.2,
    /// ADR-0145). A rejecting confirm delegate or a throwing synchronous inner command
    /// is routed to <see cref="Errors"/> rather than swallowed (VMX-009). Use
    /// <see cref="ExecuteAsync"/> to await the full sequence and observe the failure inline.
    /// </remarks>
    public void Execute(object? parameter) =>
        _ = RunAsync(parameter, awaitInner: false).ContinueWith(
            t =>
            {
                EmitError(t.Exception!.GetBaseException());
            },
            CancellationToken.None,
            TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);

    /// <summary>
    /// Awaits the confirm delegate and, if it resolves <c>true</c>, invokes the inner
    /// command exactly once: an <see cref="IAsyncCommand"/> or nested
    /// <see cref="ConfirmationDecoratorCommand"/> through its own <c>ExecuteAsync</c>,
    /// any other command through <see cref="ICommand.Execute"/>. The returned task
    /// completes when that invocation completes — for an asynchronous inner, when its
    /// operation finishes (spec §8.3.2, ADR-0145).
    /// </summary>
    /// <remarks>
    /// A confirm or inner failure propagates to the awaiter unchanged and is not
    /// emitted on <see cref="Errors"/>. The inner command applies its own admission
    /// and cancellation: a busy <see cref="AsyncRelayCommand"/> drops the call, and the
    /// inner's <see cref="IAsyncCommand.Cancel"/> outcome reaches the awaiter as the
    /// inner reports it. The decorator passes no cancellation token of its own, and
    /// disposing it neither cancels nor disposes an inner operation already started.
    /// </remarks>
    public Task ExecuteAsync(object? parameter) => RunAsync(parameter, awaitInner: true);

    private async Task RunAsync(object? parameter, bool awaitInner)
    {
        // The inner predicate may dispose the decorator.
        if (!CanExecute(parameter) || _disposed) return;
        var confirmed = await _confirm().ConfigureAwait(false);
        // A confirmation that resolves after disposal runs nothing (spec §8.4, ADR-0134).
        if (!confirmed || _disposed) return;
        if (awaitInner)
        {
            switch (_inner)
            {
                case IAsyncCommand asyncInner:
                    await asyncInner.ExecuteAsync(parameter).ConfigureAwait(false);
                    return;
                case ConfirmationDecoratorCommand nested:
                    await nested.ExecuteAsync(parameter).ConfigureAwait(false);
                    return;
            }
        }
        _inner.Execute(parameter);
    }

    private void EmitError(Exception error)
    {
        lock (_errorGate)
        {
            if (_disposed) return;
            _errors.OnNext(error);
        }
    }

    /// <summary>
    /// Makes the decorator inert, unsubscribes from the inner command's
    /// <c>CanExecuteChanged</c>, and completes the <see cref="Errors"/> channel
    /// (spec §8.4, ADR-0134). Idempotent. A pending confirmation that resolves later
    /// runs no inner command and emits nothing; the inner command stays owned by its
    /// creator.
    /// </summary>
    public void Dispose()
    {
        lock (_errorGate)
        {
            if (_disposed) return;
            _disposed = true;
            _inner.CanExecuteChanged -= _innerHandler;
        }

        ExceptionDispatchInfo? firstError = null;
        try { _errors.OnCompleted(); }
        catch (Exception error) { firstError = ExceptionDispatchInfo.Capture(error); }
        try { _errors.Dispose(); }
        catch (Exception error) { firstError ??= ExceptionDispatchInfo.Capture(error); }
        firstError?.Throw();
    }
}
