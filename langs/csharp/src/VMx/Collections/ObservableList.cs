using System.Collections;
using System.Collections.Specialized;
using System.ComponentModel;
using System.Runtime.ExceptionServices;
using VMx.Internal;

namespace VMx.Collections;

// ── Event-arg types ───────────────────────────────────────────────────────────

/// <summary>Event arguments for <see cref="ObservableList{T}.ItemAdded"/>.</summary>
public sealed class ItemAddedEventArgs<T> : EventArgs
{
    /// <summary>The item that was added.</summary>
    public T Item { get; }

    /// <summary>The index at which the item was inserted.</summary>
    public int Index { get; }

    internal ItemAddedEventArgs(T item, int index) { Item = item; Index = index; }
}

/// <summary>Event arguments for <see cref="ObservableList{T}.ItemRemoved"/>.</summary>
public sealed class ItemRemovedEventArgs<T> : EventArgs
{
    /// <summary>The item that was removed.</summary>
    public T Item { get; }

    /// <summary>The index of the item before it was removed.</summary>
    public int Index { get; }

    internal ItemRemovedEventArgs(T item, int index) { Item = item; Index = index; }
}

/// <summary>Event arguments for <see cref="ObservableList{T}.ItemReplaced"/>.</summary>
public sealed class ItemReplacedEventArgs<T> : EventArgs
{
    /// <summary>The new item at <see cref="Index"/>.</summary>
    public T NewItem { get; }

    /// <summary>The old item that was replaced.</summary>
    public T OldItem { get; }

    /// <summary>The index of the replaced item.</summary>
    public int Index { get; }

    internal ItemReplacedEventArgs(T newItem, T oldItem, int index)
    {
        NewItem = newItem;
        OldItem = oldItem;
        Index = index;
    }
}

// ── ObservableList<T> ─────────────────────────────────────────────────────────

/// <summary>
/// An observable list that raises granular per-mutation events:
/// <see cref="ItemAdded"/>, <see cref="ItemRemoved"/>, <see cref="ItemReplaced"/>,
/// and <see cref="Reset"/>.
///
/// Also implements <see cref="INotifyCollectionChanged"/> and
/// <see cref="INotifyPropertyChanged"/> for platform-binding compatibility
/// (spec §3.4 and ADR-0026 §3 rule 2).
///
/// <para>
/// The <see cref="Count"/> property change notification fires <b>after</b> the
/// granular event on every mutation that changes Count (add/remove; not replace).
/// This ordering is normative per spec §3.3 and ADR-0026.
/// </para>
///
/// <para>
/// A throwing handler does not stop the notification sequence: every handler
/// of each event runs, <see cref="CollectionChanged"/> and the <c>Count</c>
/// notification still follow, and the first failure is rethrown to the caller
/// after the last step (spec §3.3).
/// </para>
///
/// <para>
/// Call <see cref="BatchUpdate"/> to suppress granular events; a single
/// <see cref="Reset"/> fires when the returned <see cref="IDisposable"/> is
/// disposed (ref-counted for nested scopes).
/// </para>
///
/// See spec/21-collections.md §3 and ADR-0026.
/// </summary>
/// <typeparam name="T">Element type.</typeparam>
public sealed class ObservableList<T> :
    IReadOnlyList<T>,
    INotifyCollectionChanged,
    INotifyPropertyChanged
{
    private readonly List<T> _items = [];
    private int _batchDepth;
    private bool _mutatedInBatch;
    private int _countAtBatchStart;

    // ── Granular events ───────────────────────────────────────────────────────

    /// <summary>Fires when an item is added. Payload: item and insertion index.</summary>
    public event EventHandler<ItemAddedEventArgs<T>>? ItemAdded;

    /// <summary>Fires when an item is removed. Payload: item and index before removal.</summary>
    public event EventHandler<ItemRemovedEventArgs<T>>? ItemRemoved;

    /// <summary>Fires when an item is replaced. Payload: new item, old item, and index.</summary>
    public event EventHandler<ItemReplacedEventArgs<T>>? ItemReplaced;

    /// <summary>Fires on <see cref="Clear"/> or when a batch with mutations completes.</summary>
    public event EventHandler? Reset;

    // ── Platform compatibility ────────────────────────────────────────────────

    /// <inheritdoc/>
    public event NotifyCollectionChangedEventHandler? CollectionChanged;

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged;

    // ── IReadOnlyList<T> ──────────────────────────────────────────────────────

    /// <inheritdoc/>
    public int Count => _items.Count;

    /// <inheritdoc/>
    public T this[int index] => _items[index];

    /// <inheritdoc/>
    public IEnumerator<T> GetEnumerator() => _items.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => _items.GetEnumerator();

    // ── Mutations ─────────────────────────────────────────────────────────────

    /// <summary>Append <paramref name="item"/> to the end of the list.</summary>
    public void Add(T item)
    {
        int index = _items.Count;
        _items.Add(item);
        OnAdded(item, index);
    }

    /// <summary>Insert <paramref name="item"/> at <paramref name="index"/>.</summary>
    public void Insert(int index, T item)
    {
        _items.Insert(index, item);
        OnAdded(item, index);
    }

    /// <summary>
    /// Remove the first occurrence of <paramref name="item"/>.
    /// Returns <see langword="true"/> if found and removed.
    /// </summary>
    public bool Remove(T item)
    {
        int idx = _items.IndexOf(item);
        if (idx < 0) return false;
        _items.RemoveAt(idx);
        OnRemoved(item, idx);
        return true;
    }

    /// <summary>Remove the item at <paramref name="index"/>.</summary>
    public void RemoveAt(int index)
    {
        T item = _items[index];
        _items.RemoveAt(index);
        OnRemoved(item, index);
    }

    /// <summary>Replace the item at <paramref name="index"/> with <paramref name="newItem"/>.</summary>
    public void Replace(int index, T newItem)
    {
        T oldItem = _items[index];
        _items[index] = newItem;
        OnReplaced(newItem, oldItem, index);
    }

    /// <summary>
    /// Replace the complete contents with a snapshot of <paramref name="items"/>.
    /// Every replacement except empty-to-empty emits one Reset; Count follows
    /// only when the cardinality changes.
    /// </summary>
    public void ReplaceAll(IEnumerable<T> items)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(items);
#else
        if (items is null) throw new ArgumentNullException(nameof(items));
#endif
        var snapshot = new List<T>(items);
        int oldCount = _items.Count;
        if (oldCount == 0 && snapshot.Count == 0) return;

        _items.Clear();
        _items.AddRange(snapshot);
        OnReset(countChanged: oldCount != snapshot.Count);
    }

    /// <summary>Remove all items and emit <see cref="Reset"/> (and <c>Count</c> when it changed).</summary>
    public void Clear()
    {
        bool countChanged = _items.Count > 0;
        _items.Clear();
        // Clearing an empty list is a no-op: emit neither Reset nor Count
        // (ADR-0037 §2.2, mirroring the empty-batch precedent).
        // spec/21 §3.3: PropertyChanged("Count") fires after every mutation
        // that changes Count. Inside a batch the batch-exit path emits it.
        if (countChanged)
            OnReset(countChanged: true);
    }

    // ── Batch update ──────────────────────────────────────────────────────────

    /// <summary>
    /// Begin a batch-update scope. Granular events are suppressed until the
    /// returned token is disposed. On dispose of the outermost scope (ref-counted),
    /// a single <see cref="Reset"/> fires if any mutations occurred.
    /// </summary>
    public IDisposable BatchUpdate() => new BatchToken(this);

    private sealed class BatchToken : IDisposable
    {
        private readonly ObservableList<T> _owner;
        private bool _disposed;

        internal BatchToken(ObservableList<T> owner)
        {
            _owner = owner;
            if (_owner._batchDepth == 0)
                _owner._countAtBatchStart = _owner._items.Count;
            _owner._batchDepth++;
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _owner._batchDepth--;
            if (_owner._batchDepth == 0 && _owner._mutatedInBatch)
            {
                int finalCount = _owner._items.Count;
                _owner._mutatedInBatch = false;
                // Emit Count notification only if count actually changed (spec §3.3).
                _owner.RaiseReset(countChanged: finalCount != _owner._countAtBatchStart);
            }
        }
    }

    // ── Internal helpers ──────────────────────────────────────────────────────

    // Each step runs every handler of its event, even when one throws. A
    // failure skips neither CollectionChanged nor the Count notification of the
    // committed change; the first failure is rethrown after the last step
    // (spec/21 §3.3).
    private void OnAdded(T item, int index)
    {
        if (_batchDepth > 0) { _mutatedInBatch = true; return; }

        ExceptionDispatchInfo? firstFailure =
            FanOut.Raise(ItemAdded, handler => handler(this, new ItemAddedEventArgs<T>(item, index)));
        Notify(
            ref firstFailure,
            new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Add, item, index),
            countChanged: true);
        firstFailure?.Throw();
    }

    private void OnRemoved(T item, int index)
    {
        if (_batchDepth > 0) { _mutatedInBatch = true; return; }

        ExceptionDispatchInfo? firstFailure =
            FanOut.Raise(ItemRemoved, handler => handler(this, new ItemRemovedEventArgs<T>(item, index)));
        Notify(
            ref firstFailure,
            new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Remove, item, index),
            countChanged: true);
        firstFailure?.Throw();
    }

    private void OnReplaced(T newItem, T oldItem, int index)
    {
        if (_batchDepth > 0) { _mutatedInBatch = true; return; }

        ExceptionDispatchInfo? firstFailure = FanOut.Raise(
            ItemReplaced,
            handler => handler(this, new ItemReplacedEventArgs<T>(newItem, oldItem, index)));
        // Count does not change on replace — no PropertyChanged("Count")
        Notify(
            ref firstFailure,
            new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Replace, newItem, oldItem, index),
            countChanged: false);
        firstFailure?.Throw();
    }

    private void OnReset(bool countChanged)
    {
        if (_batchDepth > 0) { _mutatedInBatch = true; return; }
        RaiseReset(countChanged);
    }

    private void RaiseReset(bool countChanged)
    {
        ExceptionDispatchInfo? firstFailure = FanOut.Raise(Reset, handler => handler(this, EventArgs.Empty));
        Notify(
            ref firstFailure,
            new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset),
            countChanged);
        firstFailure?.Throw();
    }

    // Raises CollectionChanged, then PropertyChanged("Count") when the count
    // changed, and keeps the first failure in firstFailure.
    private void Notify(ref ExceptionDispatchInfo? firstFailure, NotifyCollectionChangedEventArgs args, bool countChanged)
    {
        ExceptionDispatchInfo? collectionFailure =
            FanOut.Raise(CollectionChanged, handler => handler(this, args));
        firstFailure ??= collectionFailure;
        if (!countChanged) return;
        ExceptionDispatchInfo? countFailure = FanOut.Raise(
            PropertyChanged, handler => handler(this, new PropertyChangedEventArgs(nameof(Count))));
        firstFailure ??= countFailure;
    }
}
