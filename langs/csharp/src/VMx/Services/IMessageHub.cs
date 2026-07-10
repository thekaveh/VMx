using VMx.Messages;

namespace VMx.Services;

/// <summary>
/// Hot pub/sub stream for IMessage events. See spec/03-messages.md.
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

/// <summary>
/// Additive capability implemented by hubs that support lossless message
/// transactions. Existing custom <see cref="IMessageHub"/> implementations
/// remain source-compatible.
/// </summary>
public interface ITransactionalMessageHub : IMessageHub
{
    /// <summary>
    /// Executes a synchronous transaction whose messages are delivered after
    /// the outermost transaction exits.
    /// </summary>
    /// <param name="transaction">The state mutation to execute.</param>
    void Batch(Action transaction);
}
