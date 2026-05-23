using VMx.Lifecycle;

namespace VMx.Messages;

/// <summary>
/// Emitted on every legal ConstructionStatus transition.
/// See spec/03-messages.md §ConstructionStatusChangedMessage and spec/02-lifecycle.md.
/// </summary>
public interface IConstructionStatusChangedMessage : IMessage
{
    /// <summary>The new <see cref="ConstructionStatus"/> after the transition.</summary>
    ConstructionStatus Status { get; }
}
