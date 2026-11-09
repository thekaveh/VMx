using System.Runtime.ExceptionServices;

namespace VMx.Internal;

/// <summary>
/// Runs teardown steps so that every step runs and the first failure is kept
/// for a later rethrow.
/// </summary>
internal static class FirstFailure
{
    /// <summary>
    /// Runs <paramref name="action"/>. When it throws, keeps the exception in
    /// <paramref name="firstError"/> unless an earlier step already failed.
    /// </summary>
    public static void Capture(ref ExceptionDispatchInfo? firstError, Action action)
    {
        try { action(); }
        catch (Exception error) { firstError ??= ExceptionDispatchInfo.Capture(error); }
    }

    /// <summary>
    /// Runs <paramref name="action"/> with <paramref name="state"/>, so a
    /// caller on a hot path can pass a <c>static</c> lambda that allocates no
    /// closure. When it throws, keeps the exception in
    /// <paramref name="firstError"/> unless an earlier step already failed.
    /// </summary>
    public static void Capture<TState>(
        ref ExceptionDispatchInfo? firstError, TState state, Action<TState> action)
    {
        try { action(state); }
        catch (Exception error) { firstError ??= ExceptionDispatchInfo.Capture(error); }
    }
}
