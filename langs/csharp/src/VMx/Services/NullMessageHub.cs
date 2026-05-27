using System.Reactive.Linq;
using VMx.Messages;

namespace VMx.Services;

/// <summary>
/// Null-object variant of <see cref="IMessageHub"/>. Every operation is a
/// safe no-op; <see cref="Messages"/> is the empty observable. Stateless and
/// safe to share via <see cref="Instance"/>. See spec/03-messages.md
/// §"Null variant" and ADR-0017.
/// </summary>
public sealed class NullMessageHub : IMessageHub
{
    /// <summary>Shared singleton instance (the hub holds no state).</summary>
    public static NullMessageHub Instance { get; } = new();

    private NullMessageHub() { }

    /// <inheritdoc/>
    public IObservable<IMessage> Messages { get; } = Observable.Empty<IMessage>();

    /// <inheritdoc/>
    public void Send<TMessage>(TMessage message) where TMessage : IMessage
    {
        // intentional no-op per ADR-0017
    }
}
