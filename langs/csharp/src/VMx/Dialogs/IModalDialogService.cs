namespace VMx.Dialogs;

/// <summary>
/// Optional dialog-service capability for arbitrary VM-backed modals.
/// </summary>
public interface IModalDialogService : IDialogService
{
    /// <summary>Presents a VM-backed modal and resolves with its result.</summary>
    Task<T> Present<T>(IModalVM<T> modal, CancellationToken cancellationToken = default);
}
