using System.Collections.Specialized;

namespace VMx.Messages;

/// <summary>
/// Default <see cref="ICollectionChangedMessage{T}"/> implementation.
/// Published to the hub by <see cref="VMx.Collections.ServicedObservableCollection{T}"/>
/// and, with the container as sender, by every
/// <see cref="VMx.Composites.CompositeVMBase{VM}"/> and
/// <see cref="VMx.Groups.GroupVMBase{VM}"/> after each local collection change.
/// See spec/21-collections.md §2, spec/01-concepts.md §1.4, ADR-0024, and ADR-0142.
/// </summary>
/// <typeparam name="T">Element type of the collection.</typeparam>
public sealed record CollectionChangedMessage<T>(
    object Sender,
    NotifyCollectionChangedAction Action,
    IReadOnlyList<T> NewItems,
    IReadOnlyList<T> OldItems,
    int Index) : ICollectionChangedMessage<T>
{
    /// <summary>Source position, or -1 when the action has no source.</summary>
    public int OldIndex { get; init; } = -1;

    /// <summary>Destination position, or -1 when the action has no destination.</summary>
    public int NewIndex { get; init; } = -1;

    /// <inheritdoc/>
    public object SenderObject => Sender;

    /// <inheritdoc/>
    /// <remarks>Derived from the sender's runtime type name; no separate name field per spec §2.4.</remarks>
    public string SenderName => Sender.GetType().Name;

    /// <summary>Factory for Add.</summary>
    public static CollectionChangedMessage<T> ForAdd(object sender, T item, int index)
        => new(sender, NotifyCollectionChangedAction.Add,
               new[] { item }, Array.Empty<T>(), index)
        {
            NewIndex = index,
        };

    /// <summary>Factory for Remove.</summary>
    public static CollectionChangedMessage<T> ForRemove(object sender, T item, int index)
        => new(sender, NotifyCollectionChangedAction.Remove,
               Array.Empty<T>(), new[] { item }, index)
        {
            OldIndex = index,
        };

    /// <summary>Factory for Replace.</summary>
    public static CollectionChangedMessage<T> ForReplace(object sender, T newItem, T oldItem, int index)
        => new(sender, NotifyCollectionChangedAction.Replace,
               new[] { newItem }, new[] { oldItem }, index)
        {
            OldIndex = index,
            NewIndex = index,
        };

    /// <summary>Factory for Move.</summary>
    public static CollectionChangedMessage<T> ForMove(object sender, T item, int oldIndex, int newIndex)
        => new(sender, NotifyCollectionChangedAction.Move,
               new[] { item }, new[] { item }, newIndex)
        {
            OldIndex = oldIndex,
            NewIndex = newIndex,
        };

    /// <summary>Factory for Reset.</summary>
    public static CollectionChangedMessage<T> ForReset(object sender)
        => new(sender, NotifyCollectionChangedAction.Reset,
               Array.Empty<T>(), Array.Empty<T>(), -1);

    /// <summary>
    /// Maps one single-item local collection-change event to the hub message
    /// with the same action, positions, and items.
    /// </summary>
    internal static CollectionChangedMessage<T> From(
        object sender,
        NotifyCollectionChangedEventArgs e)
        => e.Action switch
        {
            NotifyCollectionChangedAction.Add =>
                ForAdd(sender, (T)e.NewItems![0]!, e.NewStartingIndex),

            NotifyCollectionChangedAction.Remove =>
                ForRemove(sender, (T)e.OldItems![0]!, e.OldStartingIndex),

            NotifyCollectionChangedAction.Replace =>
                ForReplace(sender, (T)e.NewItems![0]!, (T)e.OldItems![0]!, e.NewStartingIndex),

            NotifyCollectionChangedAction.Move =>
                ForMove(sender, (T)e.NewItems![0]!, e.OldStartingIndex, e.NewStartingIndex),

            NotifyCollectionChangedAction.Reset => ForReset(sender),

            _ => throw new InvalidOperationException(
                $"Unexpected NotifyCollectionChangedAction: {e.Action}"),
        };
}
