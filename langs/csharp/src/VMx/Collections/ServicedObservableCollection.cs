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

    // PropertyChanged handlers. ObservableCollection raises Count and Item[]
    // before OnCollectionChanged, so during a mutation their first failure
    // waits here until OnCollectionChanged has raised CollectionChanged and
    // sent the hub message (#1430). Outside a mutation, such as a subclass
    // raising its own property, OnPropertyChanged rethrows at once.
    private PropertyChangedEventHandler? _propertyChanged;
    private ExceptionDispatchInfo? _propertyFailure;
    private int _mutationDepth;

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

    /// <inheritdoc/>
    /// <remarks>
    /// Every handler receives each change once, even when an earlier handler
    /// throws. A throwing handler skips neither <see cref="CollectionChanged"/>
    /// nor the hub message of the mutation; the mutation rethrows the first
    /// failure after the hub send (#1430).
    /// </remarks>
    protected override event PropertyChangedEventHandler? PropertyChanged
    {
        add
        {
            lock (_localHandlers) _propertyChanged += value;
        }
        remove
        {
            lock (_localHandlers) _propertyChanged -= value;
        }
    }

    /// <inheritdoc/>
    /// <remarks>
    /// Every handler runs even when an earlier handler throws. Outside a
    /// mutation the first failure is rethrown when the handlers have run.
    /// During a mutation it is rethrown by the mutation after the hub send.
    /// </remarks>
    protected override void OnPropertyChanged(PropertyChangedEventArgs e)
    {
        PropertyChangedEventHandler? handler;
        lock (_localHandlers) handler = _propertyChanged;
        if (_mutationDepth == 0)
        {
            FanOut.Raise(handler, h => h(this, e))?.Throw();
            return;
        }

        // A nested mutation from a handler keeps its own failure: the outer
        // failure is set aside while the handlers run.
        ExceptionDispatchInfo? outerFailure = _propertyFailure;
        _propertyFailure = null;
        ExceptionDispatchInfo? failure = FanOut.Raise(handler, h => h(this, e));
        _propertyFailure = outerFailure ?? failure;
    }

    // Closes one mutation. When the outermost mutation ends, a held-back
    // PropertyChanged failure that no OnCollectionChanged rethrew is returned.
    private ExceptionDispatchInfo? EndMutation()
    {
        if (--_mutationDepth > 0) return null;
        ExceptionDispatchInfo? leftover = _propertyFailure;
        _propertyFailure = null;
        return leftover;
    }

    // Raises Count, Item[] and one Reset as one mutation (ReplaceAll).
    private protected void RaiseResetNotifications()
    {
        _mutationDepth++;
        ExceptionDispatchInfo? leftover;
        try
        {
            OnPropertyChanged(new PropertyChangedEventArgs(nameof(Count)));
            OnPropertyChanged(new PropertyChangedEventArgs("Item[]"));
            OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
        }
        finally
        {
            leftover = EndMutation();
        }
        leftover?.Throw();
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

        RaiseResetNotifications();
    }

    /// <inheritdoc/>
    protected override void InsertItem(int index, T item)
    {
        _mutationDepth++;
        ExceptionDispatchInfo? leftover;
        try
        {
            base.InsertItem(index, item);
        }
        finally
        {
            leftover = EndMutation();
        }
        leftover?.Throw();
    }

    /// <inheritdoc/>
    protected override void RemoveItem(int index)
    {
        _mutationDepth++;
        ExceptionDispatchInfo? leftover;
        try
        {
            base.RemoveItem(index);
        }
        finally
        {
            leftover = EndMutation();
        }
        leftover?.Throw();
    }

    /// <inheritdoc/>
    protected override void SetItem(int index, T item)
    {
        _mutationDepth++;
        ExceptionDispatchInfo? leftover;
        try
        {
            base.SetItem(index, item);
        }
        finally
        {
            leftover = EndMutation();
        }
        leftover?.Throw();
    }

    /// <inheritdoc/>
    protected override void ClearItems()
    {
        if (Count == 0) return;
        _mutationDepth++;
        ExceptionDispatchInfo? leftover;
        try
        {
            base.ClearItems();
        }
        finally
        {
            leftover = EndMutation();
        }
        leftover?.Throw();
    }

    /// <inheritdoc/>
    protected override void MoveItem(int oldIndex, int newIndex)
    {
        if ((uint)oldIndex >= (uint)Count)
            throw new ArgumentOutOfRangeException(nameof(oldIndex));
        if ((uint)newIndex >= (uint)Count)
            throw new ArgumentOutOfRangeException(nameof(newIndex));
        if (oldIndex == newIndex) return;

        _mutationDepth++;
        ExceptionDispatchInfo? leftover;
        try
        {
            base.MoveItem(oldIndex, newIndex);
        }
        finally
        {
            leftover = EndMutation();
        }
        leftover?.Throw();
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
        //    A PropertyChanged failure of this mutation came first, so it
        //    takes precedence.
        ExceptionDispatchInfo? propertyFailure = _propertyFailure;
        _propertyFailure = null;
        ExceptionDispatchInfo? outerFailure = _deliveryFailure;
        _deliveryFailure = null;
        NotifyCollectionChangedEventHandler[] wrappers;
        lock (_localHandlers)
        {
            wrappers = new NotifyCollectionChangedEventHandler[_localHandlers.Count];
            for (int i = 0; i < wrappers.Length; i++) wrappers[i] = _localHandlers[i].Wrapper;
        }
        foreach (NotifyCollectionChangedEventHandler wrapper in wrappers) wrapper(this, e);
        ExceptionDispatchInfo? firstFailure = propertyFailure ?? _deliveryFailure;
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
