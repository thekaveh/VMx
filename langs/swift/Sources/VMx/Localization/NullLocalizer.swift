/// Null variant: returns the key verbatim (LOC-002), ignoring any args.
public final class NullLocalizer: Localizer, Sendable {
    public static let INSTANCE = NullLocalizer()
    public init() {}
    public func localize(_ key: String, _ args: [Any]?) -> String { key }
}
