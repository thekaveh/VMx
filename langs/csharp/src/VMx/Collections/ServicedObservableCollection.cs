using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;
using VMx.Messages;
using VMx.Services;

namespace VMx.Collections;

/// <summary>
/// An <see cref="ObservableCollection{T}"/> that optionally publishes
/// <see cref="CollectionChangedMessage{T}"/> events to an <see cref="IMessageHub"/>
/// in addition to the standard local <see cref="ObservableCollection{T}.CollectionChanged"/> event.
///
/// When no hub is injected the class behaves exactly like a plain
/// <see cref="ObservableCollection{T}"/> — no errors, no overhead.
/// Ownership stays with the caller: removing, replacing, or clearing an item
/// does not call <c>Dispose</c> or any VM lifecycle method on that item.
///
/// See spec/21-collections.md §2, ADR-0024, and ADR-0096.
/// </summary>
/// <typeparam name="T">Element type.</typeparam>
public class ServicedObservableCollection<T> : ObservableCollection<T>
{
    private readonly IMessageHub? _hub;

    /// <summary>
    /// Initializes a new instance, optionally wiring it to <paramref name="hub"/>.
    /// </summary>
    /// <param name="hub">Optional hub. Pass <c>null</c> for standalone (no publication) mode.</param>
    public ServicedObservableCollection(IMessageHub? hub = null)
    {
        _hub = hub;
    }

    /// <summary>Replaces the item at <paramref name="index"/>.</summary>
    /// <param name="index">Zero-based index of the item to replace.</param>
    /// <param name="item">Replacement item.</param>
    public void Replace(int index, T item) => this[index] = item;

    /// <summary>
    /// Replaces all items from a materialized snapshot and emits one Reset.
    /// Empty-to-empty is a no-op.
    /// </summary>
    /// <param name="items">Items that will form the complete new contents.</param>
    public void ReplaceAll(IEnumerable<T> items)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(items);
#else
        if (items is null) throw new ArgumentNullException(nameof(items));
#endif

        T[] snapshot = items.ToArray();
        if (Count == 0 && snapshot.Length == 0) return;

        CheckReentrancy();
        Items.Clear();
        foreach (T item in snapshot) Items.Add(item);

        OnPropertyChanged(new PropertyChangedEventArgs(nameof(Count)));
        OnPropertyChanged(new PropertyChangedEventArgs("Item[]"));
        OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
    }

    /// <inheritdoc/>
    protected override void ClearItems()
    {
        if (Count == 0) return;
        base.ClearItems();
    }

    /// <inheritdoc/>
    protected override void MoveItem(int oldIndex, int newIndex)
    {
        if ((uint)oldIndex >= (uint)Count)
            throw new ArgumentOutOfRangeException(nameof(oldIndex));
        if ((uint)newIndex >= (uint)Count)
            throw new ArgumentOutOfRangeException(nameof(newIndex));
        if (oldIndex == newIndex) return;

        base.MoveItem(oldIndex, newIndex);
    }

    /// <inheritdoc/>
    protected override void OnCollectionChanged(NotifyCollectionChangedEventArgs e)
    {
        // 1. Raise the standard local event first.
        base.OnCollectionChanged(e);

        // 2. Publish to hub (if present).
        if (_hub is null) return;

        CollectionChangedMessage<T> msg = e.Action switch
        {
            NotifyCollectionChangedAction.Add =>
                CollectionChangedMessage<T>.ForAdd(
                    this,
                    (T)e.NewItems![0]!,
                    e.NewStartingIndex),

            NotifyCollectionChangedAction.Remove =>
                CollectionChangedMessage<T>.ForRemove(
                    this,
                    (T)e.OldItems![0]!,
                    e.OldStartingIndex),

            NotifyCollectionChangedAction.Replace =>
                CollectionChangedMessage<T>.ForReplace(
                    this,
                    (T)e.NewItems![0]!,
                    (T)e.OldItems![0]!,
                    e.NewStartingIndex),

            NotifyCollectionChangedAction.Move =>
                CollectionChangedMessage<T>.ForMove(
                    this,
                    (T)e.NewItems![0]!,
                    e.OldStartingIndex,
                    e.NewStartingIndex),

            NotifyCollectionChangedAction.Reset =>
                CollectionChangedMessage<T>.ForReset(this),

            _ => throw new InvalidOperationException(
                $"Unexpected NotifyCollectionChangedAction: {e.Action}"),
        };

        _hub.Send(msg);
    }
}
