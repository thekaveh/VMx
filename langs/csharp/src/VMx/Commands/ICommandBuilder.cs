using System.Reactive;

namespace VMx.Commands;

/// <summary>
/// Fluent immutable builder for a non-parameterized <see cref="System.Windows.Input.ICommand"/>.
/// Each setter returns a NEW builder instance (BLD-001 — immutability).
/// </summary>
public interface ICommandBuilder
{
    /// <summary>Sets the action to invoke on Execute. Returns a new builder.</summary>
    ICommandBuilder Task(Action task);

    /// <summary>Sets the predicate that gates CanExecute. Returns a new builder.</summary>
    ICommandBuilder Predicate(Func<bool> predicate);

    /// <summary>
    /// Adds a trigger observable. Multiple calls are additive — all observables
    /// combine into the trigger set (spec/04-commands.md §Builder semantics).
    /// Returns a new builder.
    /// </summary>
    ICommandBuilder Triggers(IObservable<Unit> trigger);

    /// <summary>Builds the command. Succeeds even with no task, predicate, or triggers.</summary>
    System.Windows.Input.ICommand Build();
}

/// <summary>
/// Fluent immutable builder for a parameterized <see cref="System.Windows.Input.ICommand"/>
/// whose task and predicate accept a typed parameter.
/// </summary>
/// <typeparam name="T">The parameter type passed to Execute and CanExecute.</typeparam>
public interface ICommandBuilder<T>
{
    /// <summary>Sets the parameterized action to invoke on Execute. Returns a new builder.</summary>
    ICommandBuilder<T> Task(Action<T> task);

    /// <summary>Sets the parameterized predicate that gates CanExecute. Returns a new builder.</summary>
    ICommandBuilder<T> Predicate(Func<T, bool> predicate);

    /// <summary>
    /// Adds a trigger observable. Multiple calls are additive.
    /// Returns a new builder.
    /// </summary>
    ICommandBuilder<T> Triggers(IObservable<Unit> trigger);

    /// <summary>Builds the command. Succeeds even with no task, predicate, or triggers.</summary>
    System.Windows.Input.ICommand Build();
}

/// <summary>
/// Built-in immutable builder for <see cref="RelayCommand"/>. Its concrete
/// <see cref="Build"/> return preserves access to relay-specific capabilities while
/// explicit interface members retain the existing <see cref="ICommandBuilder"/> contract.
/// </summary>
public sealed class RelayCommandBuilder : ICommandBuilder
{
    private readonly Action? _task;
    private readonly Func<bool>? _predicate;
    private readonly IReadOnlyList<IObservable<Unit>> _triggers;

    /// <summary>Creates an empty builder.</summary>
    public RelayCommandBuilder()
        : this(null, null, Array.Empty<IObservable<Unit>>())
    {
    }

    private RelayCommandBuilder(
        Action? task,
        Func<bool>? predicate,
        IReadOnlyList<IObservable<Unit>> triggers)
    {
        _task = task;
        _predicate = predicate;
        _triggers = triggers;
    }

    /// <summary>Sets the action and returns a new builder.</summary>
    public RelayCommandBuilder Task(Action task) => new(task, _predicate, _triggers);

    /// <summary>Sets the predicate and returns a new builder.</summary>
    public RelayCommandBuilder Predicate(Func<bool> predicate) => new(_task, predicate, _triggers);

    /// <summary>Adds one trigger and returns a new builder.</summary>
    public RelayCommandBuilder Triggers(IObservable<Unit> trigger) =>
        new(_task, _predicate, _triggers.Append(trigger).ToArray());

    /// <summary>Builds a concrete relay command.</summary>
    public RelayCommand Build() => new(_task, _predicate, _triggers);

    ICommandBuilder ICommandBuilder.Task(Action task) => Task(task);
    ICommandBuilder ICommandBuilder.Predicate(Func<bool> predicate) => Predicate(predicate);
    ICommandBuilder ICommandBuilder.Triggers(IObservable<Unit> trigger) => Triggers(trigger);
    System.Windows.Input.ICommand ICommandBuilder.Build() => Build();
}

/// <summary>
/// Built-in immutable builder for <see cref="RelayCommand{T}"/> with a concrete
/// build result and source-compatible explicit <see cref="ICommandBuilder{T}"/> members.
/// </summary>
public sealed class RelayCommandBuilder<T> : ICommandBuilder<T>
{
    private readonly Action<T>? _task;
    private readonly Func<T, bool>? _predicate;
    private readonly IReadOnlyList<IObservable<Unit>> _triggers;

    /// <summary>Creates an empty builder.</summary>
    public RelayCommandBuilder()
        : this(null, null, Array.Empty<IObservable<Unit>>())
    {
    }

    private RelayCommandBuilder(
        Action<T>? task,
        Func<T, bool>? predicate,
        IReadOnlyList<IObservable<Unit>> triggers)
    {
        _task = task;
        _predicate = predicate;
        _triggers = triggers;
    }

    /// <summary>Sets the action and returns a new builder.</summary>
    public RelayCommandBuilder<T> Task(Action<T> task) => new(task, _predicate, _triggers);

    /// <summary>Sets the predicate and returns a new builder.</summary>
    public RelayCommandBuilder<T> Predicate(Func<T, bool> predicate) => new(_task, predicate, _triggers);

    /// <summary>Adds one trigger and returns a new builder.</summary>
    public RelayCommandBuilder<T> Triggers(IObservable<Unit> trigger) =>
        new(_task, _predicate, _triggers.Append(trigger).ToArray());

    /// <summary>Builds a concrete parameterized relay command.</summary>
    public RelayCommand<T> Build() => new(_task, _predicate, _triggers);

    ICommandBuilder<T> ICommandBuilder<T>.Task(Action<T> task) => Task(task);
    ICommandBuilder<T> ICommandBuilder<T>.Predicate(Func<T, bool> predicate) => Predicate(predicate);
    ICommandBuilder<T> ICommandBuilder<T>.Triggers(IObservable<Unit> trigger) => Triggers(trigger);
    System.Windows.Input.ICommand ICommandBuilder<T>.Build() => Build();
}
