namespace VMx.Capabilities;

// Capability interfaces from spec/14-capabilities.md §Selection.
// Opt-in; not implemented by default by any core VM type.

/// <summary>Capability: the implementer can be selected.</summary>
public interface ISelectable
{
    /// <summary>Returns true when <see cref="Select"/> is valid to call.</summary>
    bool CanSelect();

    /// <summary>Performs the selection action.</summary>
    void Select();
}

/// <summary>Capability: the implementer can be deselected.</summary>
public interface IDeselectable
{
    /// <summary>Returns true when <see cref="Deselect"/> is valid to call.</summary>
    bool CanDeselect();

    /// <summary>Performs the deselection action.</summary>
    void Deselect();
}

/// <summary>Capability: the implementer's selection state can be toggled.</summary>
public interface ISelectionTogglable
{
    /// <summary>Returns true when <see cref="ToggleSelection"/> is valid to call.</summary>
    bool CanToggleSelection();

    /// <summary>Toggles the implementer's selection state.</summary>
    void ToggleSelection();
}
