namespace VMx;

/// <summary>
/// Placeholder marker type. Replaced with the real Lifecycle types in Phase 2a.
/// Exists so the assembly is non-empty and the smoke test has something to assert against.
/// </summary>
public static class Placeholder
{
    /// <summary>
    /// The minimum spec version this assembly implements. Mirrors the
    /// <c>MinSpecVersion</c> MSBuild property and is asserted by the smoke test.
    /// </summary>
    public const string MinSpecVersion = "0.0.0";
}
