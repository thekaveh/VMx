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
    private bool _disposed;

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

    /// <inheritdoc/>
    public bool CanExecute(object? parameter) => _inner.CanExecute(parameter);

    /// <inheritdoc/>
    /// <remarks>
    /// Synchronous <c>Execute</c> kicks off the confirmation flow and returns immediately.
    /// Use <see cref="ExecuteAsync"/> to await the full sequence.
    /// </remarks>
    public void Execute(object? parameter) => _ = ExecuteAsync(parameter);

    /// <summary>Awaits the confirm delegate, then invokes inner.Execute if accepted.</summary>
    public async Task ExecuteAsync(object? parameter)
    {
        if (!CanExecute(parameter)) return;
        var confirmed = await _confirm().ConfigureAwait(false);
        if (confirmed) _inner.Execute(parameter);
    }

    /// <summary>Unsubscribes from the inner command's <c>CanExecuteChanged</c>.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _inner.CanExecuteChanged -= _innerHandler;
    }
}
