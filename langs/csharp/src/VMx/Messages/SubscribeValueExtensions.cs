using System.Reactive.Linq;
using VMx.Components;
using VMx.Internal;

namespace VMx.Messages;

/// <summary>
/// Imperative selected-state subscriptions for component viewmodels.
/// </summary>
public static class SubscribeValueExtensions
{
    /// <summary>
    /// Observes selected state from one fixed component and invokes
    /// <paramref name="callback"/> when that selected value changes.
    /// </summary>
    /// <typeparam name="TSource">The concrete component type.</typeparam>
    /// <typeparam name="TValue">The selected value type.</typeparam>
    /// <param name="source">The fixed component to observe.</param>
    /// <param name="selector">Selects the current value from <paramref name="source"/>.</param>
    /// <param name="callback">Receives the current and previous selected values.</param>
    /// <param name="equalityComparer">
    /// Optional selected-value comparer; defaults to <see cref="EqualityComparer{T}.Default"/>.
    /// </param>
    /// <param name="fireImmediately">
    /// Whether to invoke <paramref name="callback"/> synchronously with the initial value.
    /// </param>
    /// <returns>The hub subscription owned by the caller.</returns>
    public static IDisposable SubscribeValue<TSource, TValue>(
        this TSource source,
        Func<TSource, TValue> selector,
        Action<TValue, TValue> callback,
        IEqualityComparer<TValue>? equalityComparer = null,
        bool fireImmediately = false)
        where TSource : class, IComponentVM
    {
        ThrowHelper.ThrowIfNull(source, nameof(source));
        ThrowHelper.ThrowIfNull(selector, nameof(selector));
        ThrowHelper.ThrowIfNull(callback, nameof(callback));

        var comparer = equalityComparer ?? EqualityComparer<TValue>.Default;
        var current = selector(source);
        if (fireImmediately) callback(current, current);

        return source.Hub.Messages.Subscribe(message =>
        {
            if (message is not IPropertyChangedMessage<object> propertyChanged ||
                !ReferenceEquals(propertyChanged.SenderObject, source))
            {
                return;
            }

            try
            {
                var next = selector(source);
                if (comparer.Equals(current, next)) return;

                var previous = current;
                current = next;
                callback(next, previous);
            }
            catch
            {
                // Preserve HUB-007 isolation without allowing Rx to auto-detach
                // this observer after a delivery-time consumer failure.
            }
        });
    }
}
