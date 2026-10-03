namespace VMx.Tests.Helpers;

/// <summary>Liveness bound for tests that wait on another thread.</summary>
public static class Liveness
{
    /// <summary>
    /// The bound for a wait that is expected to succeed (#537, #546). A cold,
    /// oversubscribed Windows runner collecting coverage can delay a thread by
    /// seconds, so short deadlines failed without any wrong behavior. A passing
    /// wait returns as soon as its condition holds, so the bound costs nothing.
    /// Windows that assert something did not happen keep their short spans.
    /// </summary>
    public static readonly TimeSpan HangGuard = TimeSpan.FromSeconds(30);
}
