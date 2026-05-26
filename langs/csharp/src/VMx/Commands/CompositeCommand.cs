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
    private bool _disposed;

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

    /// <inheritdoc/>
    public bool CanExecute(object? parameter)
    {
        foreach (var c in _inner)
            if (c.CanExecute(parameter))
                return true;
        return false;
    }

    /// <inheritdoc/>
    public void Execute(object? parameter)
    {
        foreach (var c in _inner)
            if (c.CanExecute(parameter))
                c.Execute(parameter);
    }

    /// <summary>Unsubscribes from inner <c>CanExecuteChanged</c> events.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        for (var i = 0; i < _inner.Count; i++)
            _inner[i].CanExecuteChanged -= _innerHandlers[i];
    }
}
