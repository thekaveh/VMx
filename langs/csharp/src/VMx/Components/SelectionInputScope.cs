using System.Runtime.ExceptionServices;
using VMx.Internal;

namespace VMx.Components;

/// <summary>
/// The per-thread scope of the selection-input notification (ADR-0242). A
/// container membership transaction, and an aggregate slot replacement, enter
/// the scope. While a scope is open, a child whose selection inputs changed is
/// queued, not notified. The outermost scope on the thread emits the queue
/// after it has released every container lock, so no <c>CanExecuteChanged</c>
/// subscriber runs under a membership gate (spec/06 §4.3).
/// </summary>
internal static class SelectionInputScope
{
    [ThreadStatic] private static int _depth;
    [ThreadStatic] private static List<ComponentVMBase>? _pending;

    /// <summary>Opens a scope on the calling thread. Pair each call with <see cref="Leave"/>.</summary>
    internal static void Enter() => _depth++;

    /// <summary>Opens a scope that closes when the returned value is disposed (a <c>using</c> scope).</summary>
    internal static Closer Open()
    {
        Enter();
        return default;
    }

    /// <summary>The disposable end of <see cref="Open"/>.</summary>
    internal readonly struct Closer : IDisposable
    {
        /// <summary>Closes the scope that <see cref="Open"/> opened.</summary>
        public void Dispose() => Leave();
    }

    /// <summary>
    /// Closes a scope. The outermost close emits the queued children. Call it
    /// after the container lock of the scope is released; a close made under a
    /// lock must leave no queued child, which holds when it is not outermost.
    /// </summary>
    internal static void Leave()
    {
        if (_depth > 0) _depth--;
        if (_depth > 0) return;
        var pending = _pending;
        _pending = null;
        if (pending is null) return;
        ExceptionDispatchInfo? firstError = null;
        foreach (var child in pending)
            FirstFailure.Capture(ref firstError, child.EmitSelectionInputs);
        firstError?.Throw();
    }

    /// <summary>Queues a child for the open scope, or emits at once when no scope is open.</summary>
    internal static void Queue(ComponentVMBase child)
    {
        if (_depth == 0)
        {
            child.EmitSelectionInputs();
            return;
        }
        (_pending ??= new List<ComponentVMBase>()).Add(child);
    }
}
