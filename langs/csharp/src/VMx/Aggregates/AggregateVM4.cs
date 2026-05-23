#pragma warning disable CA1715 // Spec uses 'VM' type parameter names per ADR-0006
using VMx.Builders;
using VMx.Components;
using VMx.Messages;
using VMx.Services;

namespace VMx.Aggregates;

/// <summary>
/// Arity-4 aggregate viewmodel. A fixed tuple of four heterogeneous component VMs.
/// Component slots are populated lazily on construct() by invoking factories
/// provided via the nested builder.
///
/// See spec/08-aggregate-vm.md and ADR-0007.
/// </summary>
/// <typeparam name="VM1">Type of the first component.</typeparam>
/// <typeparam name="VM2">Type of the second component.</typeparam>
/// <typeparam name="VM3">Type of the third component.</typeparam>
/// <typeparam name="VM4">Type of the fourth component.</typeparam>
public sealed class AggregateVM4<VM1, VM2, VM3, VM4> : ComponentVMBase, IAggregateVM4<VM1, VM2, VM3, VM4>
    where VM1 : class, IComponentVM
    where VM2 : class, IComponentVM
    where VM3 : class, IComponentVM
    where VM4 : class, IComponentVM
{
    private readonly Func<VM1> _factory1;
    private readonly Func<VM2> _factory2;
    private readonly Func<VM3> _factory3;
    private readonly Func<VM4> _factory4;
    private VM1? _component1;
    private VM2? _component2;
    private VM3? _component3;
    private VM4? _component4;

    // ── IAggregateVM4<VM1, VM2, VM3, VM4> ───────────────────────────────────

    /// <inheritdoc/>
    public VM1? Component1 => _component1;

    /// <inheritdoc/>
    public VM2? Component2 => _component2;

    /// <inheritdoc/>
    public VM3? Component3 => _component3;

    /// <inheritdoc/>
    public VM4? Component4 => _component4;

    // ── IComponentVM.Type ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Aggregate;

    // ── Constructor ─────────────────────────────────────────────────────────

    private AggregateVM4(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        Func<VM1> factory1,
        Func<VM2> factory2,
        Func<VM3> factory3,
        Func<VM4> factory4)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _factory1 = factory1;
        _factory2 = factory2;
        _factory3 = factory3;
        _factory4 = factory4;
    }

    // ── Lifecycle overrides ─────────────────────────────────────────────────

    /// <inheritdoc/>
    protected override void OnConstruct()
    {
        _component1 = _factory1();
        RaisePropertyChanged(nameof(Component1));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Component1)));

        _component2 = _factory2();
        RaisePropertyChanged(nameof(Component2));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Component2)));

        _component3 = _factory3();
        RaisePropertyChanged(nameof(Component3));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Component3)));

        _component4 = _factory4();
        RaisePropertyChanged(nameof(Component4));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Component4)));

        _component1.Construct();
        _component2.Construct();
        _component3.Construct();
        _component4.Construct();
    }

    /// <inheritdoc/>
    protected override void OnDestruct()
    {
        _component1?.Destruct();
        _component2?.Destruct();
        _component3?.Destruct();
        _component4?.Destruct();
    }

    /// <inheritdoc/>
    public override void Dispose()
    {
        _component1?.Dispose();
        _component2?.Dispose();
        _component3?.Dispose();
        _component4?.Dispose();
        base.Dispose();
        GC.SuppressFinalize(this);
    }

    // ── Builder factory ─────────────────────────────────────────────────────

#pragma warning disable CA1000 // Generic static member on generic type: intentional per spec
    /// <summary>Returns a new empty builder for <see cref="AggregateVM4{VM1,VM2,VM3,VM4}"/>.</summary>
    public static AggregateVM4Builder Builder() => new();
#pragma warning restore CA1000

    // ── Nested builder ──────────────────────────────────────────────────────

    /// <summary>
    /// Immutable fluent builder for <see cref="AggregateVM4{VM1,VM2,VM3,VM4}"/>.
    /// Each setter returns a NEW builder instance (BLD-001).
    /// </summary>
    public sealed class AggregateVM4Builder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly Func<VM1>? _factory1;
        private readonly Func<VM2>? _factory2;
        private readonly Func<VM3>? _factory3;
        private readonly Func<VM4>? _factory4;

        internal AggregateVM4Builder()
        {
            _hint = "";
        }

        private AggregateVM4Builder(
            string? name,
            string hint,
            IMessageHub? hub,
            IDispatcher? dispatcher,
            Func<VM1>? factory1,
            Func<VM2>? factory2,
            Func<VM3>? factory3,
            Func<VM4>? factory4)
        {
            _name = name;
            _hint = hint;
            _hub = hub;
            _dispatcher = dispatcher;
            _factory1 = factory1;
            _factory2 = factory2;
            _factory3 = factory3;
            _factory4 = factory4;
        }

        /// <summary>Sets the required Name field.</summary>
        public AggregateVM4Builder Name(string name)
            => new(name, _hint, _hub, _dispatcher, _factory1, _factory2, _factory3, _factory4);

        /// <summary>Sets the optional Hint field (default: empty string).</summary>
        public AggregateVM4Builder Hint(string hint)
            => new(_name, hint, _hub, _dispatcher, _factory1, _factory2, _factory3, _factory4);

        /// <summary>Sets the required Services (hub + dispatcher).</summary>
        public AggregateVM4Builder Services(IMessageHub hub, IDispatcher dispatcher)
            => new(_name, _hint, hub, dispatcher, _factory1, _factory2, _factory3, _factory4);

        /// <summary>Sets the required factory for Component1.</summary>
        public AggregateVM4Builder Component1(Func<VM1> factory)
            => new(_name, _hint, _hub, _dispatcher, factory, _factory2, _factory3, _factory4);

        /// <summary>Sets the required factory for Component2.</summary>
        public AggregateVM4Builder Component2(Func<VM2> factory)
            => new(_name, _hint, _hub, _dispatcher, _factory1, factory, _factory3, _factory4);

        /// <summary>Sets the required factory for Component3.</summary>
        public AggregateVM4Builder Component3(Func<VM3> factory)
            => new(_name, _hint, _hub, _dispatcher, _factory1, _factory2, factory, _factory4);

        /// <summary>Sets the required factory for Component4.</summary>
        public AggregateVM4Builder Component4(Func<VM4> factory)
            => new(_name, _hint, _hub, _dispatcher, _factory1, _factory2, _factory3, factory);

        /// <summary>
        /// Validates required fields and constructs a <see cref="AggregateVM4{VM1,VM2,VM3,VM4}"/>.
        /// Throws <see cref="BuilderValidationException"/> if a required field is missing.
        /// </summary>
        public AggregateVM4<VM1, VM2, VM3, VM4> Build()
        {
            if (_name is null) throw new BuilderValidationException("Name");
            if (_hub is null) throw new BuilderValidationException("Hub");
            if (_dispatcher is null) throw new BuilderValidationException("Dispatcher");
            if (_factory1 is null) throw new BuilderValidationException("Component1");
            if (_factory2 is null) throw new BuilderValidationException("Component2");
            if (_factory3 is null) throw new BuilderValidationException("Component3");
            if (_factory4 is null) throw new BuilderValidationException("Component4");

            return new AggregateVM4<VM1, VM2, VM3, VM4>(
                _name, _hint, _hub, _dispatcher,
                _factory1, _factory2, _factory3, _factory4);
        }
    }
}
#pragma warning restore CA1715
