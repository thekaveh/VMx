using VMx.Builders;
using VMx.Services;

namespace VMx.Components;

/// <summary>
/// Immutable fluent builder for <see cref="ComponentVM{M}"/>.
/// Each setter returns a NEW builder instance (BLD-001).
/// Use <c>ComponentVM&lt;M&gt;.Builder()</c> to start.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public sealed class ComponentVMBuilder<M>
{
    // ── Required fields (null means unset) ──────────────────────────────────
    private readonly string? _name;
    private readonly M? _model;
    private readonly bool _modelSet;
    private readonly IMessageHub? _hub;
    private readonly IDispatcher? _dispatcher;

    // ── Optional fields ──────────────────────────────────────────────────────
    private readonly string _hint;
    private readonly ViewModelType _type;
    private readonly Func<M, string> _modeledHinter;
    private readonly Action<M>? _onModelChanged;
    private readonly Action? _onConstruct;
    private readonly Action? _onDestruct;
    private readonly bool _background;
    private readonly IParentCompositeVM? _parent;

    /// <summary>Represents an empty, unconfigured builder.</summary>
    public static readonly ComponentVMBuilder<M> Empty = new();

    private ComponentVMBuilder()
    {
        _hint = "";
        _type = ViewModelType.Component;
        _modeledHinter = _ => "";
        _model = default;
        _modelSet = false;
    }

    // Private copy constructor used by setter methods.
    private ComponentVMBuilder(
        string? name,
        M? model,
        bool modelSet,
        IMessageHub? hub,
        IDispatcher? dispatcher,
        string hint,
        ViewModelType type,
        Func<M, string> modeledHinter,
        Action<M>? onModelChanged,
        Action? onConstruct,
        Action? onDestruct,
        bool background,
        IParentCompositeVM? parent)
    {
        _name = name;
        _model = model;
        _modelSet = modelSet;
        _hub = hub;
        _dispatcher = dispatcher;
        _hint = hint;
        _type = type;
        _modeledHinter = modeledHinter;
        _onModelChanged = onModelChanged;
        _onConstruct = onConstruct;
        _onDestruct = onDestruct;
        _background = background;
        _parent = parent;
    }

    // ── Fluent setters (each returns a new instance) ─────────────────────────

    /// <summary>Sets the required Name field.</summary>
    public ComponentVMBuilder<M> Name(string name) => With(name: name);

    /// <summary>Sets the optional Hint field (default: empty string).</summary>
    public ComponentVMBuilder<M> Hint(string hint) => With(hint: hint);

    /// <summary>Sets the optional Type field (default: Component).</summary>
    public ComponentVMBuilder<M> Type(ViewModelType type) => With(type: type);

    /// <summary>Sets the required Model field.</summary>
    public ComponentVMBuilder<M> Model(M model) => With(model: model, modelSet: true);

    /// <summary>Sets the optional ModeledHinter function (default: _ => "").</summary>
    public ComponentVMBuilder<M> ModeledHinter(Func<M, string> hinter) => With(modeledHinter: hinter);

    /// <summary>Sets the optional OnModelChanged callback.</summary>
    public ComponentVMBuilder<M> OnModelChanged(Action<M> callback) => With(onModelChanged: callback);

    /// <summary>Sets the optional OnConstruct lifecycle callback.</summary>
    public ComponentVMBuilder<M> OnConstruct(Action callback) => With(onConstruct: callback);

    /// <summary>Sets the optional OnDestruct lifecycle callback.</summary>
    public ComponentVMBuilder<M> OnDestruct(Action callback) => With(onDestruct: callback);

    /// <summary>Sets the optional Background flag (default: false).</summary>
    public ComponentVMBuilder<M> Background(bool background) => With(background: background);

    /// <summary>Sets the required Services (hub + dispatcher).</summary>
    public ComponentVMBuilder<M> Services(IMessageHub hub, IDispatcher dispatcher)
        => With(hub: hub, dispatcher: dispatcher);

    internal ComponentVMBuilder<M> OptionHub(IMessageHub hub) => With(hub: hub);

    internal ComponentVMBuilder<M> OptionDispatcher(IDispatcher dispatcher)
        => With(dispatcher: dispatcher);

    /// <summary>
    /// Sets the required Services by resolving <see cref="IMessageHub"/> and
    /// <see cref="IDispatcher"/> from <paramref name="serviceProvider"/> (VMX-021).
    /// Use with <c>services.AddVMx()</c>.
    /// </summary>
    public ComponentVMBuilder<M> Services(IServiceProvider serviceProvider)
    {
        var (hub, dispatcher) = BuilderServices.Resolve(serviceProvider);
        return With(hub: hub, dispatcher: dispatcher);
    }

    /// <summary>Sets the optional parent composite (internal: used by CompositeVMBase).</summary>
    internal ComponentVMBuilder<M> Parent(IParentCompositeVM parent) => With(parent: parent);

    /// <summary>
    /// Validates required fields and constructs a <see cref="ComponentVM{M}"/>.
    /// Throws <see cref="BuilderValidationException"/> if a required field is missing.
    /// </summary>
    public ComponentVM<M> Build()
    {
        BuilderValidationException.Require(_name, "Name");
        if (!_modelSet) throw new BuilderValidationException("Model");
        BuilderValidationException.Require(_hub, "Hub");
        BuilderValidationException.Require(_dispatcher, "Dispatcher");

        var vm = ComponentVM<M>.Create(
            _name,
            _hint,
            _type,
            _model!,
            _modeledHinter,
            _onModelChanged,
            _hub,
            _dispatcher,
            _onConstruct,
            _onDestruct,
            _background);

        if (_parent is not null)
            vm.Parent = _parent;

        return vm;
    }

    // ── Private clone helper ─────────────────────────────────────────────────
    private ComponentVMBuilder<M> With(
        string? name = null,
        M? model = default,
        bool? modelSet = null,
        IMessageHub? hub = null,
        IDispatcher? dispatcher = null,
        string? hint = null,
        ViewModelType? type = null,
        Func<M, string>? modeledHinter = null,
        Action<M>? onModelChanged = null,
        Action? onConstruct = null,
        Action? onDestruct = null,
        bool? background = null,
        IParentCompositeVM? parent = null)
        => new(
            name ?? _name,
            // For model: use provided model when modelSet is explicitly true, otherwise keep current
            modelSet == true ? model : _model,
            modelSet ?? _modelSet,
            hub ?? _hub,
            dispatcher ?? _dispatcher,
            hint ?? _hint,
            type ?? _type,
            modeledHinter ?? _modeledHinter,
            onModelChanged ?? _onModelChanged,
            onConstruct ?? _onConstruct,
            onDestruct ?? _onDestruct,
            background ?? _background,
            parent ?? _parent);
}

/// <summary>
/// Immutable fluent builder for <see cref="ComponentVM"/> (non-modeled).
/// Each setter returns a NEW builder instance (BLD-001).
/// Use <c>ComponentVM.Builder()</c> to start.
/// </summary>
public sealed class ComponentVMBuilder
{
    // ── Required fields (null means unset) ──────────────────────────────────
    private readonly string? _name;
    private readonly IMessageHub? _hub;
    private readonly IDispatcher? _dispatcher;

    // ── Optional fields ──────────────────────────────────────────────────────
    private readonly string _hint;
    private readonly Action? _onConstruct;
    private readonly Action? _onDestruct;
    private readonly bool _background;
    private readonly IParentCompositeVM? _parent;

    /// <summary>Represents an empty, unconfigured builder.</summary>
    public static readonly ComponentVMBuilder Empty = new();

    private ComponentVMBuilder()
    {
        _hint = "";
    }

    private ComponentVMBuilder(
        string? name,
        IMessageHub? hub,
        IDispatcher? dispatcher,
        string hint,
        Action? onConstruct,
        Action? onDestruct,
        bool background,
        IParentCompositeVM? parent)
    {
        _name = name;
        _hub = hub;
        _dispatcher = dispatcher;
        _hint = hint;
        _onConstruct = onConstruct;
        _onDestruct = onDestruct;
        _background = background;
        _parent = parent;
    }

    /// <summary>Sets the required Name field.</summary>
    public ComponentVMBuilder Name(string name) => With(name: name);

    /// <summary>Sets the optional Hint field (default: empty string).</summary>
    public ComponentVMBuilder Hint(string hint) => With(hint: hint);

    /// <summary>Sets the optional OnConstruct lifecycle callback.</summary>
    public ComponentVMBuilder OnConstruct(Action callback) => With(onConstruct: callback);

    /// <summary>Sets the optional OnDestruct lifecycle callback.</summary>
    public ComponentVMBuilder OnDestruct(Action callback) => With(onDestruct: callback);

    /// <summary>Sets the optional Background flag (default: false).</summary>
    public ComponentVMBuilder Background(bool background) => With(background: background);

    /// <summary>Sets the required Services (hub + dispatcher).</summary>
    public ComponentVMBuilder Services(IMessageHub hub, IDispatcher dispatcher)
        => With(hub: hub, dispatcher: dispatcher);

    internal ComponentVMBuilder OptionHub(IMessageHub hub) => With(hub: hub);

    internal ComponentVMBuilder OptionDispatcher(IDispatcher dispatcher)
        => With(dispatcher: dispatcher);

    /// <summary>
    /// Sets the required Services by resolving <see cref="IMessageHub"/> and
    /// <see cref="IDispatcher"/> from <paramref name="serviceProvider"/> (VMX-021).
    /// Use with <c>services.AddVMx()</c>.
    /// </summary>
    public ComponentVMBuilder Services(IServiceProvider serviceProvider)
    {
        var (hub, dispatcher) = BuilderServices.Resolve(serviceProvider);
        return With(hub: hub, dispatcher: dispatcher);
    }

    /// <summary>Sets the optional parent composite (internal: used by CompositeVMBase).</summary>
    internal ComponentVMBuilder Parent(IParentCompositeVM parent) => With(parent: parent);

    /// <summary>
    /// Validates required fields and constructs a <see cref="ComponentVM"/>.
    /// Throws <see cref="BuilderValidationException"/> if a required field is missing.
    /// </summary>
    public ComponentVM Build()
    {
        BuilderValidationException.Require(_name, "Name");
        BuilderValidationException.Require(_hub, "Hub");
        BuilderValidationException.Require(_dispatcher, "Dispatcher");

        var vm = ComponentVM.Create(
            _name,
            _hint,
            _hub,
            _dispatcher,
            _onConstruct,
            _onDestruct,
            _background);

        if (_parent is not null)
            vm.Parent = _parent;

        return vm;
    }

    private ComponentVMBuilder With(
        string? name = null,
        IMessageHub? hub = null,
        IDispatcher? dispatcher = null,
        string? hint = null,
        Action? onConstruct = null,
        Action? onDestruct = null,
        bool? background = null,
        IParentCompositeVM? parent = null)
        => new(
            name ?? _name,
            hub ?? _hub,
            dispatcher ?? _dispatcher,
            hint ?? _hint,
            onConstruct ?? _onConstruct,
            onDestruct ?? _onDestruct,
            background ?? _background,
            parent ?? _parent);
}

/// <summary>
/// Immutable fluent builder for <see cref="ReadonlyComponentVM{M}"/>.
/// Each setter returns a NEW builder instance (BLD-001).
/// Use <c>ReadonlyComponentVM&lt;M&gt;.Builder()</c> to start.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public sealed class ReadonlyComponentVMBuilder<M>
{
    // ── Required fields ──────────────────────────────────────────────────────
    private readonly string? _name;
    private readonly M? _model;
    private readonly bool _modelSet;
    private readonly IMessageHub? _hub;
    private readonly IDispatcher? _dispatcher;

    // ── Optional fields ──────────────────────────────────────────────────────
    private readonly string _hint;
    private readonly Func<M, string> _modeledHinter;
    private readonly Action? _onConstruct;
    private readonly Action? _onDestruct;
    private readonly IParentCompositeVM? _parent;

    /// <summary>Represents an empty, unconfigured builder.</summary>
    public static readonly ReadonlyComponentVMBuilder<M> Empty = new();

    private ReadonlyComponentVMBuilder()
    {
        _hint = "";
        _modeledHinter = _ => "";
        _model = default;
        _modelSet = false;
    }

    private ReadonlyComponentVMBuilder(
        string? name,
        M? model,
        bool modelSet,
        IMessageHub? hub,
        IDispatcher? dispatcher,
        string hint,
        Func<M, string> modeledHinter,
        Action? onConstruct,
        Action? onDestruct,
        IParentCompositeVM? parent)
    {
        _name = name;
        _model = model;
        _modelSet = modelSet;
        _hub = hub;
        _dispatcher = dispatcher;
        _hint = hint;
        _modeledHinter = modeledHinter;
        _onConstruct = onConstruct;
        _onDestruct = onDestruct;
        _parent = parent;
    }

    // ── Fluent setters ────────────────────────────────────────────────────────

    /// <summary>Sets the required Name field.</summary>
    public ReadonlyComponentVMBuilder<M> Name(string name) => With(name: name);

    /// <summary>Sets the optional Hint field.</summary>
    public ReadonlyComponentVMBuilder<M> Hint(string hint) => With(hint: hint);

    /// <summary>Sets the required Model field.</summary>
    public ReadonlyComponentVMBuilder<M> Model(M model) => With(model: model, modelSet: true);

    /// <summary>Sets the optional ModeledHinter function.</summary>
    public ReadonlyComponentVMBuilder<M> ModeledHinter(Func<M, string> hinter) => With(modeledHinter: hinter);

    /// <summary>Sets the optional OnConstruct lifecycle callback.</summary>
    public ReadonlyComponentVMBuilder<M> OnConstruct(Action callback) => With(onConstruct: callback);

    /// <summary>Sets the optional OnDestruct lifecycle callback.</summary>
    public ReadonlyComponentVMBuilder<M> OnDestruct(Action callback) => With(onDestruct: callback);

    /// <summary>Sets the required Services (hub + dispatcher).</summary>
    public ReadonlyComponentVMBuilder<M> Services(IMessageHub hub, IDispatcher dispatcher)
        => With(hub: hub, dispatcher: dispatcher);

    /// <summary>
    /// Sets the required Services by resolving <see cref="IMessageHub"/> and
    /// <see cref="IDispatcher"/> from <paramref name="serviceProvider"/> (VMX-021).
    /// Use with <c>services.AddVMx()</c>.
    /// </summary>
    public ReadonlyComponentVMBuilder<M> Services(IServiceProvider serviceProvider)
    {
        var (hub, dispatcher) = BuilderServices.Resolve(serviceProvider);
        return With(hub: hub, dispatcher: dispatcher);
    }

    /// <summary>Sets the optional parent composite (internal: used by CompositeVMBase).</summary>
    internal ReadonlyComponentVMBuilder<M> Parent(IParentCompositeVM parent) => With(parent: parent);

    /// <summary>
    /// Validates required fields and constructs a <see cref="ReadonlyComponentVM{M}"/>.
    /// Throws <see cref="BuilderValidationException"/> if a required field is missing.
    /// </summary>
    public ReadonlyComponentVM<M> Build()
    {
        BuilderValidationException.Require(_name, "Name");
        if (!_modelSet) throw new BuilderValidationException("Model");
        BuilderValidationException.Require(_hub, "Hub");
        BuilderValidationException.Require(_dispatcher, "Dispatcher");

        var vm = ReadonlyComponentVM<M>.Create(
            _name,
            _hint,
            _model!,
            _modeledHinter,
            _hub,
            _dispatcher,
            _onConstruct,
            _onDestruct);

        if (_parent is not null)
            vm.Parent = _parent;

        return vm;
    }

    // ── Private clone helper ─────────────────────────────────────────────────
    private ReadonlyComponentVMBuilder<M> With(
        string? name = null,
        M? model = default,
        bool? modelSet = null,
        IMessageHub? hub = null,
        IDispatcher? dispatcher = null,
        string? hint = null,
        Func<M, string>? modeledHinter = null,
        Action? onConstruct = null,
        Action? onDestruct = null,
        IParentCompositeVM? parent = null)
        => new(
            name ?? _name,
            modelSet == true ? model : _model,
            modelSet ?? _modelSet,
            hub ?? _hub,
            dispatcher ?? _dispatcher,
            hint ?? _hint,
            modeledHinter ?? _modeledHinter,
            onConstruct ?? _onConstruct,
            onDestruct ?? _onDestruct,
            parent ?? _parent);
}
