using VMx.Builders;
using VMx.Components;
using VMx.Services;

namespace VMx.Groups;

/// <summary>
/// Immutable fluent builder for <see cref="GroupVM{VM}"/> (non-modeled).
/// Each setter returns a new builder instance (BLD-001).
/// Use <c>GroupVM&lt;VM&gt;.Builder()</c> to start.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public sealed class GroupVMBuilder<VM>
    where VM : class, IComponentVM
{
    // ── Required ──────────────────────────────────────────────────────────────
    private readonly string? _name;
    private readonly IMessageHub? _hub;
    private readonly IDispatcher? _dispatcher;

    // ── Optional ──────────────────────────────────────────────────────────────
    private readonly string _hint;
    private readonly bool _autoConstructOnAdd;
    private readonly Func<IEnumerable<VM>>? _childrenFactory;
    private readonly Action? _onConstruct;
    private readonly Action? _onDestruct;

    /// <summary>Empty starting builder.</summary>
    public static readonly GroupVMBuilder<VM> Empty = new();

    private GroupVMBuilder() { _hint = ""; }

    private GroupVMBuilder(
        string? name,
        IMessageHub? hub,
        IDispatcher? dispatcher,
        string hint,
        bool autoConstructOnAdd,
        Func<IEnumerable<VM>>? childrenFactory,
        Action? onConstruct,
        Action? onDestruct)
    {
        _name = name;
        _hub = hub;
        _dispatcher = dispatcher;
        _hint = hint;
        _autoConstructOnAdd = autoConstructOnAdd;
        _childrenFactory = childrenFactory;
        _onConstruct = onConstruct;
        _onDestruct = onDestruct;
    }

    /// <summary>Sets the required Name.</summary>
    public GroupVMBuilder<VM> Name(string name) => With(name: name);

    /// <summary>Sets the optional Hint (default: "").</summary>
    public GroupVMBuilder<VM> Hint(string hint) => With(hint: hint);

    /// <summary>Sets the required Services (hub + dispatcher).</summary>
    public GroupVMBuilder<VM> Services(IMessageHub hub, IDispatcher dispatcher)
        => With(hub: hub, dispatcher: dispatcher);

    /// <summary>
    /// Sets the required children factory. The factory is invoked lazily on
    /// Construct. For a group with no initial children, pass
    /// <c>() =&gt; Array.Empty&lt;VM&gt;()</c> (per spec/10 §3 / ADR-0035).
    /// </summary>
    public GroupVMBuilder<VM> Children(Func<IEnumerable<VM>> factory)
        => With(childrenFactory: factory);

    /// <summary>
    /// When <see langword="true"/>, children added via Add or Insert after the group
    /// reaches Constructed are automatically constructed before the CollectionChanged event fires.
    /// Default is <see langword="false"/> for backwards compatibility.
    /// </summary>
    public GroupVMBuilder<VM> AutoConstructOnAdd(bool autoConstructOnAdd)
        => With(autoConstructOnAdd: autoConstructOnAdd);

    /// <summary>Sets the optional OnConstruct lifecycle callback.</summary>
    public GroupVMBuilder<VM> OnConstruct(Action callback) => With(onConstruct: callback);

    /// <summary>Sets the optional OnDestruct lifecycle callback.</summary>
    public GroupVMBuilder<VM> OnDestruct(Action callback) => With(onDestruct: callback);

    /// <summary>
    /// Validates required fields and builds a <see cref="GroupVM{VM}"/>.
    /// </summary>
    public GroupVM<VM> Build()
    {
        BuilderValidationException.Require(_name, "Name");
        BuilderValidationException.Require(_hub, "Hub");
        BuilderValidationException.Require(_dispatcher, "Dispatcher");
        BuilderValidationException.Require(_childrenFactory, "Children");

        return GroupVM<VM>.Create(
            _name, _hint, _hub, _dispatcher,
            _autoConstructOnAdd, _childrenFactory,
            _onConstruct, _onDestruct);
    }

    private GroupVMBuilder<VM> With(
        string? name = null,
        IMessageHub? hub = null,
        IDispatcher? dispatcher = null,
        string? hint = null,
        bool? autoConstructOnAdd = null,
        Func<IEnumerable<VM>>? childrenFactory = null,
        Action? onConstruct = null,
        Action? onDestruct = null)
        => new(
            name ?? _name,
            hub ?? _hub,
            dispatcher ?? _dispatcher,
            hint ?? _hint,
            autoConstructOnAdd ?? _autoConstructOnAdd,
            childrenFactory ?? _childrenFactory,
            onConstruct ?? _onConstruct,
            onDestruct ?? _onDestruct);
}
