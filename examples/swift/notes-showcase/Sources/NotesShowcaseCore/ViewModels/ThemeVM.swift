//
// ThemeVM — Theme-as-a-VM for the Notes-Showcase Swift flagship.
//
// Scenario contract: spec/proposals/2026-06-02-theme-vm-scenario.md §4.
// THEME-001..005 conformance IDs — see spec/12-conformance.md §29.
//
// Architecture notes:
// - Extends `ComponentVMBase` from the VMx Swift library, publishing on the
//   base's now-`public` `hub` and firing the `propertyChanged` side-channel via
//   `_notifyPropertyChanged` (cross-module subclassing enabled by ADR-0066).
//
import Foundation
import Combine
import VMx

// MARK: - ThemeError

/// Domain error raised by `ThemeVM` when an unknown preset name is applied.
///
/// Used by `applyPreset(_:)` (THEME-002).
public enum ThemeError: Error, Equatable {
    /// The supplied preset name is not in the registry.
    case unknownPreset(String)
}

// MARK: - ThemeVM

/// Theme view-model for the Notes-Showcase Swift flagship.
///
/// Owns the current `ThemeModel`, exposes it via `currentTheme`, and routes
/// every user gesture through a small command surface that publishes a single
/// `ThemeChangedMessage` per effective change (equality-guarded).
///
/// Mirror of `ThemeVM` in the C# Avalonia flavor; follows Swift camelCase
/// idiom per ADR-0006.
public final class ThemeVM: ComponentVMBase {

    // ── Private state ──────────────────────────────────────────────────────

    /// The current model. Updated only through `setModel(_:)`.
    private var _model: ThemeModel

    /// Backing subject; drives `currentTheme` and `followsSystem`.
    private let _modelSubject: CurrentValueSubject<ThemeModel, Never>

    /// Optional host OS theme reader, wired by the builder.
    private let _systemThemeProvider: (() -> String)?

    // ── Public properties ──────────────────────────────────────────────────

    /// Ordered preset list: dark, light, high-contrast.
    /// A stable snapshot of `ThemeModel.presetOrder` taken at construction.
    public let presets: [ThemeModel]

    /// Derived property mirroring the full current `ThemeModel`.
    /// Backed by a `CurrentValueSubject` so `value` is always populated.
    public let currentTheme: DerivedProperty<ThemeModel>

    /// Derived property mirroring `ThemeModel.followsSystem`.
    public let followsSystem: DerivedProperty<Bool>

    // ── Commands ───────────────────────────────────────────────────────────

    /// Installs a named preset. Unknown names are silently swallowed in the
    /// command path; call `applyPreset(_:)` directly to receive the throw
    /// (THEME-002). Forces `followsSystem = false` (THEME-005).
    public private(set) var setThemeCommand: RelayCommandOf<String>

    /// Flips `highContrast`. Preserves accent and font scale (THEME-003).
    public private(set) var toggleHighContrast: RelayCommand

    /// Replaces `accentColor`. Argument is a hex string; no parsing performed.
    public private(set) var setAccentColor: RelayCommandOf<String>

    /// Sets `fontScaleFactor`, clamped to `[0.75, 1.75]` (THEME-004).
    public private(set) var setFontScale: RelayCommandOf<Double>

    /// Sets `followsSystem = true` and re-reads via the optional injected
    /// `systemThemeProvider` (THEME-005). When no provider is wired, only
    /// `followsSystem` changes.
    public private(set) var followSystemCommand: RelayCommand

    // ── Init ───────────────────────────────────────────────────────────────

    private init(
        name: String,
        hint: String,
        initialModel: ThemeModel,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        systemThemeProvider: (() -> String)?
    ) {
        // ── Phase 1: initialize all stored properties before super.init ────

        _model = initialModel
        _modelSubject = CurrentValueSubject(initialModel)
        _systemThemeProvider = systemThemeProvider
        presets = ThemeModel.presetOrder

        // DerivedProperty factories use CurrentValueSubject, which emits the
        // initial value synchronously on subscription — `value` is populated
        // by the time this initializer returns (DPROP-001).
        currentTheme = DerivedProperty<ThemeModel>.from(
            _modelSubject.eraseToAnyPublisher(),
            { $0 }
        )
        followsSystem = DerivedProperty<Bool>.from(
            _modelSubject.eraseToAnyPublisher(),
            { $0.followsSystem }
        )

        // Phase-1 placeholder commands (no-ops). Rewired in phase 2 below,
        // mirroring ComponentVMBase's own two-phase command initialisation.
        setThemeCommand = RelayCommandOf<String>(task: nil, predicate: nil, triggers: [])
        toggleHighContrast = RelayCommand(task: nil, predicate: nil, triggers: [])
        setAccentColor = RelayCommandOf<String>(task: nil, predicate: nil, triggers: [])
        setFontScale = RelayCommandOf<Double>(task: nil, predicate: nil, triggers: [])
        followSystemCommand = RelayCommand(task: nil, predicate: nil, triggers: [])

        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)

        // ── Phase 2: rewire commands with self-capturing closures ──────────
        // `self` is fully initialised at this point.

        setThemeCommand = RelayCommandOf<String>.builder()
            .task({ [weak self] n in try? self?.applyPreset(n) })
            .build()

        toggleHighContrast = RelayCommand.builder()
            .task({ [weak self] in self?.applyToggleHighContrast() })
            .build()

        setAccentColor = RelayCommandOf<String>.builder()
            .task({ [weak self] hex in self?.applySetAccentColor(hex) })
            .build()

        setFontScale = RelayCommandOf<Double>.builder()
            .task({ [weak self] scale in self?.applySetFontScale(scale) })
            .build()

        followSystemCommand = RelayCommand.builder()
            .task({ [weak self] in self?.applyFollowSystem() })
            .build()
    }

    // ── Public throwing API ────────────────────────────────────────────────

    /// Applies a named preset. Forces `followsSystem = false`.
    ///
    /// - Throws: `ThemeError.unknownPreset` when `presetName` is not in the
    ///   registry — without publishing a `ThemeChangedMessage` (THEME-002).
    ///
    /// `setThemeCommand` wraps this with `try?`, swallowing the error in the
    /// command path; call this method directly when the throw is needed.
    public func applyPreset(_ presetName: String) throws {
        guard let preset = ThemeModel.presets[presetName] else {
            throw ThemeError.unknownPreset(presetName)
        }
        setModel(ThemeModel(
            name: preset.name,
            accentColor: preset.accentColor,
            fontScaleFactor: preset.fontScaleFactor,
            highContrast: preset.highContrast,
            followsSystem: false
        ))
    }

    // ── Private command implementations ────────────────────────────────────

    private func applyToggleHighContrast() {
        setModel(ThemeModel(
            name: _model.name,
            accentColor: _model.accentColor,
            fontScaleFactor: _model.fontScaleFactor,
            highContrast: !_model.highContrast,
            followsSystem: _model.followsSystem
        ))
    }

    private func applySetAccentColor(_ hex: String) {
        setModel(ThemeModel(
            name: _model.name,
            accentColor: hex,
            fontScaleFactor: _model.fontScaleFactor,
            highContrast: _model.highContrast,
            followsSystem: _model.followsSystem
        ))
    }

    private func applySetFontScale(_ scale: Double) {
        setModel(ThemeModel(
            name: _model.name,
            accentColor: _model.accentColor,
            fontScaleFactor: ThemeModel.clampFontScale(scale),
            highContrast: _model.highContrast,
            followsSystem: _model.followsSystem
        ))
    }

    private func applyFollowSystem() {
        if let systemName = _systemThemeProvider?(),
           let preset = ThemeModel.presets[systemName] {
            setModel(ThemeModel(
                name: preset.name,
                accentColor: preset.accentColor,
                fontScaleFactor: preset.fontScaleFactor,
                highContrast: preset.highContrast,
                followsSystem: true
            ))
        } else {
            setModel(ThemeModel(
                name: _model.name,
                accentColor: _model.accentColor,
                fontScaleFactor: _model.fontScaleFactor,
                highContrast: _model.highContrast,
                followsSystem: true
            ))
        }
    }

    // ── Single mutation site ───────────────────────────────────────────────

    /// The ONLY place that updates `_model`, drives `_modelSubject`, and
    /// sends `ThemeChangedMessage`. Equality-guarded: an equal value is a
    /// no-op (no emission).
    private func setModel(_ newModel: ThemeModel) {
        guard _model != newModel else { return }
        let previous = _model
        _model = newModel
        _modelSubject.send(newModel)
        // Standard INPC channel (matches the C# SetModel order: model subject →
        // PropertyChangedMessage → propertyChanged → ThemeChangedMessage).
        _notifyPropertyChanged("model")
        hub.send(ThemeChangedMessage(
            sender: self,
            senderName: name,
            previous: previous,
            current: newModel
        ))
    }

    // ── Dispose ────────────────────────────────────────────────────────────

    override public func _onDispose() {
        currentTheme.dispose()
        followsSystem.dispose()
        _modelSubject.send(completion: .finished)
        setThemeCommand.dispose()
        toggleHighContrast.dispose()
        setAccentColor.dispose()
        setFontScale.dispose()
        followSystemCommand.dispose()
        super._onDispose()
    }

    // ── Builder ────────────────────────────────────────────────────────────

    /// Returns a new empty builder for `ThemeVM`.
    public static func builder() -> ThemeVMBuilder {
        ThemeVMBuilder()
    }

    /// Immutable fluent builder for `ThemeVM` (spec ch. 10).
    ///
    /// Required fields: `name`, `services(hub:dispatcher:)`.
    /// Optional fields: `initialModel` (defaults to `ThemeModel.DARK_PRESET`),
    /// `systemThemeProvider`.
    public struct ThemeVMBuilder {
        private var _name: String?
        private var _hint: String = ""
        private var _initialModel: ThemeModel?
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _systemThemeProvider: (() -> String)?

        fileprivate init() {}

        /// Sets the required `name`.
        public func name(_ value: String) -> ThemeVMBuilder {
            var copy = self; copy._name = value; return copy
        }

        /// Sets the optional `hint`.
        public func hint(_ value: String) -> ThemeVMBuilder {
            var copy = self; copy._hint = value; return copy
        }

        /// Sets the required services (hub + dispatcher).
        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> ThemeVMBuilder {
            var copy = self
            copy._hub = hub
            copy._dispatcher = dispatcher
            return copy
        }

        /// Sets the optional initial model. Defaults to `ThemeModel.DARK_PRESET`.
        public func initialModel(_ model: ThemeModel) -> ThemeVMBuilder {
            var copy = self; copy._initialModel = model; return copy
        }

        /// Sets the optional OS-theme provider. Invoked by `followSystemCommand`
        /// to read the current host theme name (must be a preset key, otherwise
        /// only `followsSystem` is flipped).
        public func systemThemeProvider(_ provider: @escaping () -> String) -> ThemeVMBuilder {
            var copy = self; copy._systemThemeProvider = provider; return copy
        }

        /// Validates required fields and constructs a `ThemeVM`.
        ///
        /// - Throws: `BuilderValidationError` if `name` or `services` are missing.
        public func build() throws -> ThemeVM {
            guard let name = _name else {
                throw BuilderValidationError(missingField: "name")
            }
            guard let hub = _hub else {
                throw BuilderValidationError(missingField: "hub")
            }
            guard let dispatcher = _dispatcher else {
                throw BuilderValidationError(missingField: "dispatcher")
            }
            return ThemeVM(
                name: name,
                hint: _hint,
                initialModel: _initialModel ?? ThemeModel.DARK_PRESET,
                hub: hub,
                dispatcher: dispatcher,
                systemThemeProvider: _systemThemeProvider
            )
        }
    }
}
