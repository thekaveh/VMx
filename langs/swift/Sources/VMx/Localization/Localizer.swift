/// Localization hook (spec/17-localization.md). A pure, stateless string lookup
/// contract — implementations may return localized text, the key, or "". Culture
/// changes are handled by swapping the injected Localizer (DI), not via a stream.
public protocol Localizer {
    /// Returns the localized string for `key`, optionally formatted with `args`.
    func localize(_ key: String, _ args: [Any]?) -> String
}

public extension Localizer {
    /// Convenience overload for the common no-args call.
    func localize(_ key: String) -> String { localize(key, nil) }
}
