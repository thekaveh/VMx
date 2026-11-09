using System.Runtime.ExceptionServices;
using VMx.Internal;

namespace VMx.Components;

/// <summary>
/// Disposes the candidates that a failed population built and nobody owns
/// (#1324). A population fails when a later factory or projector throws, or
/// when its preflight refuses it before the commit.
/// </summary>
internal static class UnownedCandidates
{
    /// <summary>
    /// Disposes each candidate that has no parent, is in no other ownership
    /// transaction, and is not an owner on the ancestor chain of
    /// <paramref name="parent"/>. Each canonical identity is disposed once.
    /// The disposal is best-effort: the population's own failure is the one
    /// that propagates.
    /// <para>
    /// The parent and in-progress checks take no lock. If another thread
    /// starts to attach a candidate after the checks, this cleanup can still
    /// dispose it. A factory's fresh output is normally reachable only by the
    /// failed population, so the window is narrow.
    /// </para>
    /// </summary>
    internal static void Dispose(IParentCompositeVM parent, IEnumerable<IComponentVM?> candidates)
    {
        var seen = new HashSet<IComponentVM>(ComponentVMBase.ChildReferenceComparer.Instance);
        foreach (var candidate in candidates)
        {
            if (candidate is null) continue;
            var identity = candidate.GetOwnershipIdentity();
            if (!seen.Add(identity)) continue;
            if (candidate.GetParent() is not null) continue;
            if (ComponentOwnership.IsInProgress(identity)) continue;
            if (OwnsOnChain(parent, identity)) continue;
            ExceptionDispatchInfo? ignored = null;
            FirstFailure.Capture(ref ignored, candidate.Dispose);
        }
    }

    private static bool OwnsOnChain(IParentCompositeVM parent, IComponentVM identity)
    {
        for (IParentCompositeVM? cursor = parent; cursor is not null; cursor = cursor.OwnerParent)
        {
            if (cursor.Owner is not null &&
                ReferenceEquals(cursor.Owner.GetOwnershipIdentity(), identity))
                return true;
        }
        return false;
    }
}
