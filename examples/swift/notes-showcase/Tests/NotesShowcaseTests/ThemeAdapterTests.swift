import XCTest
import SwiftUI
import VMx
@testable import NotesShowcase
@testable import NotesShowcaseCore

final class ThemeAdapterTests: XCTestCase {
    func testIndependentHighContrastFlagProjectsBlackWhitePalette() throws {
        let initial = ThemeModel(
            name: "light",
            accentColor: "#ABCDEF",
            fontScaleFactor: 1.0,
            highContrast: true,
            followsSystem: false
        )
        let vm = try ThemeVM.builder()
            .name("theme")
            .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            .initialModel(initial)
            .build()
        try vm.construct()

        let adapter = ThemeAdapter(themeVM: vm)

        XCTAssertEqual(adapter.background, Color.black)
        XCTAssertEqual(adapter.pane, Color.black)
        XCTAssertEqual(adapter.textDim, Color.white)
        vm.dispose()
    }
}
