using VMx.Lifecycle;

namespace VMx.Messages;

/// <summary>
/// Default <see cref="IConstructionStatusChangedMessage"/> implementation.
/// Records give us value-equality and an auto-generated ToString().
/// </summary>
/// <param name="Sender">Runtime sender instance.</param>
/// <param name="SenderName">Human-readable sender identifier.</param>
/// <param name="Status">The new <see cref="ConstructionStatus"/> after the transition.</param>
public sealed record ConstructionStatusChangedMessage(
    object Sender,
    string SenderName,
    ConstructionStatus Status) : IConstructionStatusChangedMessage
{
    /// <inheritdoc/>
    public object SenderObject => Sender;

    /// <summary>Factory method; equivalent to the primary constructor.</summary>
    public static ConstructionStatusChangedMessage Create(
        object sender, string senderName, ConstructionStatus status)
        => new(sender, senderName, status);
}
