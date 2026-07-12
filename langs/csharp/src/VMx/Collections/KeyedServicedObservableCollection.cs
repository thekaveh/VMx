using System.Collections.Specialized;
using System.ComponentModel;
using System.Diagnostics.CodeAnalysis;
using VMx.Services;

namespace VMx.Collections;

/// <summary>
/// An ordered serviced collection with captured-key lookup.
/// </summary>
/// <typeparam name="TKey">Stable, non-null key type.</typeparam>
/// <typeparam name="TItem">Element type.</typeparam>
/// <remarks>
/// Keys are projected before insertion and retained until that membership is
/// explicitly replaced. Lookup, removal, move, and clear never reproject a
/// stored item. The collection does not own or dispose its items.
/// </remarks>
public sealed class KeyedServicedObservableCollection<TKey, TItem>
    : ServicedObservableCollection<TItem>
    where TKey : notnull
{
    private readonly List<TKey> _capturedKeys = new();
    private readonly Dictionary<TKey, int> _indexByKey;
    private readonly Func<TItem, TKey> _keySelector;

    /// <summary>Initializes an empty keyed serviced collection.</summary>
    /// <param name="keySelector">Projects the stable key captured for each membership.</param>
    /// <param name="hub">Optional hub for collection-change publication.</param>
    /// <param name="comparer">Optional key equality comparer.</param>
    public KeyedServicedObservableCollection(
        Func<TItem, TKey> keySelector,
        IMessageHub? hub = null,
        IEqualityComparer<TKey>? comparer = null)
        : base(hub)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(keySelector);
#else
        if (keySelector is null) throw new ArgumentNullException(nameof(keySelector));
#endif
        _keySelector = keySelector;
        _indexByKey = new Dictionary<TKey, int>(comparer);
    }

    /// <summary>Returns whether a captured membership has <paramref name="key"/>.</summary>
    public bool ContainsKey(TKey key) => _indexByKey.ContainsKey(key);

    /// <summary>Attempts to obtain the item whose captured key is <paramref name="key"/>.</summary>
    public bool TryGetValue(TKey key, [MaybeNullWhen(false)] out TItem item)
    {
        if (_indexByKey.TryGetValue(key, out int index))
        {
            item = Items[index];
            return true;
        }

        item = default;
        return false;
    }

    /// <summary>
    /// Appends a missing key or replaces the membership at a present key.
    /// </summary>
    /// <returns><c>true</c> for Add; <c>false</c> for Replace.</returns>
    public bool Upsert(TItem item)
    {
        TKey key = _keySelector(item);
        if (_indexByKey.TryGetValue(key, out int index))
        {
            CheckReentrancy();
            SetProjectedItem(index, item, key);
            return false;
        }

        CheckReentrancy();
        InsertProjectedItem(Count, item, key);
        return true;
    }

    /// <summary>Removes the membership with <paramref name="key"/>, if present.</summary>
    public bool RemoveKey(TKey key)
    {
        if (!_indexByKey.TryGetValue(key, out int index)) return false;

        RemoveAt(index);
        return true;
    }

    /// <inheritdoc/>
    public override void ReplaceAll(IEnumerable<TItem> items)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(items);
#else
        if (items is null) throw new ArgumentNullException(nameof(items));
#endif

        TItem[] snapshot = items.ToArray();
        var candidateKeys = new TKey[snapshot.Length];
        var candidateIndex = new Dictionary<TKey, int>(_indexByKey.Comparer);

        for (int index = 0; index < snapshot.Length; index++)
        {
            TKey key = _keySelector(snapshot[index]);
            if (candidateIndex.ContainsKey(key)) ThrowDuplicateKey(key);
            candidateKeys[index] = key;
            candidateIndex.Add(key, index);
        }

        if (Count == 0 && snapshot.Length == 0) return;

        CheckReentrancy();
        _capturedKeys.Clear();
        _capturedKeys.AddRange(candidateKeys);
        _indexByKey.Clear();
        foreach (KeyValuePair<TKey, int> entry in candidateIndex)
            _indexByKey.Add(entry.Key, entry.Value);

        Items.Clear();
        foreach (TItem item in snapshot) Items.Add(item);

        OnPropertyChanged(new PropertyChangedEventArgs(nameof(Count)));
        OnPropertyChanged(new PropertyChangedEventArgs("Item[]"));
        OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
    }

    /// <inheritdoc/>
    protected override void InsertItem(int index, TItem item)
    {
        ValidateInsertIndex(index);
        CheckReentrancy();
        TKey key = _keySelector(item);
        if (_indexByKey.ContainsKey(key)) ThrowDuplicateKey(key);

        InsertProjectedItem(index, item, key);
    }

    /// <inheritdoc/>
    protected override void SetItem(int index, TItem item)
    {
        ValidateExistingIndex(index);
        CheckReentrancy();
        TKey key = _keySelector(item);
        if (_indexByKey.TryGetValue(key, out int ownerIndex) && ownerIndex != index)
            ThrowDuplicateKey(key);

        SetProjectedItem(index, item, key);
    }

    /// <inheritdoc/>
    protected override void RemoveItem(int index)
    {
        ValidateExistingIndex(index);
        CheckReentrancy();

        TKey oldKey = _capturedKeys[index];
        _indexByKey.Remove(oldKey);
        _capturedKeys.RemoveAt(index);
        RepairIndices(index);

        base.RemoveItem(index);
    }

    /// <inheritdoc/>
    protected override void MoveItem(int oldIndex, int newIndex)
    {
        ValidateExistingIndex(oldIndex, nameof(oldIndex));
        ValidateExistingIndex(newIndex, nameof(newIndex));
        if (oldIndex == newIndex) return;
        CheckReentrancy();

        TKey key = _capturedKeys[oldIndex];
        _capturedKeys.RemoveAt(oldIndex);
        _capturedKeys.Insert(newIndex, key);
        RepairIndices(Math.Min(oldIndex, newIndex), Math.Max(oldIndex, newIndex));

        base.MoveItem(oldIndex, newIndex);
    }

    /// <inheritdoc/>
    protected override void ClearItems()
    {
        if (Count == 0) return;
        CheckReentrancy();

        _capturedKeys.Clear();
        _indexByKey.Clear();
        base.ClearItems();
    }

    private void InsertProjectedItem(int index, TItem item, TKey key)
    {
        _capturedKeys.Insert(index, key);
        _indexByKey.Add(key, index);
        RepairIndices(index + 1);
        base.InsertItem(index, item);
    }

    private void SetProjectedItem(int index, TItem item, TKey key)
    {
        TKey oldKey = _capturedKeys[index];
        _indexByKey.Remove(oldKey);
        _capturedKeys[index] = key;
        _indexByKey.Add(key, index);
        base.SetItem(index, item);
    }

    private void RepairIndices(int startIndex, int? endIndex = null)
    {
        int lastIndex = endIndex ?? (_capturedKeys.Count - 1);
        for (int index = startIndex; index <= lastIndex; index++)
            _indexByKey[_capturedKeys[index]] = index;
    }

    private void ValidateInsertIndex(int index)
    {
        if ((uint)index > (uint)Count)
            throw new ArgumentOutOfRangeException(nameof(index));
    }

    private void ValidateExistingIndex(int index, string parameterName = "index")
    {
        if ((uint)index >= (uint)Count)
            throw new ArgumentOutOfRangeException(parameterName);
    }

    private static void ThrowDuplicateKey(TKey key) =>
        throw new ArgumentException($"A membership with key '{key}' already exists.", nameof(key));
}
