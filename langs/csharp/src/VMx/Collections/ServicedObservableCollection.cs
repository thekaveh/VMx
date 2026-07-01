using System.Collections.ObjectModel;
using System.Collections.Specialized;
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
/// See spec/21-collections.md §2 and ADR-0024.
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

    /// <inheritdoc/>
    protected override void OnCollectionChanged(NotifyCollectionChangedEventArgs e)
    {
        // 1. Raise the standard local event first.
        base.OnCollectionChanged(e);

        // 2. Publish to hub (if present).
        if (_hub is null) return;

        // Move is part of the inherited ObservableCollection<T> API but is
        // NOT a CollectionMutationAction in the spec (chapter 21). The local
        // CollectionChanged event still fires for Move subscribers; we just
        // do not synthesise a hub message — silently mapping Move to Reset
        // would lose positional information.
        if (e.Action == NotifyCollectionChangedAction.Move) return;

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

            NotifyCollectionChangedAction.Reset =>
                CollectionChangedMessage<T>.ForReset(this),

            _ => throw new InvalidOperationException(
                $"Unexpected NotifyCollectionChangedAction: {e.Action}"),
        };

        _hub.Send(msg);
    }
}
