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
