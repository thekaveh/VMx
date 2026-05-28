using System.Collections.Specialized;

namespace VMx.Messages;

/// <summary>
/// Emitted by <see cref="VMx.Collections.ServicedObservableCollection{T}"/> when
/// the collection mutates.  See spec/21-collections.md §2 and ADR-0024.
/// </summary>
/// <typeparam name="T">Element type of the collection.</typeparam>
public interface ICollectionChangedMessage<T> : IMessage
{
    /// <summary>The action that caused the change (Add / Remove / Replace / Reset).</summary>
    NotifyCollectionChangedAction Action { get; }

    /// <summary>Items added (or the replacement value on Replace). Empty on Remove/Reset.</summary>
    IReadOnlyList<T> NewItems { get; }

    /// <summary>Items removed (or the replaced value on Replace). Empty on Add/Reset.</summary>
    IReadOnlyList<T> OldItems { get; }

    /// <summary>
    /// Index of the change, or -1 for Reset.
    /// On Replace this is the index of the replaced element.
    /// </summary>
    int Index { get; }
}
