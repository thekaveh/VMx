namespace VMx.Capabilities;

// Capability interfaces from spec/14-capabilities.md §Dialog / form.

/// <summary>Capability: the implementer can be closed.</summary>
public interface IClosable
{
    /// <summary>Returns true when <see cref="Close"/> is valid to call.</summary>
    bool CanClose();

    /// <summary>Performs the close action.</summary>
    void Close();
}

/// <summary>Capability: the implementer can be approved.</summary>
public interface IApprovable
{
    /// <summary>Returns true when <see cref="Approve"/> is valid to call.</summary>
    bool CanApprove();

    /// <summary>Performs the approve action.</summary>
    void Approve();
}

/// <summary>Capability: the implementer can be canceled.</summary>
public interface ICancelable
{
    /// <summary>Returns true when <see cref="Cancel"/> is valid to call.</summary>
    bool CanCancel();

    /// <summary>Performs the cancel action.</summary>
    void Cancel();
}
