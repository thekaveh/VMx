using VMx.Messages;

namespace VMx.Services;

/// <summary>
/// Minimal interface for the message hub. Replaced by the full definition in Task 3.
/// </summary>
public interface IMessageHub
{
    /// <summary>Gets the observable stream of all messages published to this hub.</summary>
    IObservable<IMessage> Messages { get; }

    /// <summary>Publishes <paramref name="message"/> to all current subscribers.</summary>
    /// <typeparam name="TMessage">The concrete message type.</typeparam>
    /// <param name="message">The message to publish.</param>
    void Send<TMessage>(TMessage message) where TMessage : IMessage;
}
