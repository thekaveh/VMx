using System.Windows.Input;

namespace VMx.Commands;

/// <summary>
/// Aggregates N inner <see cref="ICommand"/> instances. See spec/04-commands.md
/// §Decorators and ADR-0012.
///
/// <list type="bullet">
/// <item><c>CanExecute</c> returns true iff at least one inner returns true.</item>
/// <item><c>Execute</c> invokes every inner whose <c>CanExecute</c> is true.</item>
/// <item><c>CanExecuteChanged</c> fires when any inner's CanExecuteChanged fires.</item>
/// </list>
/// </summary>
public sealed class CompositeCommand : ICommand, IDisposable
{
    private readonly IReadOnlyList<ICommand> _inner;
    private readonly List<EventHandler> _innerHandlers = new();
    private int _disposed;

    /// <summary>Creates a new <see cref="CompositeCommand"/> over the given inner commands.</summary>
    public CompositeCommand(params ICommand[] inner)
        : this((IReadOnlyList<ICommand>)inner)
    {
    }

    /// <summary>Creates a new <see cref="CompositeCommand"/> over the given inner commands.</summary>
    public CompositeCommand(IReadOnlyList<ICommand> inner)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        foreach (var c in _inner)
        {
            EventHandler handler = (sender, args) => CanExecuteChanged?.Invoke(this, args);
            _innerHandlers.Add(handler);
            c.CanExecuteChanged += handler;
        }
    }

    /// <inheritdoc/>
    public event EventHandler? CanExecuteChanged;

    private bool IsDisposed => Volatile.Read(ref _disposed) != 0;

    /// <inheritdoc/>
    public bool CanExecute(object? parameter)
    {
        if (IsDisposed) return false;
        foreach (var c in _inner)
            if (c.CanExecute(parameter))
                return !IsDisposed;
        return false;
    }

    /// <inheritdoc/>
    public void Execute(object? parameter)
    {
        // A child's predicate or action may dispose the composite; no later
        // child runs once disposal is observed (spec §8.4, ADR-0134).
        foreach (var c in _inner)
        {
            if (IsDisposed) return;
            if (c.CanExecute(parameter) && !IsDisposed)
                c.Execute(parameter);
        }
    }

    /// <summary>
    /// Makes the composite inert and unsubscribes from inner <c>CanExecuteChanged</c>
    /// events (spec §8.4, ADR-0134). Idempotent. The inner commands stay owned by
    /// their creator.
    /// </summary>
    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        for (var i = 0; i < _inner.Count; i++)
            _inner[i].CanExecuteChanged -= _innerHandlers[i];
    }
}
