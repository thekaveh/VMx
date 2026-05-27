namespace VMx.Localization;

/// <summary>
/// Null-object variant per ADR-0017. Both overloads return the input key
/// unchanged. See spec/17-localization.md.
/// </summary>
public sealed class NullLocalizer : ILocalizer
{
    /// <summary>Shared singleton.</summary>
    public static NullLocalizer Instance { get; } = new();

    private NullLocalizer() { }

    /// <inheritdoc/>
    public string Localize(string key) => key;

    /// <inheritdoc/>
    public string Localize(string key, IEnumerable<object?> args) => key;
}
