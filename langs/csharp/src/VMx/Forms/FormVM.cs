using System.Reactive;
using System.Reactive.Subjects;
using System.Windows.Input;
using VMx.Commands;
using VMx.Messages;
using VMx.Services;

namespace VMx.Forms;

/// <summary>
/// ViewModel that wraps a mutable domain model with an edit lifecycle:
/// snapshot on construct, allow mutation, then either Approve (persist) or Deny (revert).
///
/// See spec/20-form-vm.md and ADR-0030.
/// </summary>
/// <typeparam name="TM">Domain model type. Record types are recommended for structural equality.</typeparam>
public sealed class FormVM<TM> : IDisposable
    where TM : notnull
{
    private readonly Func<TM, Task> _persister;
    private readonly Func<TM, TM> _snapshotter;
    private readonly bool _strict;
    private readonly IMessageHub _hub;
    private readonly Subject<TM> _onApproved = new();
    private readonly Subject<Unit> _canExecuteChangedTrigger = new();

    private TM _model;
    private TM _snapshot;
    private bool _disposed;

    // ── Constructors ──────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a <see cref="FormVM{TM}"/> with a delegate persister.
    /// </summary>
    /// <param name="initial">Initial domain model value; also becomes the initial Snapshot.</param>
    /// <param name="persister">Consumer-supplied async persist delegate. Throw on failure.</param>
    /// <param name="hub">Message hub for DenyCommand hub messages. Defaults to <see cref="NullMessageHub.Instance"/>.</param>
    /// <param name="strict">
    /// When <c>true</c>, <see cref="ApproveCommand"/>.<c>CanExecute</c> returns <c>false</c> when
    /// <see cref="IsDirty"/> is <c>false</c>. Defaults to <c>false</c>.
    /// </param>
    /// <param name="snapshotter">
    /// Custom snapshot function. Defaults to a shallow copy via <c>MemberwiseClone</c>.
    /// For record types this is equivalent to <c>with {}</c>.
    /// </param>
    public FormVM(
        TM initial,
        Func<TM, Task> persister,
        IMessageHub? hub = null,
        bool strict = false,
        Func<TM, TM>? snapshotter = null)
    {
#pragma warning disable CA1510 // ThrowIfNull not available on netstandard2.0 target
        if (initial is null) throw new ArgumentNullException(nameof(initial));
        if (persister is null) throw new ArgumentNullException(nameof(persister));
#pragma warning restore CA1510

        _persister = persister;
        _hub = hub ?? NullMessageHub.Instance;
        _strict = strict;
        _snapshotter = snapshotter ?? DefaultSnapshotter;

        _model = initial;
        _snapshot = _snapshotter(initial);

        IObservable<Unit> canExecuteTrigger = _canExecuteChangedTrigger;

        DenyCommand = RelayCommand.Builder()
            .Task(Deny)
            .Build();

        ApproveCommand = RelayCommand.Builder()
            .Task(() => _ = ApproveInternalAsync())
            .Predicate(() => !_strict || IsDirty)
            .Triggers(canExecuteTrigger)
            .Build();
    }

    /// <summary>
    /// Creates a <see cref="FormVM{TM}"/> with an <see cref="IFormPersister{TM}"/> interface collaborator.
    /// </summary>
    public FormVM(
        TM initial,
        IFormPersister<TM> persister,
        IMessageHub? hub = null,
        bool strict = false,
        Func<TM, TM>? snapshotter = null)
        : this(
            initial,
            persister is null ? throw new ArgumentNullException(nameof(persister)) : (Func<TM, Task>)(model => persister.PersistAsync(model)),
            hub,
            strict,
            snapshotter)
    {
    }

    // ── Properties ────────────────────────────────────────────────────────────

    /// <summary>Live, editable model. Set via <see cref="SetModel"/> to mutate.</summary>
    public TM Model => _model;

    /// <summary>Read-only snapshot captured at construction (updated after a successful Approve).</summary>
    public TM Snapshot => _snapshot;

    /// <summary>
    /// <c>true</c> when <see cref="Model"/> is structurally not equal to <see cref="Snapshot"/>.
    /// Uses <see cref="object.Equals(object?, object?)"/>; record types provide structural equality.
    /// </summary>
    public bool IsDirty => !Equals(_model, _snapshot);

    /// <summary>
    /// Reverts <see cref="Model"/> to <see cref="Snapshot"/> and publishes
    /// <see cref="FormRevertedMessage"/> + <see cref="PropertyChangedMessage{TSender}"/> on the hub.
    /// </summary>
    public ICommand DenyCommand { get; }

    /// <summary>
    /// Invokes the persister delegate; on success advances <see cref="Snapshot"/> and fires <see cref="OnApproved"/>.
    /// On failure, no state mutation occurs; the persister exception is observable
    /// via <see cref="ApproveAsync"/> only — <c>ApproveCommand.Execute()</c>
    /// dispatches the persist call fire-and-forget (per FORM-007 and chapter 20 §2).
    /// In strict mode, <c>CanExecute</c> is <c>false</c> when <see cref="IsDirty"/> is <c>false</c>.
    /// </summary>
    public ICommand ApproveCommand { get; }

    /// <summary>
    /// Observable that emits the current <see cref="Model"/> value after each successful persist.
    /// </summary>
    public IObservable<TM> OnApproved => _onApproved;

    /// <summary>
    /// Awaitable entry-point to the approve flow. Invokes the persister, advances
    /// <see cref="Snapshot"/> on success, and fires <see cref="OnApproved"/>.
    /// Throws when the persister throws (no state mutation occurs on failure).
    /// Use this in tests and orchestrators that need to await the full cycle.
    /// </summary>
    public Task ApproveAsync() => ApproveInternalAsync();

    // ── Public mutation ───────────────────────────────────────────────────────

    /// <summary>
    /// Replaces the current <see cref="Model"/>. Updating the model may change <see cref="IsDirty"/>;
    /// in strict mode it also fires <see cref="ICommand.CanExecuteChanged"/> on <see cref="ApproveCommand"/>.
    /// </summary>
    public void SetModel(TM model)
    {
#pragma warning disable CA1510 // ThrowIfNull not available on netstandard2.0 target
        if (model is null) throw new ArgumentNullException(nameof(model));
#pragma warning restore CA1510
        var wasDirty = IsDirty;
        _model = model;
        if (_strict && IsDirty != wasDirty)
            _canExecuteChangedTrigger.OnNext(Unit.Default);
    }

    // ── IDisposable ───────────────────────────────────────────────────────────

    /// <summary>Completes the <see cref="OnApproved"/> observable and disposes resources.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _onApproved.OnCompleted();
        _onApproved.Dispose();
        _canExecuteChangedTrigger.OnCompleted();
        _canExecuteChangedTrigger.Dispose();
        if (DenyCommand is IDisposable d1) d1.Dispose();
        if (ApproveCommand is IDisposable d2) d2.Dispose();
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    private void Deny()
    {
        var wasDirty = IsDirty;
        _model = _snapshotter(_snapshot);

        _hub.Send(new FormRevertedMessage(this, nameof(FormVM<TM>)));
        _hub.Send(PropertyChangedMessage<FormVM<TM>>.Create(this, nameof(FormVM<TM>), nameof(Model)));

        if (_strict && wasDirty != IsDirty)
            _canExecuteChangedTrigger.OnNext(Unit.Default);
    }

    private async Task ApproveInternalAsync()
    {
        // Capture model to avoid TOCTOU if SetModel is called concurrently.
        var current = _model;

        // May throw — intentional. No state mutation if this throws.
        await _persister(current).ConfigureAwait(false);

        // Success: advance snapshot and notify.
        var wasDirty = IsDirty;
        _snapshot = _snapshotter(current);

        if (_strict && wasDirty != IsDirty)
            _canExecuteChangedTrigger.OnNext(Unit.Default);

        _onApproved.OnNext(current);
    }

    private static TM DefaultSnapshotter(TM model)
    {
        // For record types, MemberwiseClone provides a shallow copy equivalent to `with {}`.
        // For non-record types the consumer should supply a custom snapshotter.
        var method = typeof(TM).GetMethod("MemberwiseClone",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
        if (method is not null)
            return (TM)method.Invoke(model, null)!;

        // Last resort: identity (works for immutable value types).
        return model;
    }
}
