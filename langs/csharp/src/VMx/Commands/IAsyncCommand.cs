using System.Windows.Input;

namespace VMx.Commands;

/// <summary>
/// An <see cref="ICommand"/> whose work is asynchronous and cancellable.
///
/// Spec: spec/04-commands.md §11 (async command cancellation), ADR-0056.
///
/// The contract extends the synchronous <see cref="ICommand"/> with an awaitable
/// <see cref="ExecuteAsync"/> entry-point that flows a <see cref="CancellationToken"/>
/// into the command's task and a <see cref="Cancel"/> method that cancels the
/// in-flight execution. Cancellation is non-throwing to the caller by default —
/// the awaited <see cref="ExecuteAsync"/> completes normally on cancel rather than
/// surfacing an <see cref="OperationCanceledException"/> — mirroring the dialog
/// cancellation contract (spec/19-dialogs.md §6, DIA-007). While an execution is
/// in flight <see cref="ICommand.CanExecute"/> returns <c>false</c>, so the command
/// cannot double-run.
/// </summary>
public interface IAsyncCommand : ICommand
{
    /// <summary>True while an execution is in flight; false when idle.</summary>
    bool IsExecuting { get; }

    /// <summary>
    /// Runs the command's async task if (and only if) <see cref="ICommand.CanExecute"/>
    /// returns true, flowing <paramref name="cancellationToken"/> into the task. By
    /// default a cancellation (via <see cref="Cancel"/> or the supplied token)
    /// completes the returned task normally rather than throwing.
    /// </summary>
    Task ExecuteAsync(object? parameter = null, CancellationToken cancellationToken = default);

    /// <summary>Requests cancellation of the in-flight execution; a no-op when idle.</summary>
    void Cancel();
}
