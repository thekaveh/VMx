//
// NullDialogService — null-object variant of `DialogService`.
//
// See spec/19-dialogs.md §"Null variant" and ADR-0029.
//
// All operations complete with the safest possible default:
//   - pickFileToOpen / pickFileToSave → nil  (no file selected)
//   - confirm                         → false (not confirmed)
//   - notify                          → no-op (acknowledged silently)
//

/// Null-object implementation of `DialogService`. Suitable as a default
/// injection target when no real host UI is available (tests, previews, CLI).
public final class NullDialogService: DialogService {
    /// Shared singleton instance. The service is stateless.
    public static let INSTANCE = NullDialogService()

    public init() {}

    /// Returns `nil` — no file was selected (cancel default).
    public func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? {
        nil
    }

    /// Returns `nil` — no file was selected (cancel default).
    public func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? {
        nil
    }

    /// Returns `false` — not confirmed (safest default per DIA-007).
    public func confirm(_ message: String, title: String?) async -> Bool {
        false
    }

    /// No-op — notification is silently acknowledged.
    public func notify(_ message: String, title: String?, severity: NotificationSeverity) async {
        // intentional no-op
    }
}
