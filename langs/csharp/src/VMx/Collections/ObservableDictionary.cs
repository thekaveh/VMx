using System.Collections;
using System.Collections.Specialized;
using VMx.Messages;
using VMx.Services;

#pragma warning disable CA1711 // 'Dictionary' suffix: spec-mandated type name per spec/21-collections.md §4

namespace VMx.Collections;

// ── Event-arg types ───────────────────────────────────────────────────────────

/// <summary>Event arguments for <see cref="ObservableDictionary{TKey1,TKey2,TValue}.ItemAdded"/>.</summary>
public sealed class DictionaryItemAddedEventArgs<TKey1, TKey2, TValue> : EventArgs
{
    /// <summary>The first-dimension key.</summary>
    public TKey1 Key1 { get; }

    /// <summary>The second-dimension key.</summary>
    public TKey2 Key2 { get; }

    /// <summary>The value that was added.</summary>
    public TValue Value { get; }

    internal DictionaryItemAddedEventArgs(TKey1 key1, TKey2 key2, TValue value)
    {
        Key1 = key1;
        Key2 = key2;
        Value = value;
    }
}

/// <summary>Event arguments for <see cref="ObservableDictionary{TKey1,TKey2,TValue}.ItemRemoved"/>.</summary>
public sealed class DictionaryItemRemovedEventArgs<TKey1, TKey2, TValue> : EventArgs
{
    /// <summary>The first-dimension key.</summary>
    public TKey1 Key1 { get; }

    /// <summary>The second-dimension key.</summary>
    public TKey2 Key2 { get; }

    /// <summary>The value that was removed.</summary>
    public TValue Value { get; }

    internal DictionaryItemRemovedEventArgs(TKey1 key1, TKey2 key2, TValue value)
    {
        Key1 = key1;
        Key2 = key2;
        Value = value;
    }
}

/// <summary>Event arguments for <see cref="ObservableDictionary{TKey1,TKey2,TValue}.ItemReplaced"/>.</summary>
public sealed class DictionaryItemReplacedEventArgs<TKey1, TKey2, TValue> : EventArgs
{
    /// <summary>The first-dimension key.</summary>
    public TKey1 Key1 { get; }

    /// <summary>The second-dimension key.</summary>
    public TKey2 Key2 { get; }

    /// <summary>The new value at this key pair.</summary>
    public TValue NewValue { get; }

    /// <summary>The old value that was replaced.</summary>
    public TValue OldValue { get; }

    internal DictionaryItemReplacedEventArgs(TKey1 key1, TKey2 key2, TValue newValue, TValue oldValue)
    {
        Key1 = key1;
        Key2 = key2;
        NewValue = newValue;
        OldValue = oldValue;
    }
}

// ── ObservableDictionary<TKey1, TKey2, TValue> ────────────────────────────────

/// <summary>
/// A two-key observable dictionary that maintains distinct-key observable views
/// (<see cref="Keys1"/> and <see cref="Keys2"/>) and raises granular per-mutation events:
/// <see cref="ItemAdded"/>, <see cref="ItemRemoved"/>, <see cref="ItemReplaced"/>,
/// and <see cref="Reset"/>.
///
/// <para>
/// Entries are stored in insertion order. Enumeration yields
/// <see cref="KeyValuePair{TKey,TValue}"/> with a <c>(TKey1, TKey2)</c> composite key.
/// </para>
///
/// <para>
/// <see cref="Keys1"/> contains the distinct Key1 values present in the dictionary,
/// in insertion order of their first appearance. <see cref="Keys2"/> is the symmetric
/// view for Key2. Both are live <see cref="ObservableList{T}"/> views.
/// </para>
///
/// <para>
/// Null keys are not permitted; passing a null key raises
/// <see cref="ArgumentNullException"/>.
/// </para>
///
/// See spec/21-collections.md §4 and ADR-0025.
/// </summary>
/// <typeparam name="TKey1">First-dimension key type.</typeparam>
/// <typeparam name="TKey2">Second-dimension key type.</typeparam>
/// <typeparam name="TValue">Value type.</typeparam>
public sealed class ObservableDictionary<TKey1, TKey2, TValue> :
    IEnumerable<KeyValuePair<(TKey1, TKey2), TValue>>
    where TKey1 : notnull
    where TKey2 : notnull
{
    private readonly IMessageHub? _hub;

    // Insertion-ordered backing store: list of keys + dict for O(1) lookup.
    private readonly List<(TKey1, TKey2)> _keyOrder = [];
    private readonly Dictionary<(TKey1, TKey2), TValue> _data = [];

    // Distinct-key views (live ObservableLists).
    private readonly ObservableList<TKey1> _keys1 = new();
    private readonly ObservableList<TKey2> _keys2 = new();

    // Per-axis reference counts, so distinct-key view membership is maintained
    // in O(1) on each mutation instead of scanning _data / _keys1 / _keys2.
    private readonly Dictionary<TKey1, int> _key1Counts = [];
    private readonly Dictionary<TKey2, int> _key2Counts = [];

    /// <summary>
    /// Initializes a new instance, optionally wiring it to <paramref name="hub"/>.
    /// </summary>
    /// <param name="hub">Optional hub. Pass <c>null</c> for standalone (no publication) mode.</param>
    public ObservableDictionary(IMessageHub? hub = null)
    {
        _hub = hub;
    }

    // ── Granular events ───────────────────────────────────────────────────────

    /// <summary>Fires when an entry is added.</summary>
    public event EventHandler<DictionaryItemAddedEventArgs<TKey1, TKey2, TValue>>? ItemAdded;

    /// <summary>Fires when an entry is removed.</summary>
    public event EventHandler<DictionaryItemRemovedEventArgs<TKey1, TKey2, TValue>>? ItemRemoved;

    /// <summary>Fires when an existing entry's value is replaced.</summary>
    public event EventHandler<DictionaryItemReplacedEventArgs<TKey1, TKey2, TValue>>? ItemReplaced;

    /// <summary>Fires on <see cref="Clear"/>.</summary>
    public event EventHandler? Reset;

    /// <summary>Standard collection-changed event (Reset action on Clear; Add/Remove/Replace on mutations).</summary>
    public event NotifyCollectionChangedEventHandler? CollectionChanged;

    // ── Key-axis views ─────────────────────────────────────────────────────────

    /// <summary>
    /// Live observable view of distinct Key1 values present in the dictionary,
    /// in insertion order of their first appearance.
    /// </summary>
    public ObservableList<TKey1> Keys1 => _keys1;

    /// <summary>
    /// Live observable view of distinct Key2 values present in the dictionary,
    /// in insertion order of their first appearance.
    /// </summary>
    public ObservableList<TKey2> Keys2 => _keys2;

    // ── Count / indexer ────────────────────────────────────────────────────────

    /// <summary>Total number of entries.</summary>
    public int Count => _data.Count;

    /// <summary>
    /// Gets or sets the value at the given key pair.
    /// Get throws <see cref="KeyNotFoundException"/> when absent.
    /// Set inserts a new entry or replaces an existing one.
    /// </summary>
    public TValue this[TKey1 key1, TKey2 key2]
    {
        get
        {
            _ = key1 ?? throw new ArgumentNullException(nameof(key1));
            _ = key2 ?? throw new ArgumentNullException(nameof(key2));
            return _data[(key1, key2)];
        }
        set
        {
            _ = key1 ?? throw new ArgumentNullException(nameof(key1));
            _ = key2 ?? throw new ArgumentNullException(nameof(key2));
            if (_data.TryGetValue((key1, key2), out TValue? old))
            {
                _data[(key1, key2)] = value;
                OnReplaced(key1, key2, value, old);
            }
            else
            {
                InternalAdd(key1, key2, value);
            }
        }
    }

    // ── Mutations ──────────────────────────────────────────────────────────────

    /// <summary>
    /// Add an entry. Throws <see cref="ArgumentException"/> if the key pair already exists.
    /// </summary>
    public void Add(TKey1 key1, TKey2 key2, TValue value)
    {
        _ = key1 ?? throw new ArgumentNullException(nameof(key1));
        _ = key2 ?? throw new ArgumentNullException(nameof(key2));
        if (_data.ContainsKey((key1, key2)))
            throw new ArgumentException($"Key ({key1}, {key2}) already exists.", nameof(key1));
        InternalAdd(key1, key2, value);
    }

    /// <summary>
    /// Remove the entry at the given key pair.
    /// Returns <see langword="true"/> if found and removed.
    /// </summary>
    public bool Remove(TKey1 key1, TKey2 key2)
    {
        _ = key1 ?? throw new ArgumentNullException(nameof(key1));
        _ = key2 ?? throw new ArgumentNullException(nameof(key2));
        if (!_data.TryGetValue((key1, key2), out TValue? value))
            return false;

        _data.Remove((key1, key2));
        _keyOrder.Remove((key1, key2));

        // Update key-axis views: drop a key only when its last entry is gone
        // (O(1) via refcounts, no scan over _data).
        if (_key1Counts.TryGetValue(key1, out int c1))
        {
            if (c1 <= 1)
            {
                _key1Counts.Remove(key1);
                _keys1.Remove(key1);
            }
            else
            {
                _key1Counts[key1] = c1 - 1;
            }
        }

        if (_key2Counts.TryGetValue(key2, out int c2))
        {
            if (c2 <= 1)
            {
                _key2Counts.Remove(key2);
                _keys2.Remove(key2);
            }
            else
            {
                _key2Counts[key2] = c2 - 1;
            }
        }

        OnRemoved(key1, key2, value);
        return true;
    }

    /// <summary>Returns <see langword="true"/> if an entry exists for the given key pair.</summary>
    public bool ContainsKey(TKey1 key1, TKey2 key2)
    {
        _ = key1 ?? throw new ArgumentNullException(nameof(key1));
        _ = key2 ?? throw new ArgumentNullException(nameof(key2));
        return _data.ContainsKey((key1, key2));
    }

    /// <summary>
    /// Try to get the value for the given key pair.
    /// Returns <see langword="false"/> if absent.
    /// </summary>
    public bool TryGetValue(TKey1 key1, TKey2 key2, out TValue value)
    {
        _ = key1 ?? throw new ArgumentNullException(nameof(key1));
        _ = key2 ?? throw new ArgumentNullException(nameof(key2));
#pragma warning disable CS8601 // value will be default(TValue) on false — caller checks return value
        return _data.TryGetValue((key1, key2), out value!);
#pragma warning restore CS8601
    }

    /// <summary>Remove all entries and emit <see cref="Reset"/>. Does NOT fire per-item events.</summary>
    public void Clear()
    {
        _data.Clear();
        _keyOrder.Clear();
        _keys1.Clear();
        _keys2.Clear();
        _key1Counts.Clear();
        _key2Counts.Clear();
        OnReset();
    }

    // ── Enumeration ────────────────────────────────────────────────────────────

    /// <summary>Enumerates entries in insertion order.</summary>
    public IEnumerator<KeyValuePair<(TKey1, TKey2), TValue>> GetEnumerator()
    {
        foreach (var key in _keyOrder)
            yield return new KeyValuePair<(TKey1, TKey2), TValue>(key, _data[key]);
    }

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();

    // ── Internal helpers ───────────────────────────────────────────────────────

    private void InternalAdd(TKey1 key1, TKey2 key2, TValue value)
    {
        _keyOrder.Add((key1, key2));
        _data[(key1, key2)] = value;

        // Update key-axis views only on first appearance (O(1) via refcounts).
        if (_key1Counts.TryGetValue(key1, out int c1))
            _key1Counts[key1] = c1 + 1;
        else
        {
            _key1Counts[key1] = 1;
            _keys1.Add(key1);
        }

        if (_key2Counts.TryGetValue(key2, out int c2))
            _key2Counts[key2] = c2 + 1;
        else
        {
            _key2Counts[key2] = 1;
            _keys2.Add(key2);
        }

        OnAdded(key1, key2, value);
    }

    private void OnAdded(TKey1 key1, TKey2 key2, TValue value)
    {
        // 1. Raise granular local event first.
        ItemAdded?.Invoke(this, new DictionaryItemAddedEventArgs<TKey1, TKey2, TValue>(key1, key2, value));
        CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Add,
            new KeyValuePair<(TKey1, TKey2), TValue>((key1, key2), value)));
        // 2. Publish to hub (if present).
        _hub?.Send(CollectionChangedMessage<KeyValuePair<(TKey1, TKey2), TValue>>.ForAdd(
            this,
            new KeyValuePair<(TKey1, TKey2), TValue>((key1, key2), value),
            _keyOrder.Count - 1));
    }

    private void OnRemoved(TKey1 key1, TKey2 key2, TValue value)
    {
        // 1. Raise granular local event first.
        ItemRemoved?.Invoke(this, new DictionaryItemRemovedEventArgs<TKey1, TKey2, TValue>(key1, key2, value));
        CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Remove,
            new KeyValuePair<(TKey1, TKey2), TValue>((key1, key2), value)));
        // 2. Publish to hub (if present).
        _hub?.Send(CollectionChangedMessage<KeyValuePair<(TKey1, TKey2), TValue>>.ForRemove(
            this,
            new KeyValuePair<(TKey1, TKey2), TValue>((key1, key2), value),
            -1));
    }

    private void OnReplaced(TKey1 key1, TKey2 key2, TValue newValue, TValue oldValue)
    {
        // 1. Raise granular local event first.
        ItemReplaced?.Invoke(this, new DictionaryItemReplacedEventArgs<TKey1, TKey2, TValue>(key1, key2, newValue, oldValue));
        CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Replace,
            new KeyValuePair<(TKey1, TKey2), TValue>((key1, key2), newValue),
            new KeyValuePair<(TKey1, TKey2), TValue>((key1, key2), oldValue)));
        // 2. Publish to hub (if present).
        _hub?.Send(CollectionChangedMessage<KeyValuePair<(TKey1, TKey2), TValue>>.ForReplace(
            this,
            new KeyValuePair<(TKey1, TKey2), TValue>((key1, key2), newValue),
            new KeyValuePair<(TKey1, TKey2), TValue>((key1, key2), oldValue),
            -1));
    }

    private void OnReset()
    {
        // 1. Raise local events first.
        Reset?.Invoke(this, EventArgs.Empty);
        CollectionChanged?.Invoke(this, new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Reset));
        // 2. Publish to hub (if present).
        _hub?.Send(CollectionChangedMessage<KeyValuePair<(TKey1, TKey2), TValue>>.ForReset(this));
    }
}
