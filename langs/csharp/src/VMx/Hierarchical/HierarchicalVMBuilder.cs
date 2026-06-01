#pragma warning disable CA1715 // Spec uses 'TModel' / 'TVM' per ADR-0006 and ADR-0028
using VMx.Builders;
using VMx.Services;

namespace VMx.Hierarchical;

/// <summary>
/// Construction context passed to <see cref="HierarchicalVMBuilder{TModel, TVM}.VmFactory"/>.
/// Carries the validated constructor arguments produced by the builder so consumers
/// can wire their concrete <typeparamref name="TVM"/> subclass without having to
/// inspect the builder directly.
/// </summary>
/// <typeparam name="TModel">Domain model carried by the node.</typeparam>
/// <typeparam name="TVM">Concrete subclass type (recursive constraint per ADR-0028 §3.2).</typeparam>
/// <param name="Model">Domain model for the node being built.</param>
/// <param name="ChildrenFactory">Factory invoked with the new node to produce its children.</param>
/// <param name="Hub">Message hub for pub/sub.</param>
/// <param name="Dispatcher">Dispatcher for async/background work.</param>
/// <param name="Name">Optional VM name (defaults to <c>typeof(TVM).Name</c> when null).</param>
/// <param name="Hint">Optional display hint string (defaults to empty).</param>
/// <param name="EagerChildren">When true, the full subtree is materialized at construct time.</param>
public sealed record HierarchicalVMConstructionContext<TModel, TVM>(
    TModel Model,
    Func<TVM, IEnumerable<TVM>> ChildrenFactory,
    IMessageHub Hub,
    IDispatcher Dispatcher,
    string? Name,
    string Hint,
    bool EagerChildren)
    where TVM : HierarchicalVM<TModel, TVM>;

/// <summary>
/// Immutable fluent builder for <see cref="HierarchicalVM{TModel, TVM}"/>.
/// Each setter returns a new builder instance (BLD-001).
/// See spec/10-builders.md §3 and ADR-0035 §2 H1 / H2.
///
/// Because <see cref="HierarchicalVM{TModel, TVM}"/> is <c>abstract</c> with a
/// <c>protected</c> constructor, consumers MUST supply a <see cref="VmFactory"/>
/// callback that knows how to instantiate their concrete subclass. The factory
/// receives a <see cref="HierarchicalVMConstructionContext{TModel, TVM}"/>
/// carrying the validated constructor arguments, e.g.
/// <code>
/// .VmFactory(ctx =&gt; new MyTreeNode(
///     ctx.Model, ctx.ChildrenFactory, ctx.Hub, ctx.Dispatcher,
///     ctx.Name, ctx.Hint, ctx.EagerChildren))
/// </code>
///
/// Note: there is no <c>WithDefaultServices()</c> Wither on the C# builder. Per
/// ADR-0035 §2 H2 that Wither is Python + TypeScript only — C# consumers must
/// call <see cref="Services"/> explicitly.
/// </summary>
/// <typeparam name="TModel">Domain model carried by the node.</typeparam>
/// <typeparam name="TVM">Concrete subclass type (recursive constraint per ADR-0028 §3.2).</typeparam>
public sealed class HierarchicalVMBuilder<TModel, TVM>
    where TVM : HierarchicalVM<TModel, TVM>
{
    // ── Required ──────────────────────────────────────────────────────────────
    // `TModel` may be a value type, so we cannot use `null` to detect "unset".
    // Track presence with a dedicated flag (mirrors Python's `_model_set` sentinel).
    private readonly TModel _model;
    private readonly bool _modelSet;
    private readonly Func<TVM, IEnumerable<TVM>>? _childrenFactory;
    private readonly IMessageHub? _hub;
    private readonly IDispatcher? _dispatcher;
    private readonly Func<HierarchicalVMConstructionContext<TModel, TVM>, TVM>? _vmFactory;

    // ── Optional ──────────────────────────────────────────────────────────────
    private readonly string? _name;
    private readonly string _hint;
    private readonly bool _eagerChildren;

    /// <summary>Empty starting builder.</summary>
    public static readonly HierarchicalVMBuilder<TModel, TVM> Empty = new();

    private HierarchicalVMBuilder()
    {
        _model = default!;
        _modelSet = false;
        _hint = "";
    }

    private HierarchicalVMBuilder(
        TModel model,
        bool modelSet,
        Func<TVM, IEnumerable<TVM>>? childrenFactory,
        IMessageHub? hub,
        IDispatcher? dispatcher,
        Func<HierarchicalVMConstructionContext<TModel, TVM>, TVM>? vmFactory,
        string? name,
        string hint,
        bool eagerChildren)
    {
        _model = model;
        _modelSet = modelSet;
        _childrenFactory = childrenFactory;
        _hub = hub;
        _dispatcher = dispatcher;
        _vmFactory = vmFactory;
        _name = name;
        _hint = hint;
        _eagerChildren = eagerChildren;
    }

    /// <summary>Sets the required <c>Model</c> for this node.</summary>
    public HierarchicalVMBuilder<TModel, TVM> Model(TModel model)
        => With(model: model, modelSet: true);

    /// <summary>Sets the required children factory (parent -> child sequence).</summary>
    public HierarchicalVMBuilder<TModel, TVM> ChildrenFactory(Func<TVM, IEnumerable<TVM>> factory)
        => With(childrenFactory: factory);

    /// <summary>Sets the required services (hub + dispatcher).</summary>
    public HierarchicalVMBuilder<TModel, TVM> Services(IMessageHub hub, IDispatcher dispatcher)
        => With(hub: hub, dispatcher: dispatcher);

    /// <summary>
    /// Sets the required concrete-VM factory. Because
    /// <see cref="HierarchicalVM{TModel, TVM}"/> is abstract, the builder needs
    /// to be told which concrete subclass to instantiate. The factory receives a
    /// <see cref="HierarchicalVMConstructionContext{TModel, TVM}"/> and returns
    /// the concrete <typeparamref name="TVM"/>.
    /// </summary>
    public HierarchicalVMBuilder<TModel, TVM> VmFactory(
        Func<HierarchicalVMConstructionContext<TModel, TVM>, TVM> factory)
        => With(vmFactory: factory);

    /// <summary>Sets the optional <c>Name</c> (default: <c>typeof(TVM).Name</c>).</summary>
    public HierarchicalVMBuilder<TModel, TVM> Name(string name) => With(name: name);

    /// <summary>Sets the optional <c>Hint</c> (default: empty string).</summary>
    public HierarchicalVMBuilder<TModel, TVM> Hint(string hint) => With(hint: hint);

    /// <summary>
    /// When <see langword="true"/>, materializes the entire subtree at construct
    /// time (depth-first). Default is <see langword="false"/> (lazy).
    /// </summary>
    public HierarchicalVMBuilder<TModel, TVM> EagerChildren(bool eagerChildren)
        => With(eagerChildren: eagerChildren);

    /// <summary>
    /// Validates required fields and builds a concrete <typeparamref name="TVM"/>
    /// via the supplied <see cref="VmFactory"/>.
    /// </summary>
    public TVM Build()
    {
        if (!_modelSet) throw new BuilderValidationException("Model");
        BuilderValidationException.Require(_childrenFactory, "ChildrenFactory");
        BuilderValidationException.Require(_hub, "Hub");
        BuilderValidationException.Require(_dispatcher, "Dispatcher");
        BuilderValidationException.Require(_vmFactory, "VmFactory");

        var ctx = new HierarchicalVMConstructionContext<TModel, TVM>(
            Model: _model,
            ChildrenFactory: _childrenFactory,
            Hub: _hub,
            Dispatcher: _dispatcher,
            Name: _name,
            Hint: _hint,
            EagerChildren: _eagerChildren);

        return _vmFactory(ctx);
    }

    private HierarchicalVMBuilder<TModel, TVM> With(
        TModel? model = default,
        bool? modelSet = null,
        Func<TVM, IEnumerable<TVM>>? childrenFactory = null,
        IMessageHub? hub = null,
        IDispatcher? dispatcher = null,
        Func<HierarchicalVMConstructionContext<TModel, TVM>, TVM>? vmFactory = null,
        string? name = null,
        string? hint = null,
        bool? eagerChildren = null)
        => new(
            modelSet == true ? model! : _model,
            modelSet ?? _modelSet,
            childrenFactory ?? _childrenFactory,
            hub ?? _hub,
            dispatcher ?? _dispatcher,
            vmFactory ?? _vmFactory,
            name ?? _name,
            hint ?? _hint,
            eagerChildren ?? _eagerChildren);
}
#pragma warning restore CA1715
