using System.Reactive;
using System.Reactive.Disposables;
using System.Windows.Input;

namespace VMx.Commands;

/// <summary>
/// Non-parameterized <see cref="ICommand"/> implementation.
///
/// Spec: spec/04-commands.md
/// - Predicate null → CanExecute returns true unconditionally.
/// - Task null → Execute is a no-op (no exception raised).
/// - Execute is GATED on CanExecute: if CanExecute() returns false, Execute returns immediately
///   without invoking the task (matches fixture row "predicate-false").
/// - Predicate that throws → treated as false (exception does NOT propagate).
/// - Task that throws → exception propagates to the caller of Execute.
/// - Trigger emissions fire CanExecuteChanged.
/// - RaiseCanExecuteChanged emits one imperative re-evaluation notification.
/// - Disposed commands are inert: CanExecute returns false and Execute is a no-op.
/// - Builder is IMMUTABLE (BLD-001): every setter returns a NEW builder instance.
/// - Triggers are additive: multiple .Triggers(...) calls combine into the trigger set.
/// </summary>
public sealed class RelayCommand : ICommand, IDisposable
{
    private readonly Action? _task;
    private readonly Func<bool>? _predicate;
    private readonly CompositeDisposable _triggerSubscriptions = new();
    private bool _disposed;

    internal RelayCommand(Action? task, Func<bool>? predicate, IReadOnlyList<IObservable<Unit>> triggers)
    {
        _task = task;
        _predicate = predicate;
        foreach (var t in triggers)
            _triggerSubscriptions.Add(t.Subscribe(_ => RaiseCanExecuteChanged()));
    }

    /// <inheritdoc/>
    public event EventHandler? CanExecuteChanged;

    /// <summary>
    /// Notifies subscribers that <see cref="CanExecute"/> may have changed without
    /// evaluating the predicate or invoking the task. A no-op after disposal.
    /// </summary>
    public void RaiseCanExecuteChanged()
    {
        if (_disposed) return;
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>
    /// Returns true if no predicate is configured; otherwise returns the predicate's result.
    /// If the predicate throws, returns false (defensive — exception does not propagate).
    /// </summary>
    public bool CanExecute(object? parameter)
    {
        if (_disposed) return false;
        if (_predicate is null) return true;
        try { return _predicate(); }
        catch { return false; }
    }

    /// <summary>
    /// Invokes the configured task if (and only if) CanExecute() returns true.
    /// If no task was configured, Execute is a no-op.
    /// </summary>
    public void Execute(object? parameter)
    {
        if (_disposed) return;
        if (!CanExecute(parameter)) return;
        _task?.Invoke();
    }

    /// <summary>Disposes all trigger subscriptions.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
        _triggerSubscriptions.Dispose();
    }

    /// <summary>Returns a new immutable builder for <see cref="RelayCommand"/>.</summary>
    public static RelayCommandBuilder Builder() => new();
}
