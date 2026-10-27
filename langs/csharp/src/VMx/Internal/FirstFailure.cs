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
}
