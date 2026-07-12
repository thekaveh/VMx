using System.Collections.Specialized;

namespace VMx.Messages;

/// <summary>
/// Emitted by <see cref="VMx.Collections.ServicedObservableCollection{T}"/> when
/// the collection mutates.  See spec/21-collections.md §2 and ADR-0024.
/// </summary>
/// <typeparam name="T">Element type of the collection.</typeparam>
public interface ICollectionChangedMessage<T> : IMessage
{
    /// <summary>The action that caused the change (Add / Remove / Replace / Move / Reset).</summary>
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

    // netstandard2.0 cannot encode default interface implementations. Omitting
    // these members on that TFM preserves existing third-party implementers;
    // CollectionChangedMessage<T> still exposes both concrete properties.
#if NET8_0_OR_GREATER
    /// <summary>
    /// Source position for Remove, Replace, or Move; otherwise -1.
    /// Legacy implementations receive an Index-based default for Remove and Replace.
    /// </summary>
    int OldIndex => Action is NotifyCollectionChangedAction.Remove or NotifyCollectionChangedAction.Replace
        ? Index
        : -1;

    /// <summary>
    /// Destination position for Add, Replace, or Move; otherwise -1.
    /// Legacy implementations receive an Index-based default for these actions.
    /// </summary>
    int NewIndex => Action is NotifyCollectionChangedAction.Add
        or NotifyCollectionChangedAction.Replace
        or NotifyCollectionChangedAction.Move
        ? Index
        : -1;
#endif
}
