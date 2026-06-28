using System.Reactive;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Windows.Input;
using VMx.Commands;
using VMx.Internal;
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
    private readonly Subject<Exception> _approveErrors = new();
    private readonly Subject<Unit> _canExecuteChangedTrigger = new();

    private TM _model;
    private TM _snapshot;
    private bool _disposed;

    // ── Builder factory ───────────────────────────────────────────────────────

    /// <summary>
    /// Returns an empty <see cref="FormVMBuilder{TM}"/> for fluent construction.
    /// See ADR-0035 §2 FV1 / FV2.
    /// </summary>
    public static FormVMBuilder<TM> Builder() => FormVMBuilder<TM>.Empty;

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
    /// Custom snapshot function. Defaults to a deep clone via a
    /// <see cref="System.Text.Json"/> round-trip (so a nested-object mutation is
    /// tracked by <see cref="IsDirty"/> and reverted by <see cref="DenyCommand"/>).
    /// Inject this as the escape hatch for models JSON cannot round-trip.
    /// </param>
    public FormVM(
        TM initial,
        Func<TM, Task> persister,
        IMessageHub? hub = null,
        bool strict = false,
        Func<TM, TM>? snapshotter = null)
    {
        ThrowHelper.ThrowIfNull(initial, nameof(initial));
        ThrowHelper.ThrowIfNull(persister, nameof(persister));

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
            .Task(ApproveCommandExecute)
            .Predicate(() => !_strict || IsDirty)
            .Triggers(canExecuteTrigger)
            .Build();
    }

    // Fire-and-forget command entry-point. ApproveCommand.Execute() is void, so a
    // persister failure cannot propagate to the caller; route the faulted Task to
    // the ApproveErrors channel instead of discarding it (a discarded faulted Task
    // would otherwise surface only as an UnobservedTaskException at GC) (VMX-008).
    // Await ApproveAsync() to observe the failure inline.
    private void ApproveCommandExecute()
    {
        _ = ApproveInternalAsync().ContinueWith(
            t =>
            {
                if (_disposed) return;
                _approveErrors.OnNext(t.Exception!.GetBaseException());
            },
            CancellationToken.None,
            TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
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
    /// Observable that emits the persisted model value after each successful persist.
    /// </summary>
    public IObservable<TM> OnApproved => _onApproved.AsObservable();

    /// <summary>
    /// Observable that surfaces the persister exception when the approve
    /// <em>command</em> (<c>ApproveCommand.Execute()</c>) fails. That path is
    /// fire-and-forget (<see cref="ICommand.Execute"/> is <c>void</c>), so the
    /// failure cannot propagate to the caller; it is emitted here instead of
    /// being discarded with the faulted <see cref="Task"/> (VMX-008). The
    /// awaitable <see cref="ApproveAsync"/> path keeps its throw behavior — await
    /// it directly to handle the error inline. Completes on <see cref="Dispose"/>.
    /// </summary>
    public IObservable<Exception> ApproveErrors => _approveErrors.AsObservable();

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
        ThrowHelper.ThrowIfNull(model, nameof(model));
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
        _approveErrors.OnCompleted();
        _approveErrors.Dispose();
        _canExecuteChangedTrigger.OnCompleted();
        _canExecuteChangedTrigger.Dispose();
        if (DenyCommand is IDisposable d1) d1.Dispose();
        if (ApproveCommand is IDisposable d2) d2.Dispose();
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    private void Deny()
    {
        if (_disposed) return;
        var wasDirty = IsDirty;
        _model = _snapshotter(_snapshot);

        _hub.Send(new FormRevertedMessage(this, nameof(FormVM<TM>)));
        _hub.Send(PropertyChangedMessage<FormVM<TM>>.Create(this, nameof(FormVM<TM>), nameof(Model)));

        if (_strict && wasDirty != IsDirty)
            _canExecuteChangedTrigger.OnNext(Unit.Default);
    }

    private async Task ApproveInternalAsync()
    {
        // A disposed form is a full no-op — the persister must not be
        // invoked (symmetric with the Deny guard).
        if (_disposed) return;

        // Capture model to avoid TOCTOU if SetModel is called concurrently.
        var current = _model;

        // May throw — intentional. No state mutation if this throws.
        await _persister(current).ConfigureAwait(false);

        // Dispose() may have run during the await; the subjects below are
        // completed and disposed, so emitting would throw inside an
        // unobserved task.
        if (_disposed) return;

        // Success: advance snapshot and notify.
        var wasDirty = IsDirty;
        _snapshot = _snapshotter(current);

        if (_strict && wasDirty != IsDirty)
            _canExecuteChangedTrigger.OnNext(Unit.Default);

        _onApproved.OnNext(current);
    }

    // Cached per closed generic (one instance per TM): System.Text.Json caches
    // serialization metadata against the options instance, so reusing a single
    // instance avoids a per-call metadata rebuild (and CA1869).
    private static readonly System.Text.Json.JsonSerializerOptions DefaultSnapshotJsonOptions =
        new() { IncludeFields = true };

    /// <summary>
    /// Default deep-clone snapshotter: a <see cref="System.Text.Json"/> serialize→deserialize
    /// round-trip. A deep clone is required so the snapshot does not share nested
    /// mutable state with the live model — otherwise an in-place mutation of a
    /// nested object would be invisible to <see cref="IsDirty"/> and could not be
    /// reverted by <see cref="DenyCommand"/> (VMX-064). <c>System.Text.Json</c> is
    /// in the BCL, so no extra package is taken.
    /// <para>
    /// For models JSON cannot round-trip (delegates, cyclic graphs, non-public or
    /// non-default-constructible members, live handles, …) inject a custom
    /// <c>snapshotter</c> via the constructor or builder — that hook is the
    /// documented escape hatch and always overrides this default.
    /// </para>
    /// </summary>
    private static TM DefaultSnapshotter(TM model)
    {
        var json = System.Text.Json.JsonSerializer.Serialize(model, DefaultSnapshotJsonOptions);
        return System.Text.Json.JsonSerializer.Deserialize<TM>(json, DefaultSnapshotJsonOptions)!;
    }
}
