using System.Windows.Input;

namespace NotesShowcase.Views.Adapter;

/// <summary>
/// CommandBridge (scenario §7.1, plan §4.a): wraps a VMx <see cref="ICommand"/>
/// (typically <see cref="VMx.Commands.RelayCommand"/> or <see cref="VMx.Commands.RelayCommand{T}"/>)
/// and forwards <see cref="ICommand.CanExecute"/> / <see cref="ICommand.Execute"/>.
///
/// <para>
/// VMx's <see cref="VMx.Commands.RelayCommand"/> already implements
/// <see cref="ICommand"/>, so the showcase binds commands directly. This bridge
/// is the documented integration seam (scenario §7.3) a host MAY route command
/// bindings through when it wants command lifetime and re-raise behaviour owned
/// by the adapter layer rather than the VM; it is exercised by the adapter unit
/// tests as a reference pattern.
/// </para>
///
/// <para>
/// <see cref="ICommand.CanExecuteChanged"/> on the source is forwarded
/// 1:1: every event raised by the source triggers an event on the bridge.
/// Disposing the bridge unsubscribes from the source so its handler list
/// no longer references the bridge.
/// </para>
/// </summary>
public sealed class RelayCommandBridge : ICommand, IDisposable
{
    private readonly ICommand _source;
    private readonly EventHandler _sourceHandler;
    private bool _disposed;

    /// <inheritdoc/>
    public event EventHandler? CanExecuteChanged;

    /// <summary>
    /// Creates a bridge that wraps <paramref name="source"/> and re-raises its
    /// <see cref="ICommand.CanExecuteChanged"/> notifications.
    /// </summary>
    /// <param name="source">The wrapped command. Required.</param>
    /// <exception cref="ArgumentNullException">If <paramref name="source"/> is null.</exception>
    public RelayCommandBridge(ICommand source)
    {
        ArgumentNullException.ThrowIfNull(source);
        _source = source;
        _sourceHandler = (_, e) => CanExecuteChanged?.Invoke(this, e);
        _source.CanExecuteChanged += _sourceHandler;
    }

    /// <inheritdoc/>
    public bool CanExecute(object? parameter) => _source.CanExecute(parameter);

    /// <inheritdoc/>
    public void Execute(object? parameter) => _source.Execute(parameter);

    /// <summary>Unsubscribes from the source's <see cref="ICommand.CanExecuteChanged"/>. Idempotent.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _source.CanExecuteChanged -= _sourceHandler;
    }
}
