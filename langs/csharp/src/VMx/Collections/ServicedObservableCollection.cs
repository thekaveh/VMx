using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;
using System.Reactive.Disposables;
using System.Runtime.ExceptionServices;
using VMx.Internal;
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
public class ServicedObservableCollection<T> : ObservableCollection<T>, IObservableMembershipSource<T>
{
    private readonly IMessageHub? _hub;

    // Each entry of a local handler is kept here with a wrapper that records
    // its failure, so a throwing entry does not stop the later ones (spec/03
    // §3.6, ADR-0191). OnCollectionChanged invokes the wrappers itself, never
    // through the base event, so ObservableCollection's reentrancy block never
    // applies and a handler may mutate the collection (spec/21 §2.13,
    // ADR-0214, #1343). The lock guards the list against a concurrent add and
    // remove.
    private readonly List<(Delegate Handler, NotifyCollectionChangedEventHandler Wrapper)> _localHandlers = [];
    private ExceptionDispatchInfo? _deliveryFailure;

    /// <summary>
    /// Initializes a new instance, optionally wiring it to <paramref name="hub"/>.
    /// </summary>
    /// <param name="hub">Optional hub. Pass <c>null</c> for standalone (no publication) mode.</param>
    public ServicedObservableCollection(IMessageHub? hub = null)
    {
        _hub = hub;
    }

    /// <inheritdoc/>
    /// <remarks>
    /// Every handler receives each change once, even when an earlier handler
    /// throws. The mutation then rethrows the first failure after the hub send
    /// (spec/03 §3.6, ADR-0171, ADR-0191). The event keeps its own handler
    /// list, so the base <see cref="ObservableCollection{T}"/> never blocks
    /// reentrancy. A <see cref="CollectionChanged"/> handler may mutate the
    /// collection while other handlers are attached; the nested mutation
    /// completes its own local and hub delivery first (spec/21 §2.13,
    /// ADR-0214, #1343).
    /// </remarks>
    public override event NotifyCollectionChangedEventHandler? CollectionChanged
    {
        add
        {
            if (value is null) return;
            lock (_localHandlers)
            {
                foreach (Delegate entry in value.GetInvocationList())
                {
                    var handler = (NotifyCollectionChangedEventHandler)entry;
                    NotifyCollectionChangedEventHandler wrapper = (sender, args) =>
                    {
                        try { handler(sender, args); }
                        catch (Exception error) { _deliveryFailure ??= ExceptionDispatchInfo.Capture(error); }
                    };
                    _localHandlers.Add((entry, wrapper));
                }
            }
        }
        remove
        {
            if (value is null) return;
            // Standard event semantics: remove the last run of entries that
            // equals the invocation list of value, if there is one.
            Delegate[] entries = value.GetInvocationList();
            lock (_localHandlers)
            {
                for (int start = _localHandlers.Count - entries.Length; start >= 0; start--)
                {
                    if (!RunMatches(start, entries)) continue;
                    _localHandlers.RemoveRange(start, entries.Length);
                    return;
                }
            }
        }
    }

    private bool RunMatches(int start, Delegate[] entries)
    {
        for (int i = 0; i < entries.Length; i++)
            if (!_localHandlers[start + i].Handler.Equals(entries[i])) return false;
        return true;
    }

    /// <inheritdoc/>
    public IReadOnlyList<T> Snapshot() => this.ToArray();

    /// <inheritdoc/>
    public IDisposable SubscribeMembership(Action callback)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(callback);
#else
        if (callback is null) throw new ArgumentNullException(nameof(callback));
#endif
        NotifyCollectionChangedEventHandler handler = (_, _) => callback();
        CollectionChanged += handler;
        return Disposable.Create(() => CollectionChanged -= handler);
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
    public virtual void ReplaceAll(IEnumerable<T> items)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(items);
#else
        if (items is null) throw new ArgumentNullException(nameof(items));
#endif

        T[] snapshot = items.ToArray();
        if (Count == 0 && snapshot.Length == 0) return;

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
        // 1. Raise the standard local event first. A throwing local handler
        //    stops neither the later handlers nor the hub message for the
        //    committed change: send it, then rethrow the first failure
        //    (spec/01 §1.4, spec/03 §3.6, ADR-0171, ADR-0191). A nested
        //    delivery keeps its own first failure. The handlers are invoked
        //    here, not through base.OnCollectionChanged, so no reentrancy
        //    block applies (ADR-0214).
        ExceptionDispatchInfo? outerFailure = _deliveryFailure;
        _deliveryFailure = null;
        NotifyCollectionChangedEventHandler[] wrappers;
        lock (_localHandlers)
        {
            wrappers = new NotifyCollectionChangedEventHandler[_localHandlers.Count];
            for (int i = 0; i < wrappers.Length; i++) wrappers[i] = _localHandlers[i].Wrapper;
        }
        foreach (NotifyCollectionChangedEventHandler wrapper in wrappers) wrapper(this, e);
        ExceptionDispatchInfo? firstFailure = _deliveryFailure;
        _deliveryFailure = outerFailure;

        // 2. Publish to hub (if present).
        if (_hub is not null)
        {
            FirstFailure.Capture(
                ref firstFailure,
                (Owner: this, Hub: _hub, Args: e),
                static state => state.Hub.Send(CollectionChangedMessage<T>.From(state.Owner, state.Args)));
        }
        firstFailure?.Throw();
    }
}
