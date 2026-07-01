namespace VMx.Dialogs;

/// <summary>
/// Small base implementation for result-bearing VM-backed modals.
/// </summary>
/// <typeparam name="T">Modal result type.</typeparam>
public sealed class ModalVM<T> : IModalVM<T>
{
    private readonly TaskCompletionSource<T> _completion =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private bool _isDismissed;

    /// <summary>Creates a modal with the result used for cancellation/disposal.</summary>
    public ModalVM(T cancellationResult)
    {
        CancellationResult = cancellationResult;
    }

    /// <inheritdoc/>
    public T CancellationResult { get; }

    /// <inheritdoc/>
    public T? Result { get; private set; }

    /// <inheritdoc/>
    public bool IsDismissed => _isDismissed;

    /// <inheritdoc/>
    public Task<T> Completion => _completion.Task;

    /// <inheritdoc/>
    public void Dismiss(T result)
    {
        if (_isDismissed) return;
        Result = result;
        _isDismissed = true;
        _completion.TrySetResult(result);
    }

    /// <summary>Cancel the modal with <see cref="CancellationResult"/>. Idempotent.</summary>
    public void Dispose()
    {
        Dismiss(CancellationResult);
    }
}
