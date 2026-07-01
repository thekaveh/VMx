namespace VMx.Dialogs;

/// <summary>Extension fallback for VM-backed modal presentation.</summary>
public static class DialogServiceModalExtensions
{
    /// <summary>
    /// Presents a VM-backed modal when the service implements
    /// <see cref="IModalDialogService"/>; otherwise dismisses with the modal's
    /// cancellation result.
    /// </summary>
    public static Task<T> Present<T>(
        this IDialogService dialogService,
        IModalVM<T> modal,
        CancellationToken cancellationToken = default)
    {
        if (dialogService is IModalDialogService modalDialogService)
            return modalDialogService.Present(modal, cancellationToken);

        modal.Dismiss(modal.CancellationResult);
        return Task.FromResult(modal.CancellationResult);
    }
}
