using System.Collections.Specialized;

namespace VMx.Messages;

/// <summary>
/// Default <see cref="ICollectionChangedMessage{T}"/> implementation.
/// Published by <see cref="VMx.Collections.ServicedObservableCollection{T}"/> to the hub.
/// See spec/21-collections.md §2 and ADR-0024.
/// </summary>
/// <typeparam name="T">Element type of the collection.</typeparam>
public sealed record CollectionChangedMessage<T>(
    object Sender,
    NotifyCollectionChangedAction Action,
    IReadOnlyList<T> NewItems,
    IReadOnlyList<T> OldItems,
    int Index) : ICollectionChangedMessage<T>
{
    /// <inheritdoc/>
    public object SenderObject => Sender;

    /// <inheritdoc/>
    /// <remarks>Derived from the sender's runtime type name; no separate name field per spec §2.4.</remarks>
    public string SenderName => Sender.GetType().Name;

    /// <summary>Factory for Add.</summary>
    public static CollectionChangedMessage<T> ForAdd(object sender, T item, int index)
        => new(sender, NotifyCollectionChangedAction.Add,
               new[] { item }, Array.Empty<T>(), index);

    /// <summary>Factory for Remove.</summary>
    public static CollectionChangedMessage<T> ForRemove(object sender, T item, int index)
        => new(sender, NotifyCollectionChangedAction.Remove,
               Array.Empty<T>(), new[] { item }, index);

    /// <summary>Factory for Replace.</summary>
    public static CollectionChangedMessage<T> ForReplace(object sender, T newItem, T oldItem, int index)
        => new(sender, NotifyCollectionChangedAction.Replace,
               new[] { newItem }, new[] { oldItem }, index);

    /// <summary>Factory for Reset.</summary>
    public static CollectionChangedMessage<T> ForReset(object sender)
        => new(sender, NotifyCollectionChangedAction.Reset,
               Array.Empty<T>(), Array.Empty<T>(), -1);
}
