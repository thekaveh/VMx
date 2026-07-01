//
// DialogService — host-side modal interaction contract.
//
// See spec/19-dialogs.md and ADR-0029.
//

/// Severity level for a notification presented via `DialogService.notify`.
public enum NotificationSeverity: Sendable {
    case info
    case warning
    case error
}

/// Describes a file-type filter for file-picker dialogs.
public struct FileFilter: Sendable, Equatable {
    /// Human-readable label, e.g. `"Image files"`.
    public let description: String
    /// File extension patterns, e.g. `["*.png", "*.jpg"]`.
    public let extensions: [String]

    public init(description: String, extensions: [String]) {
        self.description = description
        self.extensions = extensions
    }
}

/// Host-side service contract for modal interactions: file pick, confirm prompt,
/// and severity-tagged notify. See spec/19-dialogs.md §2.
///
/// Methods are `async`, NOT `throws` — cancellation resolves with the safe
/// default (nil / false) rather than throwing (per DIA-007).
public protocol DialogService {
    /// Presents a file-open dialog. Returns the selected path, or `nil` on cancel.
    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String?

    /// Presents a file-save dialog. Returns the selected path, or `nil` on cancel.
    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String?

    /// Presents a confirmation prompt. Returns `true` when confirmed,
    /// `false` when cancelled or dismissed.
    func confirm(_ message: String, title: String?) async -> Bool

    /// Presents a notification with the given severity. Returns when
    /// acknowledged or dismissed.
    func notify(_ message: String, title: String?, severity: NotificationSeverity) async

    /// Presents a VM-backed modal and resolves with its result.
    func present<M: ModalVM>(_ modalVM: M) async -> M.Result
}

// MARK: - Convenience overloads (optional parameters)

public extension DialogService {
    /// `pickFileToOpen` with no filter or title.
    func pickFileToOpen() async -> String? {
        await pickFileToOpen(filter: nil, title: nil)
    }

    /// `pickFileToOpen` with filter only.
    func pickFileToOpen(filter: FileFilter?) async -> String? {
        await pickFileToOpen(filter: filter, title: nil)
    }

    /// `pickFileToSave` with no parameters.
    func pickFileToSave() async -> String? {
        await pickFileToSave(filter: nil, title: nil, suggestedName: nil)
    }

    /// `pickFileToSave` with filter only.
    func pickFileToSave(filter: FileFilter?) async -> String? {
        await pickFileToSave(filter: filter, title: nil, suggestedName: nil)
    }

    /// `pickFileToSave` with filter and title only.
    func pickFileToSave(filter: FileFilter?, title: String?) async -> String? {
        await pickFileToSave(filter: filter, title: title, suggestedName: nil)
    }

    /// `confirm` without a title.
    func confirm(_ message: String) async -> Bool {
        await confirm(message, title: nil)
    }

    /// `notify` with default severity (`info`) and no title.
    func notify(_ message: String) async {
        await notify(message, title: nil, severity: .info)
    }

    /// `notify` with explicit title but default severity (`info`).
    func notify(_ message: String, title: String?) async {
        await notify(message, title: title, severity: .info)
    }

    /// Default modal presentation preserves null-object safety. Host services
    /// override this method to bridge a modal VM to native UI.
    func present<M: ModalVM>(_ modalVM: M) async -> M.Result {
        modalVM.dismiss(modalVM.cancellationResult)
        return modalVM.cancellationResult
    }
}
