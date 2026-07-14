using VMx.Builders;
using VMx.Components;
using VMx.Services;

namespace VMx.Aggregates;

/// <summary>
/// Arity-2 aggregate viewmodel. A fixed tuple of two heterogeneous component VMs.
/// Component slots are populated lazily on construct() by invoking factories
/// provided via the nested builder.
///
/// See spec/08-aggregate-vm.md and ADR-0007.
/// </summary>
/// <typeparam name="VM1">Type of the first component.</typeparam>
/// <typeparam name="VM2">Type of the second component.</typeparam>
public sealed class AggregateVM2<VM1, VM2> : ComponentVMBase, IAggregateVM2<VM1, VM2>, IAggregateSlots
    where VM1 : class, IComponentVM
    where VM2 : class, IComponentVM
{
    private readonly Func<VM1> _factory1;
    private readonly Func<VM2> _factory2;
    private VM1? _component1;
    private VM2? _component2;

    IEnumerable<IComponentVM> IAggregateSlots.EnumerateSlots()
    {
        if (_component1 is { } c1) yield return c1;
        if (_component2 is { } c2) yield return c2;
    }

    // ── IAggregateVM2<VM1, VM2> ─────────────────────────────────────────────

    /// <inheritdoc/>
    public VM1? Component1 => _component1;

    /// <inheritdoc/>
    public VM2? Component2 => _component2;

    // ── IComponentVM.Type ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Aggregate;

    // ── Constructor ─────────────────────────────────────────────────────────

    private AggregateVM2(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        Func<VM1> factory1,
        Func<VM2> factory2)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _factory1 = factory1;
        _factory2 = factory2;
    }

    // ── Lifecycle overrides ─────────────────────────────────────────────────

    /// <inheritdoc/>
    protected override void OnConstruct()
    {
        // On Reconstruct, dispose previous slot instances before overwriting
        // so their hub subscriptions and command Subjects don't leak.
        _component1?.Dispose();
        _component2?.Dispose();

        _component1 = _factory1();
        NotifyPropertyChanged(nameof(Component1));

        _component2 = _factory2();
        NotifyPropertyChanged(nameof(Component2));

        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            [_component1, _component2], construct: true));
    }

    /// <inheritdoc/>
    protected override void OnDestruct()
    {
        CompleteLifecycleHookAfter(TransitionChildrenAsync(
            new IComponentVM?[] { _component1, _component2 }.OfType<IComponentVM>(),
            construct: false));
    }

    /// <summary>
    /// Dispose cascade (LIFE-013): dispose each component slot depth-first, then self.
    /// </summary>
    public override void Dispose()
    {
        var firstError = DisposeChildren([_component1, _component2]);
        try { base.Dispose(); }
        catch (Exception error)
        {
            firstError ??= System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error);
        }
        firstError?.Throw();
    }

    // ── Builder factory ─────────────────────────────────────────────────────

    /// <summary>Returns a new empty builder for <see cref="AggregateVM2{VM1,VM2}"/>.</summary>
    public static AggregateVM2Builder Builder() => new();

    // ── Nested builder ──────────────────────────────────────────────────────

    /// <summary>
    /// Immutable fluent builder for <see cref="AggregateVM2{VM1,VM2}"/>.
    /// Each setter returns a NEW builder instance (BLD-001).
    /// </summary>
    public sealed class AggregateVM2Builder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly Func<VM1>? _factory1;
        private readonly Func<VM2>? _factory2;

        internal AggregateVM2Builder()
        {
            _hint = "";
        }

        private AggregateVM2Builder(
            string? name,
            string hint,
            IMessageHub? hub,
            IDispatcher? dispatcher,
            Func<VM1>? factory1,
            Func<VM2>? factory2)
        {
            _name = name;
            _hint = hint;
            _hub = hub;
            _dispatcher = dispatcher;
            _factory1 = factory1;
            _factory2 = factory2;
        }

        /// <summary>Sets the required Name field.</summary>
        public AggregateVM2Builder Name(string name)
            => new(name, _hint, _hub, _dispatcher, _factory1, _factory2);

        /// <summary>Sets the optional Hint field (default: empty string).</summary>
        public AggregateVM2Builder Hint(string hint)
            => new(_name, hint, _hub, _dispatcher, _factory1, _factory2);

        /// <summary>Sets the required Services (hub + dispatcher).</summary>
        public AggregateVM2Builder Services(IMessageHub hub, IDispatcher dispatcher)
            => new(_name, _hint, hub, dispatcher, _factory1, _factory2);

        /// <summary>Sets the required factory for Component1.</summary>
        public AggregateVM2Builder Component1(Func<VM1> factory)
            => new(_name, _hint, _hub, _dispatcher, factory, _factory2);

        /// <summary>Sets the required factory for Component2.</summary>
        public AggregateVM2Builder Component2(Func<VM2> factory)
            => new(_name, _hint, _hub, _dispatcher, _factory1, factory);

        /// <summary>
        /// Validates required fields and constructs a <see cref="AggregateVM2{VM1,VM2}"/>.
        /// Throws <see cref="BuilderValidationException"/> if a required field is missing.
        /// </summary>
        public AggregateVM2<VM1, VM2> Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            BuilderValidationException.Require(_factory1, "Component1");
            BuilderValidationException.Require(_factory2, "Component2");

            return new AggregateVM2<VM1, VM2>(_name, _hint, _hub, _dispatcher, _factory1, _factory2);
        }
    }
}
