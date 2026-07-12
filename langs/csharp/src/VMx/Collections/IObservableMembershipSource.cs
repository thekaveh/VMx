namespace VMx.Collections;

/// <summary>
/// Provides an ordered membership snapshot and payload-free structural change
/// notifications without exposing collection mutation or ownership.
/// </summary>
/// <typeparam name="T">Membership item type.</typeparam>
public interface IObservableMembershipSource<T>
{
    /// <summary>Returns the current ordered membership as an independent snapshot.</summary>
    IReadOnlyList<T> Snapshot();

    /// <summary>Subscribes to structural membership changes.</summary>
    /// <param name="callback">Invoked after Add, Remove, Replace, Move, or Reset.</param>
    /// <returns>An idempotent subscription that detaches only this callback.</returns>
    IDisposable SubscribeMembership(Action callback);
}
