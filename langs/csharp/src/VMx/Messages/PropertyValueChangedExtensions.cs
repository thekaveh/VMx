using System.Linq.Expressions;
using System.Reactive.Linq;

namespace VMx.Messages;

/// <summary>
/// Convenience extension over <see cref="VMx.Services.IMessageHub"/> that returns an
/// <c>IObservable&lt;TProperty&gt;</c> of property values rather than the full
/// <see cref="PropertyChangedMessage{TSender}"/> envelope.
///
/// The helper filters the hub's message stream to matching
/// <see cref="PropertyChangedMessage{TSender}"/> instances and reads the property value
/// from the sender via the compiled getter (snapshot at delivery time).
///
/// This helper is informative-only (ADR-0032); the underlying <c>Messages</c> stream is
/// the conformance-tested contract.
/// </summary>
public static class PropertyValueChangedExtensions
{
    /// <summary>
    /// Returns an observable that emits the current value of
    /// <paramref name="propertyExpression"/> on <paramref name="source"/> every time a
    /// matching <see cref="PropertyChangedMessage{TSender}"/> arrives on the hub.
    /// </summary>
    /// <typeparam name="TSource">Type of the sender.</typeparam>
    /// <typeparam name="TProperty">Type of the property being observed.</typeparam>
    /// <param name="hub">The message hub to filter.</param>
    /// <param name="source">
    ///   The specific sender instance to watch.  Reference equality is used.
    /// </param>
    /// <param name="propertyExpression">
    ///   A simple member-access expression identifying the property, e.g.
    ///   <c>vm => vm.IsValid</c>.  The expression is compiled once per call;
    ///   all subscriptions to the returned observable share that compilation.
    /// </param>
    /// <returns>Cold observable; each subscription attaches a new filter to <c>hub.Messages</c>.</returns>
    public static IObservable<TProperty> PropertyValueChangedMessagesFor<TSource, TProperty>(
        this VMx.Services.IMessageHub hub,
        TSource source,
        Expression<Func<TSource, TProperty>> propertyExpression)
        where TSource : notnull
    {
        var propertyName = ExtractPropertyName(propertyExpression);
        var getter = propertyExpression.Compile();

        return hub.Messages
            .OfType<IPropertyChangedMessage<TSource>>()
            .Where(m => ReferenceEquals(m.Sender, source) && m.PropertyName == propertyName)
            .Select(_ => getter(source));
    }

    private static string ExtractPropertyName<TSource, TProperty>(
        Expression<Func<TSource, TProperty>> expression)
    {
        if (expression.Body is MemberExpression memberExpr)
            return memberExpr.Member.Name;

        throw new ArgumentException(
            $"Expression '{expression}' does not refer to a simple property member.",
            nameof(expression));
    }
}
