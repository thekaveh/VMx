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
    private int _disposed;

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

    private bool IsDisposed => Volatile.Read(ref _disposed) != 0;

    /// <inheritdoc/>
    public bool CanExecute(object? parameter)
    {
        if (IsDisposed || !_inner.CanExecute(parameter)) return false;
        if (_extraPredicate is null) return !IsDisposed;
        bool allowed;
        try { allowed = _extraPredicate(); }
        catch { return false; }
        // The extra predicate may dispose the decorator.
        return allowed && !IsDisposed;
    }

    /// <inheritdoc/>
    public void Execute(object? parameter)
    {
        if (!CanExecute(parameter)) return;
        _preExecute?.Invoke();
        try
        {
            // The pre-action may dispose the decorator: skip the inner command but
            // keep the admitted pre/post pair balanced (spec §8.4, ADR-0134).
            if (!IsDisposed) _inner.Execute(parameter);
        }
        finally
        {
            // postExecute runs whether or not the inner threw, so that a
            // "busy" flag set in preExecute always gets cleared.
            _postExecute?.Invoke();
        }
    }

    /// <summary>
    /// Makes the decorator inert and unsubscribes from the inner command's
    /// <c>CanExecuteChanged</c> (spec §8.4, ADR-0134). Idempotent. The inner command
    /// stays owned by its creator.
    /// </summary>
    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        _inner.CanExecuteChanged -= _innerHandler;
    }
}
