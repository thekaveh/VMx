using System;
using System.Collections.Generic;
using System.Reactive.Subjects;
using System.Windows.Input;
using NotesShowcase.Messages;
using NotesShowcase.Models;
using VMx.Builders;
using VMx.Commands;
using VMx.Components;
using VMx.Messages;
using VMx.Properties;
using VMx.Services;

namespace NotesShowcase.ViewModels;

/// <summary>
/// Theme-as-a-VM seam for the Notes-Showcase app.
///
/// Implements the scenario contract in
/// <c>spec/proposals/2026-06-02-theme-vm-scenario.md</c> §4: the VM owns the
/// current <see cref="ThemeModel"/>, exposes it via
/// <see cref="CurrentTheme"/>, and routes every user gesture through a small
/// command surface that publishes a single <see cref="ThemeChangedMessage"/>
/// per effective change.
///
/// <para>
/// <b>Wire-up status (VMX-129).</b> This VM is the theme seam for the C#
/// flagship. It is composed into <see cref="WorkspaceVM"/> as a workspace-owned
/// sibling of the six aggregate children (not a seventh aggregate child —
/// that would require an <c>AggregateVM7</c> in the core library, which ADR-0058
/// declined). The workspace drives its lifecycle (Construct/Destruct/Dispose)
/// and the Avalonia <c>ThemeAdapter</c> is bound to it at composition time
/// (<see cref="App"/>), so the THEME-001..005 scenario is exercised in the
/// running app.
/// </para>
///
/// <para>
/// Per ADR-0006 the public surface is PascalCase
/// (<see cref="SetThemeCommand"/>, <see cref="SetFontScale"/>, etc.); the
/// other flavors mirror this shape under their own idiomatic casing.
/// </para>
/// </summary>
public sealed class ThemeVM : ComponentVMBase
{
    private readonly BehaviorSubject<ThemeModel> _modelSubject;
    private readonly IReadOnlyList<ThemeModel> _presets;
    private readonly Func<string>? _systemThemeProvider;

    private ThemeModel _model;

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Component;

    /// <summary>Public hub accessor — mirrors the other example VMs.</summary>
    public new IMessageHub Hub => base.Hub;

    /// <summary>
    /// The current model, equality-guarded. Setting an equal value is a
    /// no-op (no <see cref="ThemeChangedMessage"/> emission). Every other
    /// mutator routes through this setter, so it is the single emission
    /// site for the change event.
    /// </summary>
    public ThemeModel Model
    {
        get => _model;
        set => SetModel(value);
    }

    /// <summary>
    /// Derived property mirroring <see cref="Model"/>. Adapter layers and
    /// tests subscribe to <see cref="DerivedProperty{T}.ValueChanged"/> here
    /// rather than reading <see cref="Model"/> directly — matches the
    /// scenario contract §4 (conformance routes through <c>currentTheme</c>).
    /// </summary>
    public DerivedProperty<ThemeModel> CurrentTheme { get; }

    /// <summary>
    /// Named presets the VM is willing to install. The list is a stable
    /// snapshot of <see cref="ThemeModel.Presets"/> in registry order
    /// (dark, light, high-contrast).
    /// </summary>
    public IReadOnlyList<ThemeModel> Presets => _presets;

    /// <summary>Derived property mirroring <see cref="ThemeModel.FollowsSystem"/>.</summary>
    public DerivedProperty<bool> FollowsSystem { get; }

    /// <summary>
    /// Installs the named preset. Parameter is the preset name (one of
    /// <c>"dark"</c>, <c>"light"</c>, <c>"high-contrast"</c>). An unknown
    /// name throws <see cref="ArgumentException"/> WITHOUT publishing a
    /// <see cref="ThemeChangedMessage"/> (THEME-002). Also flips
    /// <see cref="ThemeModel.FollowsSystem"/> off (THEME-005).
    /// </summary>
    public ICommand SetThemeCommand { get; }

    /// <summary>
    /// Flips <see cref="ThemeModel.HighContrast"/>. Preserves accent and
    /// font scale (THEME-003).
    /// </summary>
    public ICommand ToggleHighContrast { get; }

    /// <summary>
    /// Replaces <see cref="ThemeModel.AccentColor"/>. Argument is a hex
    /// string; no parsing is performed — the adapter layer interprets it
    /// per framework.
    /// </summary>
    public ICommand SetAccentColor { get; }

    /// <summary>
    /// Sets <see cref="ThemeModel.FontScaleFactor"/>, clamped to
    /// <c>[0.75, 1.75]</c> (THEME-004).
    /// </summary>
    public ICommand SetFontScale { get; }

    /// <summary>
    /// Sets <see cref="ThemeModel.FollowsSystem"/> to true and re-reads the
    /// host's current theme via the optional
    /// <c>SystemThemeProvider</c> delegate (THEME-005). When no provider is
    /// wired, the call leaves <see cref="ThemeModel.Name"/> unchanged.
    /// </summary>
    public ICommand FollowSystemCommand { get; }

    private ThemeVM(
        string name,
        string hint,
        ThemeModel initialModel,
        IMessageHub hub,
        IDispatcher dispatcher,
        Func<string>? systemThemeProvider)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _model = initialModel;
        _modelSubject = new BehaviorSubject<ThemeModel>(initialModel);
        _systemThemeProvider = systemThemeProvider;

        // Registry-order snapshot so consumers can render a stable picker.
        var presetsList = new List<ThemeModel>(ThemeModel.Presets.Count);
        foreach (var kv in ThemeModel.Presets) presetsList.Add(kv.Value);
        _presets = presetsList;

        CurrentTheme = DerivedProperty.From<ThemeModel, ThemeModel>(
            _modelSubject,
            m => m);
        FollowsSystem = DerivedProperty.From<ThemeModel, bool>(
            _modelSubject,
            m => m.FollowsSystem);

        SetThemeCommand = RelayCommand<string>.Builder()
            .Task(ApplyPreset)
            .Build();
        ToggleHighContrast = RelayCommand.Builder()
            .Task(ApplyToggleHighContrast)
            .Build();
        SetAccentColor = RelayCommand<string>.Builder()
            .Task(ApplySetAccentColor)
            .Build();
        SetFontScale = RelayCommand<double>.Builder()
            .Task(ApplySetFontScale)
            .Build();
        FollowSystemCommand = RelayCommand.Builder()
            .Task(ApplyFollowSystem)
            .Build();
    }

    private void ApplyPreset(string presetName)
    {
        if (presetName is null)
            throw new ArgumentNullException(nameof(presetName));
        if (!ThemeModel.Presets.TryGetValue(presetName, out var preset))
            throw new ArgumentException(
                $"Unknown theme preset: '{presetName}'. Known: dark, light, high-contrast.",
                nameof(presetName));
        // Adopt the preset's name + flags but preserve user-chosen accent
        // and scale ONLY for the system pseudo-transition; explicit preset
        // selection replaces the full surface and forces followsSystem=false.
        SetModel(preset with { FollowsSystem = false });
    }

    private void ApplyToggleHighContrast()
    {
        SetModel(_model with { HighContrast = !_model.HighContrast });
    }

    private void ApplySetAccentColor(string hex)
    {
        if (hex is null)
            throw new ArgumentNullException(nameof(hex));
        SetModel(_model with { AccentColor = hex });
    }

    private void ApplySetFontScale(double scale)
    {
        var clamped = ThemeModel.ClampFontScale(scale);
        SetModel(_model with { FontScaleFactor = clamped });
    }

    private void ApplyFollowSystem()
    {
        var systemName = _systemThemeProvider?.Invoke();
        if (systemName is not null && ThemeModel.Presets.TryGetValue(systemName, out var preset))
        {
            SetModel(preset with { FollowsSystem = true });
        }
        else
        {
            SetModel(_model with { FollowsSystem = true });
        }
    }

    private void SetModel(ThemeModel value)
    {
        if (EqualityComparer<ThemeModel>.Default.Equals(_model, value)) return;
        var previous = _model;
        _model = value;

        // Drive the DerivedProperty observers.
        _modelSubject.OnNext(value);

        // INPC + hub PropertyChanged for the modeled property.
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Model)));
        RaisePropertyChanged(nameof(Model));

        // Custom event per scenario §4.
        Hub.Send(new ThemeChangedMessage(this, Name, previous, value));
    }

    /// <inheritdoc/>
    protected override void OnDispose()
    {
        CurrentTheme.Dispose();
        FollowsSystem.Dispose();
        _modelSubject.OnCompleted();
        _modelSubject.Dispose();
        (SetThemeCommand as IDisposable)?.Dispose();
        (ToggleHighContrast as IDisposable)?.Dispose();
        (SetAccentColor as IDisposable)?.Dispose();
        (SetFontScale as IDisposable)?.Dispose();
        (FollowSystemCommand as IDisposable)?.Dispose();
        base.OnDispose();
    }

    /// <summary>Returns a new empty builder for <see cref="ThemeVM"/>.</summary>
    public static ThemeVMBuilder Builder() => ThemeVMBuilder.Empty;

    /// <summary>Immutable fluent builder for <see cref="ThemeVM"/> (spec ch. 10).</summary>
    public sealed class ThemeVMBuilder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly ThemeModel? _initialModel;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly Func<string>? _systemThemeProvider;

        internal static readonly ThemeVMBuilder Empty = new();

        private ThemeVMBuilder()
        {
            _hint = "";
        }

        private ThemeVMBuilder(
            string? name,
            string hint,
            ThemeModel? initialModel,
            IMessageHub? hub,
            IDispatcher? dispatcher,
            Func<string>? systemThemeProvider)
        {
            _name = name;
            _hint = hint;
            _initialModel = initialModel;
            _hub = hub;
            _dispatcher = dispatcher;
            _systemThemeProvider = systemThemeProvider;
        }

        /// <summary>Sets the required Name.</summary>
        public ThemeVMBuilder Name(string name)
            => new(name, _hint, _initialModel, _hub, _dispatcher, _systemThemeProvider);

        /// <summary>Sets the optional Hint.</summary>
        public ThemeVMBuilder Hint(string hint)
            => new(_name, hint, _initialModel, _hub, _dispatcher, _systemThemeProvider);

        /// <summary>
        /// Sets the optional initial theme model. Defaults to
        /// <see cref="ThemeModel.DARK_PRESET"/> to match the app's
        /// <c>App.axaml</c> declaration.
        /// </summary>
        public ThemeVMBuilder InitialModel(ThemeModel model)
            => new(_name, _hint, model, _hub, _dispatcher, _systemThemeProvider);

        /// <summary>Sets the required Services (hub + dispatcher).</summary>
        public ThemeVMBuilder Services(IMessageHub hub, IDispatcher dispatcher)
            => new(_name, _hint, _initialModel, hub, dispatcher, _systemThemeProvider);

        /// <summary>
        /// Sets the optional OS-theme provider. Invoked by
        /// <see cref="FollowSystemCommand"/> to learn the current host theme
        /// name (must be one of the preset keys, else the call leaves the
        /// preset name unchanged and only flips <see cref="ThemeModel.FollowsSystem"/>).
        /// </summary>
        public ThemeVMBuilder SystemThemeProvider(Func<string> provider)
            => new(_name, _hint, _initialModel, _hub, _dispatcher, provider);

        /// <summary>Builds the VM after validating required fields.</summary>
        public ThemeVM Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            var initial = _initialModel ?? ThemeModel.DARK_PRESET;
            return new ThemeVM(_name!, _hint, initial, _hub!, _dispatcher!, _systemThemeProvider);
        }
    }
}
