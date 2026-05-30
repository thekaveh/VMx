using System.Windows.Input;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Pure presentation record for a single capability-derived action.
///
/// Used by <see cref="CapabilityActionsVM"/> to project a focused VM's
/// capability surface into a flat list of (label, command) tuples for the view.
/// See plan §3.a.5 and spec §14.4 (capability dispatch).
/// </summary>
public sealed record ActionVM(string Label, ICommand Command);
