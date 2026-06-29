namespace NotesShowcase.Tests;

/// <summary>
/// Deterministic wait helper for tests that exercise fire-and-forget async
/// view-model refreshes (NewNote, bind/rebind, save, delete, export). Those
/// paths complete on a background continuation, so the tests previously slept a
/// fixed <c>Task.Delay(50)</c> hoping the refresh had landed — which flakes
/// under CI load (a slower runner needs &gt; 50&#160;ms). This polls the actual
/// post-condition instead: it returns the instant the condition holds, or after
/// the timeout, in which case the caller's assertion reports the real failure.
/// </summary>
internal static class TestWait
{
    public static async Task WaitUntilAsync(
        Func<bool> condition,
        int timeoutMs = 2000,
        int pollMs = 5)
    {
        var deadline = DateTime.UtcNow + TimeSpan.FromMilliseconds(timeoutMs);
        while (!condition())
        {
            if (DateTime.UtcNow >= deadline)
            {
                return;
            }
            await Task.Delay(pollMs);
        }
    }
}
