namespace VMx.Messages;

/// <summary>
/// Base contract for every message sent through the VMx hub.
/// See spec/03-messages.md §IMessage shape.
/// </summary>
public interface IMessage
{
    /// <summary>Human-readable sender identifier, typically equal to Sender.Name.</summary>
    string SenderName { get; }

    /// <summary>Runtime sender instance without compile-time type info.</summary>
    object SenderObject { get; }
}
