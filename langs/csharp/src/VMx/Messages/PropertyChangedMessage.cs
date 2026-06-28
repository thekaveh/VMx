namespace VMx.Messages;

/// <summary>
/// Default <see cref="IPropertyChangedMessage{TSender}"/> implementation.
/// Records give us value-equality and an auto-generated ToString().
/// </summary>
/// <typeparam name="TSender">Compile-time type of the sender. Must be non-null.</typeparam>
/// <param name="Sender">Strongly-typed sender instance.</param>
/// <param name="SenderName">Human-readable sender identifier.</param>
/// <param name="PropertyName">Name of the property whose value changed.</param>
public sealed record PropertyChangedMessage<TSender>(
    TSender Sender,
    string SenderName,
    string PropertyName) : IPropertyChangedMessage<TSender>
    where TSender : notnull
{
    /// <inheritdoc/>
    public object SenderObject => Sender!;

    /// <summary>Factory method; equivalent to the primary constructor.</summary>
    public static PropertyChangedMessage<TSender> Create(
        TSender sender, string senderName, string propertyName)
        => new(sender, senderName, propertyName);
}
