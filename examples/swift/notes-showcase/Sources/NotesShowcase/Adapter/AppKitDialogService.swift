//
// AppKitDialogService — native macOS implementation of VMx DialogService.
//
// Keeps the reusable NotesShowcaseCore target UI-agnostic while the SwiftUI
// app target provides real file, confirm, and notify dialogs.
//
import AppKit
import UniformTypeIdentifiers
import VMx

final class AppKitDialogService: DialogService {
    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? {
        await MainActor.run {
            let panel = NSOpenPanel()
            panel.title = title ?? "Open"
            panel.canChooseFiles = true
            panel.canChooseDirectories = false
            panel.allowsMultipleSelection = false
            panel.allowedContentTypes = Self.contentTypes(from: filter)
            return panel.runModal() == .OK ? panel.url?.path : nil
        }
    }

    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? {
        await MainActor.run {
            let panel = NSSavePanel()
            panel.title = title ?? "Save"
            panel.nameFieldStringValue = suggestedName ?? ""
            panel.allowedContentTypes = Self.contentTypes(from: filter)
            return panel.runModal() == .OK ? panel.url?.path : nil
        }
    }

    func confirm(_ message: String, title: String?) async -> Bool {
        await MainActor.run {
            let alert = NSAlert()
            alert.messageText = title ?? "Confirm"
            alert.informativeText = message
            alert.alertStyle = .warning
            alert.addButton(withTitle: "Yes")
            alert.addButton(withTitle: "No")
            return alert.runModal() == .alertFirstButtonReturn
        }
    }

    func notify(_ message: String, title: String?, severity: NotificationSeverity) async {
        await MainActor.run {
            let alert = NSAlert()
            alert.messageText = title ?? Self.defaultTitle(for: severity)
            alert.informativeText = message
            alert.alertStyle = Self.alertStyle(for: severity)
            alert.addButton(withTitle: "OK")
            alert.runModal()
        }
    }

    private static func contentTypes(from filter: FileFilter?) -> [UTType] {
        guard let filter else { return [] }
        return filter.extensions.compactMap { pattern in
            let ext = pattern
                .replacingOccurrences(of: "*.", with: "")
                .replacingOccurrences(of: ".", with: "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return ext.isEmpty ? nil : UTType(filenameExtension: ext)
        }
    }

    private static func defaultTitle(for severity: NotificationSeverity) -> String {
        switch severity {
        case .info:
            return "Notice"
        case .warning:
            return "Warning"
        case .error:
            return "Error"
        }
    }

    private static func alertStyle(for severity: NotificationSeverity) -> NSAlert.Style {
        switch severity {
        case .info:
            return .informational
        case .warning:
            return .warning
        case .error:
            return .critical
        }
    }
}
