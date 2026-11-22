using VMx.Components;

namespace VMx.Messages;

/// <summary>
/// The canonical sender identity that the chapter 03 §7 hub subscription helpers
/// match (spec/03-messages.md §7, ADR-0233). A forwarding decorator sends no message
/// of its own: the wrapped VM is the sender of each message the decorator causes
/// (ADR-0221), and nested decorators resolve to the same innermost VM (ADR-0124).
/// </summary>
internal static class SenderIdentity
{
    /// <summary>
    /// Returns the canonical ownership identity of <paramref name="sender"/>, or the
    /// sender itself when it is not a VMx component. Each helper calls this once,
    /// when it subscribes.
    /// </summary>
    internal static object Of(object sender) =>
        sender is IComponentVM vm ? vm.GetOwnershipIdentity() : sender;
}
