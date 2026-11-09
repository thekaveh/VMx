using System.Collections;
using System.Collections.Specialized;
using System.ComponentModel;

namespace VMx.Collections;

/// <summary>
/// A live, read-only facade over an <see cref="ObservableList{T}"/>.
///
/// <para>
/// It has every read and subscribe member of <see cref="ObservableList{T}"/>
/// and no mutator and no batch member. Each event reaches its handlers in the
/// source's order, with the source's arguments and with this facade as sender,
/// as the BCL <c>ReadOnlyObservableCollection&lt;T&gt;</c> does. The facade
/// does not expose the backing list.
/// </para>
///
/// <para>
/// <see cref="ObservableDictionary{TKey1,TKey2,TValue}.Keys1"/> and
/// <see cref="ObservableDictionary{TKey1,TKey2,TValue}.Keys2"/> return this type.
/// Only the dictionary changes a key view.
/// </para>
///
/// See spec/21-collections.md §4.2 and ADR-0193.
/// </summary>
/// <typeparam name="T">Element type.</typeparam>
public sealed class ReadOnlyObservableList<T> :
    IReadOnlyList<T>,
    INotifyCollectionChanged,
    INotifyPropertyChanged
{
    private readonly ObservableList<T> _source;

    internal ReadOnlyObservableList(ObservableList<T> source)
    {
        _source = source;
        _source.ItemAdded += (_, e) => ItemAdded?.Invoke(this, e);
        _source.ItemRemoved += (_, e) => ItemRemoved?.Invoke(this, e);
        _source.ItemReplaced += (_, e) => ItemReplaced?.Invoke(this, e);
        _source.Reset += (_, e) => Reset?.Invoke(this, e);
        _source.CollectionChanged += (_, e) => CollectionChanged?.Invoke(this, e);
        _source.PropertyChanged += (_, e) => PropertyChanged?.Invoke(this, e);
    }

    // ── Granular events ───────────────────────────────────────────────────────

    /// <summary>Fires when an item is added. Payload: item and insertion index.</summary>
    public event EventHandler<ItemAddedEventArgs<T>>? ItemAdded;

    /// <summary>Fires when an item is removed. Payload: item and index before removal.</summary>
    public event EventHandler<ItemRemovedEventArgs<T>>? ItemRemoved;

    /// <summary>Fires when an item is replaced. Payload: new item, old item, and index.</summary>
    public event EventHandler<ItemReplacedEventArgs<T>>? ItemReplaced;

    /// <summary>Fires when the source list is cleared or a source batch with mutations completes.</summary>
    public event EventHandler? Reset;

    // ── Platform compatibility ────────────────────────────────────────────────

    /// <inheritdoc/>
    public event NotifyCollectionChangedEventHandler? CollectionChanged;

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged;

    // ── IReadOnlyList<T> ──────────────────────────────────────────────────────

    /// <inheritdoc/>
    public int Count => _source.Count;

    /// <inheritdoc/>
    public T this[int index] => _source[index];

    /// <inheritdoc/>
    public IEnumerator<T> GetEnumerator() => _source.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
}
