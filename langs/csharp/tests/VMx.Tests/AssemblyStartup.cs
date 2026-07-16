using System.Runtime.CompilerServices;

namespace VMx.Tests;

/// <summary>
/// Test-assembly bootstrap. VMx.Tests contains concurrent/race tests that block
/// ThreadPool threads while awaiting deterministic signals (events/TCS), alongside
/// heavy stress sweeps (e.g. the 20k-iteration dispose-race) that also consume pool
/// threads. The .NET ThreadPool injects new worker threads only slowly (~one every
/// 0.5s once the floor is exhausted), so under CI's parallel xUnit execution on a
/// 2-core runner the pool starves and otherwise-correct timing tests trip their wait
/// deadlines (observed: observerEntered/disposeStarted 5s waits timing out, a
/// background-construct task taking &gt;5s to fault). A generous min-threads floor keeps
/// the pool responsive; production code is untouched.
/// </summary>
internal static class AssemblyStartup
{
    [ModuleInitializer]
    internal static void ConfigureThreadPool()
    {
        ThreadPool.SetMinThreads(workerThreads: 64, completionPortThreads: 64);
    }
}
