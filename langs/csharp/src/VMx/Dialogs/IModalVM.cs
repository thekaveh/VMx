namespace VMx.Dialogs;

/// <summary>
/// Result-bearing VM-backed modal contract.
/// </summary>
/// <typeparam name="T">Modal result type.</typeparam>
public interface IModalVM<T> : IDisposable
{
    /// <summary>Result used when the modal is cancelled or disposed.</summary>
    T CancellationResult { get; }

    /// <summary>Dismissal result, or <c>default</c> before dismissal.</summary>
    T? Result { get; }

    /// <summary><c>true</c> after dismissal or disposal.</summary>
    bool IsDismissed { get; }

    /// <summary>Completes when the modal is dismissed.</summary>
    Task<T> Completion { get; }

    /// <summary>Complete the modal with <paramref name="result"/>. Idempotent.</summary>
    void Dismiss(T result);
}
