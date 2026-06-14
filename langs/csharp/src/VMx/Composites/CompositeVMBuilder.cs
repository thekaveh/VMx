#pragma warning disable CA1715 // Spec uses 'VM' / 'M' type parameters per ADR-0006
using VMx.Builders;
using VMx.Components;
using VMx.Services;

namespace VMx.Composites;

/// <summary>
/// Immutable fluent builder for <see cref="CompositeVM{VM}"/> (non-modeled).
/// Each setter returns a new builder instance (BLD-001).
/// Use <c>CompositeVM&lt;VM&gt;.Builder()</c> to start.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public sealed class CompositeVMBuilder<VM>
    where VM : class, IComponentVM
{
    // ── Required ──────────────────────────────────────────────────────────────
    private readonly string? _name;
    private readonly IMessageHub? _hub;
    private readonly IDispatcher? _dispatcher;

    // ── Optional ──────────────────────────────────────────────────────────────
    private readonly string _hint;
    private readonly bool _asyncSelection;
    private readonly bool _autoConstructOnAdd;
    private readonly Func<IEnumerable<VM>>? _childrenFactory;
    private readonly Action? _onConstruct;
    private readonly Action? _onDestruct;
    private readonly Func<IEnumerable<VM>, VM?>? _currentSelector;

    /// <summary>Empty starting builder.</summary>
    public static readonly CompositeVMBuilder<VM> Empty = new();

    private CompositeVMBuilder() { _hint = ""; }

    private CompositeVMBuilder(
        string? name,
        IMessageHub? hub,
        IDispatcher? dispatcher,
        string hint,
        bool asyncSelection,
        bool autoConstructOnAdd,
        Func<IEnumerable<VM>>? childrenFactory,
        Action? onConstruct,
        Action? onDestruct,
        Func<IEnumerable<VM>, VM?>? currentSelector)
    {
        _name = name;
        _hub = hub;
        _dispatcher = dispatcher;
        _hint = hint;
        _asyncSelection = asyncSelection;
        _autoConstructOnAdd = autoConstructOnAdd;
        _childrenFactory = childrenFactory;
        _onConstruct = onConstruct;
        _onDestruct = onDestruct;
        _currentSelector = currentSelector;
    }

    /// <summary>Sets the required Name.</summary>
    public CompositeVMBuilder<VM> Name(string name) => With(name: name);

    /// <summary>Sets the optional Hint (default: "").</summary>
    public CompositeVMBuilder<VM> Hint(string hint) => With(hint: hint);

    /// <summary>Sets the required Services (hub + dispatcher).</summary>
    public CompositeVMBuilder<VM> Services(IMessageHub hub, IDispatcher dispatcher)
        => With(hub: hub, dispatcher: dispatcher);

    /// <summary>
    /// Sets the required children factory. The factory is invoked lazily on
    /// Construct. For a composite with no initial children, pass
    /// <c>() =&gt; Array.Empty&lt;VM&gt;()</c> (per spec/10 §3 / ADR-0035).
    /// </summary>
    public CompositeVMBuilder<VM> Children(Func<IEnumerable<VM>> factory)
        => With(childrenFactory: factory);

    /// <summary>
    /// Sets an optional selector that picks the initial <c>Current</c> child during
    /// construct. The selector runs after all children reach <c>Constructed</c> and
    /// before the composite itself transitions to <c>Constructed</c>. If it returns
    /// <see langword="null"/> or a value not in the composite, <c>Current</c> is
    /// left at its prior value (initially <see langword="null"/>) and no
    /// notification fires. See ADR-0042 and spec/06 §3.X (COMP-025).
    /// </summary>
    public CompositeVMBuilder<VM> Current(Func<IEnumerable<VM>, VM?> selector)
        => With(currentSelector: selector);

    /// <summary>Enables async selection dispatch via the foreground scheduler.</summary>
    public CompositeVMBuilder<VM> AsyncSelection(bool asyncSelection) => With(asyncSelection: asyncSelection);

    /// <summary>
    /// When <see langword="true"/>, children added via Add or Insert after the composite
    /// reaches Constructed are automatically constructed before the CollectionChanged event fires.
    /// Default is <see langword="false"/> for backwards compatibility.
    /// </summary>
    public CompositeVMBuilder<VM> AutoConstructOnAdd(bool autoConstructOnAdd) => With(autoConstructOnAdd: autoConstructOnAdd);

    /// <summary>Sets the optional OnConstruct lifecycle callback.</summary>
    public CompositeVMBuilder<VM> OnConstruct(Action callback) => With(onConstruct: callback);

    /// <summary>Sets the optional OnDestruct lifecycle callback.</summary>
    public CompositeVMBuilder<VM> OnDestruct(Action callback) => With(onDestruct: callback);

    /// <summary>
    /// Validates required fields and builds a <see cref="CompositeVM{VM}"/>.
    /// </summary>
    public CompositeVM<VM> Build()
    {
        BuilderValidationException.Require(_name, "Name");
        BuilderValidationException.Require(_hub, "Hub");
        BuilderValidationException.Require(_dispatcher, "Dispatcher");
        BuilderValidationException.Require(_childrenFactory, "Children");

        return CompositeVM<VM>.Create(
            _name, _hint, _hub, _dispatcher,
            _asyncSelection, _autoConstructOnAdd, _childrenFactory,
            _onConstruct, _onDestruct, _currentSelector);
    }

    private CompositeVMBuilder<VM> With(
        string? name = null,
        IMessageHub? hub = null,
        IDispatcher? dispatcher = null,
        string? hint = null,
        bool? asyncSelection = null,
        bool? autoConstructOnAdd = null,
        Func<IEnumerable<VM>>? childrenFactory = null,
        Action? onConstruct = null,
        Action? onDestruct = null,
        Func<IEnumerable<VM>, VM?>? currentSelector = null)
        => new(
            name ?? _name,
            hub ?? _hub,
            dispatcher ?? _dispatcher,
            hint ?? _hint,
            asyncSelection ?? _asyncSelection,
            autoConstructOnAdd ?? _autoConstructOnAdd,
            childrenFactory ?? _childrenFactory,
            onConstruct ?? _onConstruct,
            onDestruct ?? _onDestruct,
            currentSelector ?? _currentSelector);
}

/// <summary>
/// Immutable fluent builder for <see cref="CompositeVMOfM{M,VM}"/> (modeled).
/// Each setter returns a new builder instance (BLD-001).
/// Use <c>CompositeVMOfM&lt;M, VM&gt;.Builder()</c> to start.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public sealed class CompositeVMOfMBuilder<M, VM>
    where VM : class, IComponentVM
{
    // ── Required ──────────────────────────────────────────────────────────────
    private readonly string? _name;
    private readonly IMessageHub? _hub;
    private readonly IDispatcher? _dispatcher;
    private readonly Func<IEnumerable<M>>? _childrenModels;
    private readonly Func<M, VM>? _childModelToChildViewModel;

    // ── Optional ──────────────────────────────────────────────────────────────
    private readonly string _hint;
    private readonly bool _asyncSelection;
    private readonly bool _autoConstructOnAdd;
    private readonly Action? _onConstruct;
    private readonly Action? _onDestruct;
    private readonly Func<IEnumerable<VM>, VM?>? _currentSelector;

    /// <summary>Empty starting builder.</summary>
    public static readonly CompositeVMOfMBuilder<M, VM> Empty = new();

    private CompositeVMOfMBuilder() { _hint = ""; }

    private CompositeVMOfMBuilder(
        string? name,
        IMessageHub? hub,
        IDispatcher? dispatcher,
        string hint,
        bool asyncSelection,
        bool autoConstructOnAdd,
        Func<IEnumerable<M>>? childrenModels,
        Func<M, VM>? childModelToChildViewModel,
        Action? onConstruct,
        Action? onDestruct,
        Func<IEnumerable<VM>, VM?>? currentSelector)
    {
        _name = name;
        _hub = hub;
        _dispatcher = dispatcher;
        _hint = hint;
        _asyncSelection = asyncSelection;
        _autoConstructOnAdd = autoConstructOnAdd;
        _childrenModels = childrenModels;
        _childModelToChildViewModel = childModelToChildViewModel;
        _onConstruct = onConstruct;
        _onDestruct = onDestruct;
        _currentSelector = currentSelector;
    }

    /// <summary>Sets the required Name.</summary>
    public CompositeVMOfMBuilder<M, VM> Name(string name) => With(name: name);

    /// <summary>Sets the optional Hint.</summary>
    public CompositeVMOfMBuilder<M, VM> Hint(string hint) => With(hint: hint);

    /// <summary>Sets the required Services.</summary>
    public CompositeVMOfMBuilder<M, VM> Services(IMessageHub hub, IDispatcher dispatcher)
        => With(hub: hub, dispatcher: dispatcher);

    /// <summary>Sets the required model factory.</summary>
    public CompositeVMOfMBuilder<M, VM> ChildrenModels(Func<IEnumerable<M>> factory)
        => With(childrenModels: factory);

    /// <summary>Sets the required model→VM mapper.</summary>
    public CompositeVMOfMBuilder<M, VM> ChildModelToChildViewModel(Func<M, VM> mapper)
        => With(childModelToChildViewModel: mapper);

    /// <summary>
    /// Sets an optional selector that picks the initial <c>Current</c> child during
    /// construct. The selector runs after all children reach <c>Constructed</c> and
    /// before the composite itself transitions to <c>Constructed</c>. If it returns
    /// <see langword="null"/> or a value not in the composite, <c>Current</c> is
    /// left at its prior value (initially <see langword="null"/>) and no
    /// notification fires. See ADR-0042 and spec/06 §3.X (COMP-025).
    /// </summary>
    public CompositeVMOfMBuilder<M, VM> Current(Func<IEnumerable<VM>, VM?> selector)
        => With(currentSelector: selector);

    /// <summary>Enables async selection dispatch.</summary>
    public CompositeVMOfMBuilder<M, VM> AsyncSelection(bool asyncSelection)
        => With(asyncSelection: asyncSelection);

    /// <summary>
    /// When <see langword="true"/>, children added via Add or Insert after the composite
    /// reaches Constructed are automatically constructed before the CollectionChanged event fires.
    /// Default is <see langword="false"/> for backwards compatibility.
    /// </summary>
    public CompositeVMOfMBuilder<M, VM> AutoConstructOnAdd(bool autoConstructOnAdd)
        => With(autoConstructOnAdd: autoConstructOnAdd);

    /// <summary>Sets the optional OnConstruct callback.</summary>
    public CompositeVMOfMBuilder<M, VM> OnConstruct(Action callback) => With(onConstruct: callback);

    /// <summary>Sets the optional OnDestruct callback.</summary>
    public CompositeVMOfMBuilder<M, VM> OnDestruct(Action callback) => With(onDestruct: callback);

    /// <summary>
    /// Validates required fields and builds a <see cref="CompositeVMOfM{M,VM}"/>.
    /// </summary>
    public CompositeVMOfM<M, VM> Build()
    {
        BuilderValidationException.Require(_name, "Name");
        BuilderValidationException.Require(_hub, "Hub");
        BuilderValidationException.Require(_dispatcher, "Dispatcher");
        BuilderValidationException.Require(_childrenModels, "ChildrenModels");
        BuilderValidationException.Require(_childModelToChildViewModel, "ChildModelToChildViewModel");

        return CompositeVMOfM<M, VM>.Create(
            _name, _hint, _hub, _dispatcher,
            _asyncSelection, _autoConstructOnAdd,
            _childrenModels, _childModelToChildViewModel,
            _onConstruct, _onDestruct, _currentSelector);
    }

    private CompositeVMOfMBuilder<M, VM> With(
        string? name = null,
        IMessageHub? hub = null,
        IDispatcher? dispatcher = null,
        string? hint = null,
        bool? asyncSelection = null,
        bool? autoConstructOnAdd = null,
        Func<IEnumerable<M>>? childrenModels = null,
        Func<M, VM>? childModelToChildViewModel = null,
        Action? onConstruct = null,
        Action? onDestruct = null,
        Func<IEnumerable<VM>, VM?>? currentSelector = null)
        => new(
            name ?? _name,
            hub ?? _hub,
            dispatcher ?? _dispatcher,
            hint ?? _hint,
            asyncSelection ?? _asyncSelection,
            autoConstructOnAdd ?? _autoConstructOnAdd,
            childrenModels ?? _childrenModels,
            childModelToChildViewModel ?? _childModelToChildViewModel,
            onConstruct ?? _onConstruct,
            onDestruct ?? _onDestruct,
            currentSelector ?? _currentSelector);
}
#pragma warning restore CA1715
