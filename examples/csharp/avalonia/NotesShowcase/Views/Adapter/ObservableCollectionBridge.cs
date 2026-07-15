using System.Collections.ObjectModel;
using System.Collections.Specialized;

namespace NotesShowcase.Views.Adapter;

/// <summary>
/// CollectionBridge (scenario §7.1, plan §4.a): wraps a VMx source that
/// implements <see cref="INotifyCollectionChanged"/> and <see cref="IEnumerable{T}"/>
/// (typically <see cref="VMx.Composites.CompositeVM{VM}"/> or its base) and
/// mirrors Add/Remove/Replace/Reset operations on the base
/// <see cref="ObservableCollection{T}"/>.
///
/// <para>
/// XAML <see cref="System.Windows.Controls.ItemsControl"/>-style consumers can
/// bind directly to this bridge: they observe standard
/// <see cref="ObservableCollection{T}.CollectionChanged"/> events without ever
/// touching the VMx hub.
/// </para>
/// </summary>
/// <typeparam name="T">Element type — typically a VMx <c>IComponentVM</c> subtype.</typeparam>
public sealed class ObservableCollectionBridge<T> : ObservableCollection<T>, IDisposable
{
    private readonly INotifyCollectionChanged _source;
    private readonly NotifyCollectionChangedEventHandler _handler;
    private bool _disposed;

    /// <summary>
    /// Wraps <paramref name="source"/>, copying its current contents and
    /// subscribing to its <see cref="INotifyCollectionChanged.CollectionChanged"/>
    /// event. Subsequent source mutations are mirrored on this bridge.
    /// </summary>
    /// <param name="source">A VMx composite (or any INCC + IEnumerable&lt;T&gt;) source. Required.</param>
    /// <exception cref="ArgumentNullException">If <paramref name="source"/> is null.</exception>
    /// <exception cref="ArgumentException">
    /// If <paramref name="source"/> does not also expose an <see cref="IEnumerable{T}"/> view.
    /// </exception>
    public ObservableCollectionBridge(INotifyCollectionChanged source)
        : base(SnapshotSource(source))
    {
        _source = source;
        _handler = OnSourceCollectionChanged;
        _source.CollectionChanged += _handler;
    }

    private static IEnumerable<T> SnapshotSource(INotifyCollectionChanged source)
    {
        ArgumentNullException.ThrowIfNull(source);
        if (source is IEnumerable<T> typed) return typed.ToList();
        throw new ArgumentException(
            $"Source must implement IEnumerable<{typeof(T).Name}>; got {source.GetType().Name}.",
            nameof(source));
    }

    private void OnSourceCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        switch (e.Action)
        {
            case NotifyCollectionChangedAction.Add:
                ApplyAdd(e);
                break;
            case NotifyCollectionChangedAction.Remove:
                ApplyRemove(e);
                break;
            case NotifyCollectionChangedAction.Replace:
                ApplyReplace(e);
                break;
            case NotifyCollectionChangedAction.Move:
                ApplyMove(e);
                break;
            case NotifyCollectionChangedAction.Reset:
                ApplyReset();
                break;
            default:
                ApplyReset();
                break;
        }
    }

    private void ApplyAdd(NotifyCollectionChangedEventArgs e)
    {
        if (e.NewItems is null) return;
        var idx = e.NewStartingIndex >= 0 ? e.NewStartingIndex : Count;
        for (var i = 0; i < e.NewItems.Count; i++)
            Insert(idx + i, (T)e.NewItems[i]!);
    }

    private void ApplyRemove(NotifyCollectionChangedEventArgs e)
    {
        if (e.OldItems is null) return;
        var idx = e.OldStartingIndex;
        if (idx < 0 || idx > Count || e.OldItems.Count > Count - idx)
        {
            ApplyReset();
            return;
        }
        for (var i = 0; i < e.OldItems.Count; i++)
            RemoveAt(idx);
    }

    private void ApplyReplace(NotifyCollectionChangedEventArgs e)
    {
        if (e.NewItems is null || e.NewStartingIndex < 0) return;
        for (var i = 0; i < e.NewItems.Count; i++)
            this[e.NewStartingIndex + i] = (T)e.NewItems[i]!;
    }

    private void ApplyMove(NotifyCollectionChangedEventArgs e)
    {
        if (e.OldStartingIndex < 0 || e.NewStartingIndex < 0) return;
        Move(e.OldStartingIndex, e.NewStartingIndex);
    }

    private void ApplyReset()
    {
        Clear();
        if (_source is IEnumerable<T> typed)
        {
            foreach (var item in typed)
                Add(item);
        }
    }

    /// <summary>Unsubscribes from the source's <see cref="INotifyCollectionChanged"/>. Idempotent.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _source.CollectionChanged -= _handler;
    }
}
