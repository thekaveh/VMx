//
// DialogServiceTests — DIA-001..005: DialogService contract + NullDialogService.
//
// See spec/19-dialogs.md and ADR-0029.
// Ports langs/typescript/tests/conformance/dia-001-to-008-dialog-service.test.ts (DIA-001..005).
//
import XCTest
@testable import VMx

/// DIA-003 test double: records the title of each `confirm` call.
/// It always returns false. The tests do not check that result.
private final class TitleRecordingDialogService: DialogService {
    private(set) var titles: [String?] = []

    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? { nil }
    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? { nil }
    func notify(_ message: String, title: String?, severity: NotificationSeverity) async {}
    func confirm(_ message: String, title: String?) async -> Bool {
        titles.append(title)
        return false
    }
}

final class DialogServiceTests: XCTestCase {

    // MARK: - DIA-001

    /// DIA-001 — `pickFileToOpen` returns nil in the null impl; all params optional.
    func testDia001PickFileToOpenReturnsNil() async {
        let sut: any DialogService = NullDialogService.INSTANCE

        // No arguments (convenience overload).
        let r1 = await sut.pickFileToOpen()
        // Explicit nil filter and title.
        let r2 = await sut.pickFileToOpen(filter: nil, title: nil)
        // Full arguments with a real filter.
        let r3 = await sut.pickFileToOpen(
            filter: FileFilter(description: "Images", extensions: ["*.png", "*.jpg"]),
            title: "Open image"
        )

        XCTAssertNil(r1)
        XCTAssertNil(r2)
        XCTAssertNil(r3)
    }

    // MARK: - DIA-002

    /// DIA-002 — `pickFileToSave` returns nil in the null impl; all params optional.
    func testDia002PickFileToSaveReturnsNil() async {
        let sut: any DialogService = NullDialogService.INSTANCE

        // No arguments (convenience overload).
        let r1 = await sut.pickFileToSave()
        // Explicit nils for all three params.
        let r2 = await sut.pickFileToSave(filter: nil, title: nil, suggestedName: nil)
        // Full arguments with a real filter.
        let r3 = await sut.pickFileToSave(
            filter: FileFilter(description: "Text files", extensions: ["*.txt"]),
            title: "Save as",
            suggestedName: "output.txt"
        )

        XCTAssertNil(r1)
        XCTAssertNil(r2)
        XCTAssertNil(r3)
    }

    // MARK: - DIA-003

    /// DIA-003 — `confirm` returns false in the null impl (safest default).
    func testDia003ConfirmReturnsFalse() async {
        let sut: any DialogService = NullDialogService.INSTANCE

        // Without title (convenience overload).
        let r1 = await sut.confirm("Are you sure?")
        // With explicit title.
        let r2 = await sut.confirm("Delete this item?", title: "Confirm delete")

        XCTAssertFalse(r1)
        XCTAssertFalse(r2)
    }

    /// DIA-003 — `confirm(_:)` forwards `title: nil`; `confirm(_:title:)` forwards the given title.
    func testDia003ConfirmForwardsTitle() async {
        let sut = TitleRecordingDialogService()

        // The library extension supplies `confirm(_:)`. It must forward a nil title.
        _ = await sut.confirm("Proceed?")
        _ = await sut.confirm("Proceed?", title: "Confirm")

        XCTAssertEqual(sut.titles, [nil, "Confirm"])
    }

    // MARK: - DIA-004

    /// DIA-004 — `notify` completes without error for all severities.
    func testDia004NotifyCompletesForAllSeverities() async {
        let sut: any DialogService = NullDialogService.INSTANCE

        // Default severity (info) via convenience overload — no arguments beyond message.
        await sut.notify("Hello")

        // Explicit severities.
        let severities: [NotificationSeverity] = [.info, .warning, .error]
        for sev in severities {
            await sut.notify("msg", title: "title", severity: sev)
        }
        // Reaching here without trap/throw satisfies the contract.
    }

    // MARK: - DIA-005

    /// DIA-005 — `NullDialogService`: `pickFile*` returns nil; `confirm` returns false; `notify` no-op.
    func testDia005NullDialogServiceAllDefaults() async {
        let sut = NullDialogService.INSTANCE

        let openResult = await sut.pickFileToOpen()
        let saveResult = await sut.pickFileToSave()
        let confirmResult = await sut.confirm("msg")
        // notify must complete without throwing or trapping.
        await sut.notify("msg")

        XCTAssertNil(openResult)
        XCTAssertNil(saveResult)
        XCTAssertFalse(confirmResult)
        // Reaching here without error is the DIA-005 contract for notify.
    }
}
