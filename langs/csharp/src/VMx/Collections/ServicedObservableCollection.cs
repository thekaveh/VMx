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
///
/// See spec/21-collections.md §2 and ADR-0024.
/// </summary>
/// <typeparam name="T">Element type.</typeparam>
public class ServicedObservableCollection<T> : ObservableCollection<T>
{
    private readonly IMessageHub? _hub;

    /// <summary>
    /// Human-readable name used as <c>SenderName</c> in published messages.
    /// </summary>
    public string Name { get; }

    /// <summary>
    /// Initializes a new instance, optionally wiring it to <paramref name="hub"/>.
    /// </summary>
    /// <param name="name">Identifier used in hub messages. Defaults to the type name.</param>
    /// <param name="hub">Optional hub. Pass <c>null</c> for standalone (no publication) mode.</param>
    public ServicedObservableCollection(string? name = null, IMessageHub? hub = null)
    {
        Name = name ?? nameof(ServicedObservableCollection<T>);
        _hub = hub;
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
                    this, Name,
                    (T)e.NewItems![0]!,
                    e.NewStartingIndex),

            NotifyCollectionChangedAction.Remove =>
                CollectionChangedMessage<T>.ForRemove(
                    this, Name,
                    (T)e.OldItems![0]!,
                    e.OldStartingIndex),

            NotifyCollectionChangedAction.Replace =>
                CollectionChangedMessage<T>.ForReplace(
                    this, Name,
                    (T)e.NewItems![0]!,
                    (T)e.OldItems![0]!,
                    e.NewStartingIndex),

            _ /* Reset */ =>
                CollectionChangedMessage<T>.ForReset(this, Name),
        };

        _hub.Send(msg);
    }
}
