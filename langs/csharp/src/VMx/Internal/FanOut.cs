using System.Runtime.ExceptionServices;

namespace VMx.Internal;

/// <summary>
/// Raises a multicast event handler so that every handler runs once, even
/// when an earlier one throws (spec/03 §3.6, ADR-0191).
/// </summary>
internal static class FanOut
{
    /// <summary>
    /// Invokes each entry of <paramref name="handler"/> in order through
    /// <paramref name="invoke"/>. Returns the first failure, or <c>null</c>.
    /// The caller rethrows it after its hub send (ADR-0171) or discards it on
    /// a stream-fed path.
    /// </summary>
    public static ExceptionDispatchInfo? Raise<THandler>(THandler? handler, Action<THandler> invoke)
        where THandler : Delegate
    {
        if (handler is null) return null;
        ExceptionDispatchInfo? firstError = null;
        foreach (Delegate entry in handler.GetInvocationList())
            FirstFailure.Capture(ref firstError, () => invoke((THandler)entry));
        return firstError;
    }
}
