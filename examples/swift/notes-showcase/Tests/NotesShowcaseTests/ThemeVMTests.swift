import XCTest
import Combine
import VMx
@testable import NotesShowcaseCore

// MARK: - Recorder

/// Reference-type recorder for `ThemeChangedMessage`s published on the hub.
///
/// Storing the `AnyCancellable` inside the recorder ensures the subscription
/// lives exactly as long as the recorder itself — no manual cancellable
/// management in each test body.
private final class ThemeRecorder {
    var messages: [ThemeChangedMessage] = []
    var cancellables = Set<AnyCancellable>()
}

// MARK: - ThemeVMTests

final class ThemeVMTests: XCTestCase {

    // MARK: - Helpers

    /// Builds and constructs a fresh `ThemeVM` on a dedicated `MessageHub`.
    ///
    /// `initial` defaults to `ThemeModel.LIGHT_PRESET` to mirror the C#
    /// test helper convention. The builder default (`DARK_PRESET`) is
    /// intentionally overridden here.
    private func build(
        initial: ThemeModel? = nil,
        systemThemeProvider: (() -> String)? = nil
    ) throws -> (ThemeVM, MessageHub) {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        var b = ThemeVM.builder()
            .name("theme")
            .services(hub: hub, dispatcher: dispatcher)
            .initialModel(initial ?? ThemeModel.LIGHT_PRESET)
        if let provider = systemThemeProvider {
            b = b.systemThemeProvider(provider)
        }
        let vm = try b.build()
        try vm.construct()
        return (vm, hub)
    }

    /// Subscribes a `ThemeRecorder` to all `ThemeChangedMessage`s on `hub`.
    /// The subscription is retained inside the recorder.
    private func capture(_ hub: MessageHub) -> ThemeRecorder {
        let recorder = ThemeRecorder()
        hub.messages
            .compactMap { $0 as? ThemeChangedMessage }
            .sink { [weak recorder] msg in recorder?.messages.append(msg) }
            .store(in: &recorder.cancellables)
        return recorder
    }

    // MARK: - THEME-001

    /// THEME-001 — `setThemeCommand.execute("dark")` publishes exactly one
    /// `ThemeChangedMessage`; `previous` equals `LIGHT_PRESET`; `current.name`
    /// and `current.accentColor` match the "dark" preset; `currentTheme.value`
    /// reflects the new state with `followsSystem == false`.
    func testTHEME001_SetThemeCommand_dark_publishes_ThemeChangedMessage() throws {
        let (vm, hub) = try build(initial: ThemeModel.LIGHT_PRESET)
        let recorder = capture(hub)

        vm.setThemeCommand.execute("dark")

        XCTAssertEqual(recorder.messages.count, 1)
        let msg = try XCTUnwrap(recorder.messages.first)
        XCTAssertEqual(msg.previous, ThemeModel.LIGHT_PRESET)
        XCTAssertEqual(msg.current.name, "dark")
        XCTAssertEqual(msg.current.accentColor, ThemeModel.DARK_PRESET.accentColor)
        XCTAssertEqual(try vm.currentTheme.value.name, "dark")
        XCTAssertFalse(try vm.currentTheme.value.followsSystem)
    }

    // MARK: - THEME-002

    /// THEME-002 — `applyPreset("unknown-preset")` throws without publishing a
    /// message; the model is unchanged after the throw.
    func testTHEME002_Unknown_preset_throws_without_publishing_a_message() throws {
        let (vm, hub) = try build()
        let recorder = capture(hub)
        let before = try vm.currentTheme.value

        XCTAssertThrowsError(try vm.applyPreset("unknown-preset"))

        XCTAssertTrue(recorder.messages.isEmpty)
        XCTAssertEqual(try vm.currentTheme.value, before)
    }

    // MARK: - THEME-003

    /// THEME-003 — `toggleHighContrast` flips `highContrast` and preserves
    /// accent color, font scale, and preset name.
    func testTHEME003_ToggleHighContrast_preserves_accent_and_scale() throws {
        let custom = ThemeModel(
            name: ThemeModel.LIGHT_PRESET.name,
            accentColor: "#ABCDEF",
            fontScaleFactor: 1.25,
            highContrast: ThemeModel.LIGHT_PRESET.highContrast,
            followsSystem: ThemeModel.LIGHT_PRESET.followsSystem
        )
        let (vm, hub) = try build(initial: custom)
        let recorder = capture(hub)

        vm.toggleHighContrast.execute()

        XCTAssertEqual(recorder.messages.count, 1)
        XCTAssertTrue(try vm.currentTheme.value.highContrast)
        XCTAssertEqual(try vm.currentTheme.value.accentColor, "#ABCDEF")
        XCTAssertEqual(try vm.currentTheme.value.fontScaleFactor, 1.25)
        XCTAssertEqual(try vm.currentTheme.value.name, "light")
    }

    // MARK: - THEME-004

    /// THEME-004 — `setFontScale` clamps a value below the floor to 0.75.
    func testTHEME004_SetFontScale_clamps_below_floor() throws {
        let (vm, hub) = try build()
        let recorder = capture(hub)

        vm.setFontScale.execute(0.1)

        XCTAssertEqual(recorder.messages.count, 1)
        XCTAssertEqual(try vm.currentTheme.value.fontScaleFactor, ThemeModel.minFontScale)
    }

    /// THEME-004 — `setFontScale` clamps a value above the ceiling to 1.75.
    func testTHEME004_SetFontScale_clamps_above_ceiling() throws {
        let (vm, hub) = try build()
        let recorder = capture(hub)

        vm.setFontScale.execute(99.0)

        XCTAssertEqual(recorder.messages.count, 1)
        XCTAssertEqual(try vm.currentTheme.value.fontScaleFactor, ThemeModel.maxFontScale)
    }

    /// THEME-004 — `setFontScale` keeps an in-range value unchanged.
    func testTHEME004_SetFontScale_in_range_keeps_value() throws {
        let (vm, _) = try build()

        vm.setFontScale.execute(1.5)

        XCTAssertEqual(try vm.currentTheme.value.fontScaleFactor, 1.5)
    }

    // MARK: - THEME-005

    /// THEME-005 — `followSystemCommand` sets `followsSystem = true` and reads
    /// the host theme; subsequent `setThemeCommand` resets `followsSystem` to
    /// false.
    func testTHEME005_FollowSystemCommand_then_SetTheme_resets_followsSystem() throws {
        let (vm, _) = try build(
            initial: ThemeModel.LIGHT_PRESET,
            systemThemeProvider: { "dark" }
        )

        vm.followSystemCommand.execute()

        XCTAssertTrue(try vm.currentTheme.value.followsSystem)
        XCTAssertEqual(try vm.currentTheme.value.name, "dark")

        vm.setThemeCommand.execute("light")

        XCTAssertFalse(try vm.currentTheme.value.followsSystem)
        XCTAssertEqual(try vm.currentTheme.value.name, "light")
    }

    // MARK: - Sanity

    /// Sanity — `presets` exposes exactly 3 models in registry order:
    /// dark, light, high-contrast.
    func testPresets_exposes_three_named_models_in_registry_order() throws {
        let (vm, _) = try build()

        XCTAssertEqual(vm.presets.count, 3)
        XCTAssertEqual(vm.presets[0].name, "dark")
        XCTAssertEqual(vm.presets[1].name, "light")
        XCTAssertEqual(vm.presets[2].name, "high-contrast")
    }
}
