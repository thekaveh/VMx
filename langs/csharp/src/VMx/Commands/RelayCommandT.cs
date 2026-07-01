using System.Collections.Immutable;
using System.Reactive;
using System.Reactive.Disposables;
using System.Windows.Input;

namespace VMx.Commands;

/// <summary>
/// Parameterized <see cref="ICommand"/> implementation whose task and predicate
/// receive a typed parameter.
///
/// Spec: spec/04-commands.md (same rules as <see cref="RelayCommand"/>, parameterized by T).
/// - Parameter not assignable to T (including a <see langword="null"/> for a value-type
///   or non-nullable reference T) → CanExecute returns false and Execute is a no-op.
///   The command never fabricates a <c>default(T)</c> to hand to the user's delegate.
/// - Predicate null → CanExecute returns true for any T-typed parameter.
/// - Task null → Execute is a no-op (no exception raised).
/// - Execute is GATED on CanExecute: if CanExecute(parameter) returns false, Execute
///   returns immediately without invoking the task.
/// - Predicate that throws → treated as false (exception does NOT propagate).
/// - Task that throws → exception propagates to the caller of Execute.
/// - Trigger emissions fire CanExecuteChanged.
/// - Disposed commands are inert: CanExecute returns false and Execute is a no-op.
/// - Builder is IMMUTABLE (BLD-001): every setter returns a NEW builder instance via `with`.
/// - Triggers are additive: multiple .Triggers(...) calls combine into the trigger set.
/// </summary>
/// <typeparam name="T">The parameter type threaded through Execute and CanExecute.</typeparam>
public sealed class RelayCommand<T> : ICommand, IDisposable
{
    private readonly Action<T>? _task;
    private readonly Func<T, bool>? _predicate;
    private readonly CompositeDisposable _triggerSubscriptions = new();
    private bool _disposed;

    private RelayCommand(Action<T>? task, Func<T, bool>? predicate, IReadOnlyList<IObservable<Unit>> triggers)
    {
        _task = task;
        _predicate = predicate;
        foreach (var t in triggers)
            _triggerSubscriptions.Add(t.Subscribe(_ => CanExecuteChanged?.Invoke(this, EventArgs.Empty)));
    }

    /// <inheritdoc/>
    public event EventHandler? CanExecuteChanged;

    /// <summary>
    /// Returns false when <paramref name="parameter"/> is not a T (a non-T command
    /// cannot act on a foreign parameter). Otherwise returns true when no predicate
    /// is configured, or the predicate result for the typed parameter. A predicate
    /// that throws is treated as false (defensive).
    /// </summary>
    public bool CanExecute(object? parameter)
    {
        if (_disposed) return false;
        if (parameter is not T typed) return false;
        if (_predicate is null) return true;
        try { return _predicate(typed); }
        catch { return false; }
    }

    /// <summary>
    /// Invokes the configured task with the typed parameter if (and only if) CanExecute
    /// returns true. If <paramref name="parameter"/> is not a T, or no task was configured,
    /// Execute is a no-op.
    /// </summary>
    public void Execute(object? parameter)
    {
        if (_disposed) return;
        if (parameter is not T typed) return;
        if (!CanExecute(parameter)) return;
        _task?.Invoke(typed);
    }

    /// <summary>Disposes all trigger subscriptions.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
        _triggerSubscriptions.Dispose();
    }

    /// <summary>Returns a new immutable builder for <see cref="RelayCommand{T}"/>.</summary>
    public static ICommandBuilder<T> Builder() => new BuilderImpl();

    // -----------------------------------------------------------------------
    // Immutable nested record builder (BLD-001).
    // -----------------------------------------------------------------------

    private sealed record BuilderImpl(
        Action<T>? Task = null,
        Func<T, bool>? Predicate = null,
        ImmutableList<IObservable<Unit>>? Triggers = null) : ICommandBuilder<T>
    {
        ICommandBuilder<T> ICommandBuilder<T>.Task(Action<T> task) =>
            this with { Task = task };

        ICommandBuilder<T> ICommandBuilder<T>.Predicate(Func<T, bool> predicate) =>
            this with { Predicate = predicate };

        ICommandBuilder<T> ICommandBuilder<T>.Triggers(IObservable<Unit> trigger) =>
            this with { Triggers = (Triggers ?? ImmutableList<IObservable<Unit>>.Empty).Add(trigger) };

        ICommand ICommandBuilder<T>.Build() =>
            new RelayCommand<T>(
                Task,
                Predicate,
                (IReadOnlyList<IObservable<Unit>>?)Triggers ?? Array.Empty<IObservable<Unit>>());
    }
}
