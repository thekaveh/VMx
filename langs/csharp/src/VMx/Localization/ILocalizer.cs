namespace VMx.Localization;

/// <summary>
/// Localization hook contract. See spec/17-localization.md and ADR-0019.
/// </summary>
public interface ILocalizer
{
    /// <summary>Returns the localized string for <paramref name="key"/>.</summary>
    string Localize(string key);

    /// <summary>Returns the localized string for <paramref name="key"/>, optionally formatted with <paramref name="args"/>.</summary>
    string Localize(string key, IEnumerable<object?> args);
}
