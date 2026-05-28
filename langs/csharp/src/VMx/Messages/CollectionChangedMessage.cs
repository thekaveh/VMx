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
    string SenderName,
    NotifyCollectionChangedAction Action,
    IReadOnlyList<T> NewItems,
    IReadOnlyList<T> OldItems,
    int Index) : ICollectionChangedMessage<T>
{
    /// <inheritdoc/>
    public object SenderObject => Sender;

#pragma warning disable CA1000 // Static factories on generic type: intentional — mirrors PropertyChangedMessage<T> pattern
    /// <summary>Factory for Add.</summary>
    public static CollectionChangedMessage<T> ForAdd(object sender, string senderName, T item, int index)
        => new(sender, senderName, NotifyCollectionChangedAction.Add,
               new[] { item }, Array.Empty<T>(), index);

    /// <summary>Factory for Remove.</summary>
    public static CollectionChangedMessage<T> ForRemove(object sender, string senderName, T item, int index)
        => new(sender, senderName, NotifyCollectionChangedAction.Remove,
               Array.Empty<T>(), new[] { item }, index);

    /// <summary>Factory for Replace.</summary>
    public static CollectionChangedMessage<T> ForReplace(object sender, string senderName, T newItem, T oldItem, int index)
        => new(sender, senderName, NotifyCollectionChangedAction.Replace,
               new[] { newItem }, new[] { oldItem }, index);

    /// <summary>Factory for Reset.</summary>
    public static CollectionChangedMessage<T> ForReset(object sender, string senderName)
        => new(sender, senderName, NotifyCollectionChangedAction.Reset,
               Array.Empty<T>(), Array.Empty<T>(), -1);
#pragma warning restore CA1000
}
