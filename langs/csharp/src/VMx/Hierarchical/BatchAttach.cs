using System.Collections.ObjectModel;

namespace VMx.Hierarchical;

/// <summary>Missing-parent retention policy for batch hierarchy ingestion.</summary>
public enum MissingParentPolicy
{
    /// <summary>Retain and retry unresolved missing-parent items.</summary>
    Park,
    /// <summary>Return unresolved items without retaining them.</summary>
    Reject,
}

/// <summary>
/// A parent-key selector result. <see cref="Root"/> means attach directly
/// beneath the structural root; <see cref="For"/> identifies another node.
/// This explicit option shape supports both reference- and value-type keys.
/// </summary>
public readonly struct BatchParentKey<TKey> where TKey : notnull
{
    private readonly bool _hasKey;
    private readonly TKey? _key;

    private BatchParentKey(TKey key)
    {
        _hasKey = true;
        _key = key;
    }

    /// <summary>Whether this denotes the structural root.</summary>
    public bool IsRoot => !_hasKey;

    /// <summary>The requested parent key; invalid when <see cref="IsRoot"/>.</summary>
    public TKey Key => IsRoot
        ? throw new InvalidOperationException("A root parent key has no value.")
        : _key!;

    /// <summary>Creates the structural-root sentinel.</summary>
    public static BatchParentKey<TKey> Root => default;

    /// <summary>Creates a concrete parent-key reference.</summary>
    public static BatchParentKey<TKey> For(TKey key)
    {
        if (key is null) throw new ArgumentNullException(nameof(key));
        return new BatchParentKey<TKey>(key);
    }
}

/// <summary>Typed reason why one batch item was not attached.</summary>
public enum BatchAttachRejectionReason
{
    /// <summary>The key already belongs to a materialized tree node.</summary>
    DuplicateExistingKey,
    /// <summary>An earlier active batch item already claimed the key.</summary>
    DuplicateBatchKey,
    /// <summary>The item is already attached outside the target tree.</summary>
    AlreadyAttached,
    /// <summary>The requested parent key is not materialized.</summary>
    MissingParent,
    /// <summary>The unresolved parent-key graph contains a cycle.</summary>
    Cycle,
    /// <summary>A consumer selector failed.</summary>
    SelectorFailed,
    /// <summary>The underlying single-node attachment failed.</summary>
    AttachmentFailed,
}

/// <summary>One typed, non-throwing batch-attachment rejection.</summary>
public sealed class BatchAttachRejection<TVM>
{
    internal BatchAttachRejection(TVM item, BatchAttachRejectionReason reason, string? detail = null)
    {
        Item = item;
        Reason = reason;
        Detail = detail;
    }

    /// <summary>The input item that was not attached.</summary>
    public TVM Item { get; }
    /// <summary>The stable rejection category.</summary>
    public BatchAttachRejectionReason Reason { get; }
    /// <summary>Optional diagnostic text for selector/attachment failures.</summary>
    public string? Detail { get; }
}

/// <summary>Structured result of one batch-attachment attempt.</summary>
public sealed class BatchAttachResult<TVM>
{
    internal BatchAttachResult(
        List<TVM> added,
        List<TVM> duplicates,
        List<TVM> orphans,
        List<BatchAttachRejection<TVM>> rejections)
    {
        Added = new ReadOnlyCollection<TVM>(added);
        Duplicates = new ReadOnlyCollection<TVM>(duplicates);
        Orphans = new ReadOnlyCollection<TVM>(orphans);
        Rejections = new ReadOnlyCollection<BatchAttachRejection<TVM>>(rejections);
    }

    /// <summary>Nodes attached during this call, including retried parked nodes.</summary>
    public IReadOnlyList<TVM> Added { get; }
    /// <summary>Same-key inputs that were not attached.</summary>
    public IReadOnlyList<TVM> Duplicates { get; }
    /// <summary>Items still missing a materialized parent.</summary>
    public IReadOnlyList<TVM> Orphans { get; }
    /// <summary>Typed outcomes for every item not attached.</summary>
    public IReadOnlyList<BatchAttachRejection<TVM>> Rejections { get; }
}
