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
    /// path — either the confirm delegate faulting or the inner command throwing.
    /// <see cref="ICommand.Execute"/> is <c>void</c>, so it cannot propagate the
    /// failure across the async confirm gate the way <see cref="RelayCommand"/>'s
    /// task does; instead of swallowing it (a discarded faulted <see cref="Task"/>
    /// would otherwise surface only as an <c>UnobservedTaskException</c> at GC) the
    /// error is emitted here (VMX-009). The awaitable <see cref="ExecuteAsync"/>
    /// path keeps its throw behavior — await it directly to handle the error
    /// inline. Completes on <see cref="Dispose"/>.
    /// </summary>
    public IObservable<Exception> Errors => _errors.AsObservable();

    /// <inheritdoc/>
    public bool CanExecute(object? parameter) => _inner.CanExecute(parameter);

    /// <inheritdoc/>
    /// <remarks>
    /// Synchronous <c>Execute</c> kicks off the confirmation flow and returns immediately.
    /// A rejecting confirm delegate or a throwing inner command is routed to
    /// <see cref="Errors"/> rather than swallowed (VMX-009). Use
    /// <see cref="ExecuteAsync"/> to await the full sequence and observe the failure inline.
    /// </remarks>
    public void Execute(object? parameter) =>
        _ = ExecuteAsync(parameter).ContinueWith(
            t =>
            {
                EmitError(t.Exception!.GetBaseException());
            },
            CancellationToken.None,
            TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);

    /// <summary>Awaits the confirm delegate, then invokes inner.Execute if accepted.</summary>
    public async Task ExecuteAsync(object? parameter)
    {
        if (!CanExecute(parameter)) return;
        var confirmed = await _confirm().ConfigureAwait(false);
        if (confirmed) _inner.Execute(parameter);
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
    /// Unsubscribes from the inner command's <c>CanExecuteChanged</c> and completes
    /// the <see cref="Errors"/> channel. Idempotent.
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
