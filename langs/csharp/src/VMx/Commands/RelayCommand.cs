using System.Collections.Immutable;
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
/// - Builder is IMMUTABLE (BLD-001): every setter returns a NEW builder instance via `with`.
/// - Triggers are additive: multiple .Triggers(...) calls combine into the trigger set.
/// </summary>
public sealed class RelayCommand : ICommand, IDisposable
{
    private readonly Action? _task;
    private readonly Func<bool>? _predicate;
    private readonly CompositeDisposable _triggerSubscriptions = new();

    private RelayCommand(Action? task, Func<bool>? predicate, IReadOnlyList<IObservable<Unit>> triggers)
    {
        _task = task;
        _predicate = predicate;
        foreach (var t in triggers)
            _triggerSubscriptions.Add(t.Subscribe(_ => CanExecuteChanged?.Invoke(this, EventArgs.Empty)));
    }

    /// <inheritdoc/>
    public event EventHandler? CanExecuteChanged;

    /// <summary>
    /// Returns true if no predicate is configured; otherwise returns the predicate's result.
    /// If the predicate throws, returns false (defensive — exception does not propagate).
    /// </summary>
    public bool CanExecute(object? parameter)
    {
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
        if (!CanExecute(parameter)) return;
        _task?.Invoke();
    }

    /// <summary>Disposes all trigger subscriptions.</summary>
    public void Dispose() => _triggerSubscriptions.Dispose();

    /// <summary>Returns a new immutable builder for <see cref="RelayCommand"/>.</summary>
    public static ICommandBuilder Builder() => new BuilderImpl();

    // -----------------------------------------------------------------------
    // Immutable nested record builder (BLD-001).
    // Each setter returns a new BuilderImpl via `with` — the original is unchanged.
    // -----------------------------------------------------------------------

    private sealed record BuilderImpl(
        Action? Task = null,
        Func<bool>? Predicate = null,
        ImmutableList<IObservable<Unit>>? Triggers = null) : ICommandBuilder
    {
        ICommandBuilder ICommandBuilder.Task(Action task) =>
            this with { Task = task };

        ICommandBuilder ICommandBuilder.Predicate(Func<bool> predicate) =>
            this with { Predicate = predicate };

        ICommandBuilder ICommandBuilder.Triggers(IObservable<Unit> trigger) =>
            this with { Triggers = (Triggers ?? ImmutableList<IObservable<Unit>>.Empty).Add(trigger) };

        ICommand ICommandBuilder.Build() =>
            new RelayCommand(
                Task,
                Predicate,
                (IReadOnlyList<IObservable<Unit>>?)Triggers ?? Array.Empty<IObservable<Unit>>());
    }
}
