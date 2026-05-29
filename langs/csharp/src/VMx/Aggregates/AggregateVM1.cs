#pragma warning disable CA1715 // Spec uses 'VM' type parameter names per ADR-0006
using VMx.Builders;
using VMx.Components;
using VMx.Messages;
using VMx.Services;

namespace VMx.Aggregates;

/// <summary>
/// Arity-1 aggregate viewmodel. A fixed tuple of one heterogeneous component VM.
/// The component slot is populated lazily on construct() by invoking the factory
/// provided via the nested builder.
///
/// See spec/08-aggregate-vm.md and ADR-0007.
/// </summary>
/// <typeparam name="VM1">Type of the first component.</typeparam>
public sealed class AggregateVM1<VM1> : ComponentVMBase, IAggregateVM1<VM1>, IAggregateSlots
    where VM1 : class, IComponentVM
{
    private readonly Func<VM1> _factory1;
    private VM1? _component1;

    IEnumerable<IComponentVM> IAggregateSlots.EnumerateSlots()
    {
        if (_component1 is { } c1) yield return c1;
    }

    // ── IAggregateVM1<VM1> ──────────────────────────────────────────────────

    /// <inheritdoc/>
    public VM1? Component1 => _component1;

    // ── IComponentVM.Type ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public override ViewModelType Type => ViewModelType.Aggregate;

    // ── Constructor ─────────────────────────────────────────────────────────

    private AggregateVM1(
        string name,
        string hint,
        IMessageHub hub,
        IDispatcher dispatcher,
        Func<VM1> factory1)
        : base(name, hint, hub, dispatcher, onConstruct: null, onDestruct: null)
    {
        _factory1 = factory1;
    }

    // ── Lifecycle overrides ─────────────────────────────────────────────────

    /// <inheritdoc/>
    protected override void OnConstruct()
    {
        // On Reconstruct, the previous slot instance is in Destructed state but
        // still holds hub subscriptions and command Subjects. Dispose it before
        // overwriting so subscribers don't leak across the Reconstruct boundary.
        _component1?.Dispose();
        _component1 = _factory1();
        RaisePropertyChanged(nameof(Component1));
        Hub.Send(PropertyChangedMessage<IComponentVM>.Create(this, Name, nameof(Component1)));

        _component1.Construct();
    }

    /// <inheritdoc/>
    protected override void OnDestruct()
    {
        _component1?.Destruct();
    }

    /// <summary>
    /// Dispose cascade (LIFE-013): dispose each component slot depth-first, then self.
    /// </summary>
#pragma warning disable CA1816 // base.Dispose() already calls GC.SuppressFinalize(this)
    public override void Dispose()
    {
        _component1?.Dispose();
        base.Dispose(); // calls GC.SuppressFinalize(this)
    }
#pragma warning restore CA1816

    // ── Builder factory ─────────────────────────────────────────────────────

#pragma warning disable CA1000 // Generic static member on generic type: intentional per spec
    /// <summary>Returns a new empty builder for <see cref="AggregateVM1{VM1}"/>.</summary>
    public static AggregateVM1Builder Builder() => new();
#pragma warning restore CA1000

    // ── Nested builder ──────────────────────────────────────────────────────

    /// <summary>
    /// Immutable fluent builder for <see cref="AggregateVM1{VM1}"/>.
    /// Each setter returns a NEW builder instance (BLD-001).
    /// </summary>
    public sealed class AggregateVM1Builder
    {
        private readonly string? _name;
        private readonly string _hint;
        private readonly IMessageHub? _hub;
        private readonly IDispatcher? _dispatcher;
        private readonly Func<VM1>? _factory1;

        internal AggregateVM1Builder()
        {
            _hint = "";
        }

        private AggregateVM1Builder(
            string? name,
            string hint,
            IMessageHub? hub,
            IDispatcher? dispatcher,
            Func<VM1>? factory1)
        {
            _name = name;
            _hint = hint;
            _hub = hub;
            _dispatcher = dispatcher;
            _factory1 = factory1;
        }

        /// <summary>Sets the required Name field.</summary>
        public AggregateVM1Builder Name(string name)
            => new(name, _hint, _hub, _dispatcher, _factory1);

        /// <summary>Sets the optional Hint field (default: empty string).</summary>
        public AggregateVM1Builder Hint(string hint)
            => new(_name, hint, _hub, _dispatcher, _factory1);

        /// <summary>Sets the required Services (hub + dispatcher).</summary>
        public AggregateVM1Builder Services(IMessageHub hub, IDispatcher dispatcher)
            => new(_name, _hint, hub, dispatcher, _factory1);

        /// <summary>Sets the required factory for Component1.</summary>
        public AggregateVM1Builder Component1(Func<VM1> factory)
            => new(_name, _hint, _hub, _dispatcher, factory);

        /// <summary>
        /// Validates required fields and constructs a <see cref="AggregateVM1{VM1}"/>.
        /// Throws <see cref="BuilderValidationException"/> if a required field is missing.
        /// </summary>
        public AggregateVM1<VM1> Build()
        {
            BuilderValidationException.Require(_name, "Name");
            BuilderValidationException.Require(_hub, "Hub");
            BuilderValidationException.Require(_dispatcher, "Dispatcher");
            BuilderValidationException.Require(_factory1, "Component1");

            return new AggregateVM1<VM1>(_name, _hint, _hub, _dispatcher, _factory1);
        }
    }
}
#pragma warning restore CA1715
