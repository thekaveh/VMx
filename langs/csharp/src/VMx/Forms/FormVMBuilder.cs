using VMx.Builders;
using VMx.Internal;
using VMx.Services;

namespace VMx.Forms;

/// <summary>
/// Immutable fluent builder for <see cref="FormVM{TM}"/>.
/// Each setter returns a new builder instance (BLD-001).
/// <see cref="Build"/> validates required fields and raises
/// <see cref="BuilderValidationException"/> on failure (BLD-002).
/// See ADR-0035 §2 FV1 / FV2 and spec/10-builders.md §3.
/// Use <c>FormVM&lt;TM&gt;.Builder()</c> to start.
/// </summary>
/// <typeparam name="TM">Domain model type. Record types are recommended for structural equality.</typeparam>
public sealed class FormVMBuilder<TM>
    where TM : notnull
{
    // ── Required ──────────────────────────────────────────────────────────────
    private readonly TM? _initial;
    private readonly bool _initialSet;
    private readonly Func<TM, Task>? _persister;

    // ── Optional ──────────────────────────────────────────────────────────────
    private readonly IMessageHub? _hub;
    private readonly bool _strict;
    private readonly Func<TM, TM>? _snapshotter;
    private readonly Dictionary<string, Func<TM, string?>> _validators;
    private readonly Func<TM, IReadOnlyDictionary<string, string?>>? _modelValidator;
    private readonly Func<TM, TM>? _resetOnApproved;

    /// <summary>Empty starting builder.</summary>
    public static readonly FormVMBuilder<TM> Empty = new();

    private FormVMBuilder()
    {
        _validators = new Dictionary<string, Func<TM, string?>>();
    }

    private FormVMBuilder(
        TM? initial,
        bool initialSet,
        Func<TM, Task>? persister,
        IMessageHub? hub,
        bool strict,
        Func<TM, TM>? snapshotter,
        Dictionary<string, Func<TM, string?>> validators,
        Func<TM, IReadOnlyDictionary<string, string?>>? modelValidator,
        Func<TM, TM>? resetOnApproved)
    {
        _initial = initial;
        _initialSet = initialSet;
        _persister = persister;
        _hub = hub;
        _strict = strict;
        _snapshotter = snapshotter;
        _validators = validators;
        _modelValidator = modelValidator;
        _resetOnApproved = resetOnApproved;
    }

    // ── Fluent setters ───────────────────────────────────────────────────────

    /// <summary>Sets the required initial domain model.</summary>
    public FormVMBuilder<TM> Initial(TM initial) => With(initial: initial, initialSet: true);

    /// <summary>Sets the required async persister delegate <c>(model) -&gt; Task</c>.</summary>
    public FormVMBuilder<TM> Persister(Func<TM, Task> persister) => With(persister: persister);

    /// <summary>
    /// C#-only convenience: wires the typed-interface persister overload by
    /// delegating to the <see cref="Func{TM, Task}"/> form via
    /// <see cref="IFormPersister{TM}.PersistAsync"/>.
    /// </summary>
    public FormVMBuilder<TM> WithFormPersister(IFormPersister<TM> persister)
    {
        ThrowHelper.ThrowIfNull(persister, nameof(persister));
        return With(persister: model => persister.PersistAsync(model));
    }

    /// <summary>Sets the optional message hub (default: <see cref="NullMessageHub.Instance"/>).</summary>
    public FormVMBuilder<TM> Hub(IMessageHub hub) => With(hub: hub);

    /// <summary>
    /// Enables strict mode: <c>ApproveCommand.CanExecute()</c> returns
    /// <c>false</c> when <see cref="FormVM{TM}.IsDirty"/> is <c>false</c>.
    /// Default: <c>false</c>.
    /// </summary>
    public FormVMBuilder<TM> Strict(bool strict) => With(strict: strict);

    /// <summary>
    /// Sets a custom snapshot function (default: a deep clone via a
    /// <see cref="System.Text.Json"/> round-trip; inject this as the escape
    /// hatch for models JSON cannot round-trip).
    /// </summary>
    public FormVMBuilder<TM> Snapshotter(Func<TM, TM> snapshotter) => With(snapshotter: snapshotter);

    /// <summary>Registers a field validator. The returned builder is a new instance.</summary>
    public FormVMBuilder<TM> Validator(string field, Func<TM, string?> validator)
    {
        var validators = new Dictionary<string, Func<TM, string?>>(_validators)
        {
            [field] = validator,
        };
        return With(validators: validators);
    }

    /// <summary>Registers a model-level validator returning field-name errors.</summary>
    public FormVMBuilder<TM> ModelValidator(
        Func<TM, IReadOnlyDictionary<string, string?>> modelValidator)
        => With(modelValidator: modelValidator);

    /// <summary>
    /// Sets an optional post-persist callback that derives the next pristine
    /// model from the captured approved value.
    /// </summary>
    public FormVMBuilder<TM> ResetOnApproved(Func<TM, TM> resetOnApproved)
        => With(resetOnApproved: resetOnApproved);

    // ── Build ────────────────────────────────────────────────────────────────

    /// <summary>
    /// Validates required fields and constructs a <see cref="FormVM{TM}"/>.
    /// </summary>
    /// <exception cref="BuilderValidationException">
    /// Thrown when <c>Initial</c> or <c>Persister</c> has not been set.
    /// </exception>
    public FormVM<TM> Build()
    {
        if (!_initialSet) throw new BuilderValidationException("Initial");
        BuilderValidationException.Require(_persister, "Persister");

        return new FormVM<TM>(
            _initial!,
            _persister,
            _hub,
            _strict,
            _snapshotter,
            _validators,
            _modelValidator,
            _resetOnApproved);
    }

    // ── Wither ───────────────────────────────────────────────────────────────

    private FormVMBuilder<TM> With(
        TM? initial = default,
        bool? initialSet = null,
        Func<TM, Task>? persister = null,
        IMessageHub? hub = null,
        bool? strict = null,
        Func<TM, TM>? snapshotter = null,
        Dictionary<string, Func<TM, string?>>? validators = null,
        Func<TM, IReadOnlyDictionary<string, string?>>? modelValidator = null,
        Func<TM, TM>? resetOnApproved = null)
        => new(
            initialSet == true ? initial : _initial,
            initialSet ?? _initialSet,
            persister ?? _persister,
            hub ?? _hub,
            strict ?? _strict,
            snapshotter ?? _snapshotter,
            validators ?? _validators,
            modelValidator ?? _modelValidator,
            resetOnApproved ?? _resetOnApproved);
}
