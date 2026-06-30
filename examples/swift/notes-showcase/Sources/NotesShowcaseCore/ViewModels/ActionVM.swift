//
// ActionVM — pure presentation value for a single capability-derived action.
//
// Used by `CapabilityActionsVM` (Task 6) to project a focused VM's capability
// surface into a flat list of (label, command) tuples for the view.
// See spec/14-capabilities.md §4 (capability dispatch).
//
import VMx

/// Pure presentation struct for a single capability-derived action.
///
/// Holds a human-readable `label` and the `Command` to invoke when the
/// associated button / menu item is activated. Constructed by the owning
/// `CapabilityActionsVM` from the focused VM's capability methods.
public struct ActionVM {
    public let label: String
    public let command: Command

    public init(label: String, command: Command) {
        self.label = label
        self.command = command
    }
}
