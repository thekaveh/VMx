namespace VMx.Messages;

/// <summary>
/// Strongly-typed sender variant of <see cref="IMessage"/>.
/// </summary>
/// <typeparam name="TSender">Compile-time type of the sender.</typeparam>
public interface IMessage<out TSender> : IMessage
{
    /// <summary>Strongly-typed sender instance.</summary>
    TSender Sender { get; }
}
