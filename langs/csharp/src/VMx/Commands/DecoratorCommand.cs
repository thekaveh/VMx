using System.Windows.Input;

namespace VMx.Commands;

/// <summary>
/// Wraps a single inner <see cref="ICommand"/> with optional pre/post actions and
/// an optional extra can-execute predicate. See spec/04-commands.md §Decorators
/// and ADR-0012.
/// </summary>
public sealed class DecoratorCommand : ICommand, IDisposable
{
    private readonly ICommand _inner;
    private readonly Action? _preExecute;
    private readonly Action? _postExecute;
    private readonly Func<bool>? _extraPredicate;
    private readonly EventHandler _innerHandler;
    private bool _disposed;

    /// <summary>Creates a new <see cref="DecoratorCommand"/>.</summary>
    public DecoratorCommand(
        ICommand inner,
        Action? preExecute = null,
        Action? postExecute = null,
        Func<bool>? extraPredicate = null)
    {
        _inner = inner ?? throw new ArgumentNullException(nameof(inner));
        _preExecute = preExecute;
        _postExecute = postExecute;
        _extraPredicate = extraPredicate;
        _innerHandler = (sender, args) => CanExecuteChanged?.Invoke(this, args);
        _inner.CanExecuteChanged += _innerHandler;
    }

    /// <inheritdoc/>
    public event EventHandler? CanExecuteChanged;

    /// <inheritdoc/>
    public bool CanExecute(object? parameter)
    {
        if (!_inner.CanExecute(parameter)) return false;
        if (_extraPredicate is null) return true;
        try { return _extraPredicate(); }
        catch { return false; }
    }

    /// <inheritdoc/>
    public void Execute(object? parameter)
    {
        if (!CanExecute(parameter)) return;
        _preExecute?.Invoke();
        _inner.Execute(parameter);
        _postExecute?.Invoke();
    }

    /// <summary>Unsubscribes from the inner command's <c>CanExecuteChanged</c>.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _inner.CanExecuteChanged -= _innerHandler;
    }
}
