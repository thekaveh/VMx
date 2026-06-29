using System.Reactive.Linq;
using VMx.Internal;
using VMx.Messages;

namespace VMx.Services;

/// <summary>
/// Ergonomic typed helpers over <see cref="IMessageHub"/> (VMX-017).
/// </summary>
public static class MessageHubExtensions
{
    /// <summary>
    /// Returns the stream of <see cref="IPropertyChangedMessage{TSender}"/> events
    /// published to <paramref name="hub"/> by <paramref name="sender"/> for the
    /// property named <paramref name="propertyName"/>.
    ///
    /// <para>
    /// Replaces the hand-wired
    /// <c>hub.Messages.OfType&lt;PropertyChangedMessage&lt;…&gt;&gt;().Where(m =&gt; ReferenceEquals(m.Sender, x) &amp;&amp; m.PropertyName == "P")</c>
    /// filter that otherwise gets copy-pasted into every cross-VM binding. The
    /// covariant <see cref="IPropertyChangedMessage{TSender}"/> match captures
    /// messages regardless of the concrete sender generic argument; sender
    /// identity is compared by reference.
    /// </para>
    /// </summary>
    /// <param name="hub">The hub whose message stream to observe.</param>
    /// <param name="sender">The sender instance to match by reference.</param>
    /// <param name="propertyName">The property name to match (ordinal).</param>
    public static IObservable<IPropertyChangedMessage<object>> WhenPropertyChanged(
        this IMessageHub hub,
        object sender,
        string propertyName)
    {
        ThrowHelper.ThrowIfNull(hub, nameof(hub));
        ThrowHelper.ThrowIfNull(sender, nameof(sender));
        ThrowHelper.ThrowIfNull(propertyName, nameof(propertyName));

        return hub.Messages
            .OfType<IPropertyChangedMessage<object>>()
            .Where(m => ReferenceEquals(m.SenderObject, sender)
                && string.Equals(m.PropertyName, propertyName, StringComparison.Ordinal));
    }
}
