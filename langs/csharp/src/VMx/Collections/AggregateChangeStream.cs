using System.ComponentModel;
using System.Reactive;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using System.Runtime.CompilerServices;
using System.Runtime.ExceptionServices;
using VMx.Components;

namespace VMx.Collections;

#pragma warning disable CA1711 // 'Stream' suffix: spec-mandated type name per spec/21-collections.md §9

/// <summary>Identifies why an aggregate change notification was emitted.</summary>
public enum AggregateChangeReason
{
    /// <summary>Subscriber-local readiness seed.</summary>
    Initial,

    /// <summary>A structural pulse committed a fresh ordered membership snapshot.</summary>
    Membership,

    /// <summary>A current member's selected change stream emitted.</summary>
    Item,

    /// <summary>One or more changes were coalesced by an explicit aggregate batch.</summary>
    Batch,
}

/// <summary>Reports aggregate change provenance without synthesizing domain state.</summary>
/// <typeparam name="T">Reference-identity membership item type.</typeparam>
public sealed class AggregateChange<T>
    where T : class
{
    internal AggregateChange(AggregateChangeReason reason, T? item = null)
    {
        Reason = reason;
        Item = item;
    }

    /// <summary>Gets the notification reason.</summary>
    public AggregateChangeReason Reason { get; }

    /// <summary>Gets the identical member for <see cref="AggregateChangeReason.Item"/>.</summary>
    public T? Item { get; }
}

/// <summary>
/// Follows live source membership and fans in one selected local change stream
/// per distinct current reference identity.
/// </summary>
/// <typeparam name="T">Reference-identity membership item type.</typeparam>
public sealed class AggregateChangeStream<T> : IDisposable
    where T : class
{
    private const long SetupFlag = 1;
    private const long StructuralVersionIncrement = 2;

    private readonly object _gate = new();
    private readonly IObservableMembershipSource<T> _source;
    private readonly Func<T, IObservable<Unit>> _observeItem;
    private readonly Dictionary<T, Entry> _entries = new(ReferenceComparer.Instance);
    private readonly List<Registration> _registrations = new();
    private readonly LinkedList<Work> _work = new();
    private readonly HashSet<Registration> _batchRecipients = new();

    private IDisposable? _membershipSubscription;
    private long _nextEpoch;
    private long _structuralState = SetupFlag;
    private bool _processing;
    private bool _completed;
    private Exception? _terminalError;
    private int _batchDepth;
    private bool _batchDirty;

    /// <summary>Creates an aggregate over <paramref name="source"/>.</summary>
    /// <param name="source">Live ordered membership source.</param>
    /// <param name="observeItem">Selects a non-failing local stream for each member.</param>
    public AggregateChangeStream(
        IObservableMembershipSource<T> source,
        Func<T, IObservable<Unit>> observeItem)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(observeItem);
#else
        if (source is null) throw new ArgumentNullException(nameof(source));
        if (observeItem is null) throw new ArgumentNullException(nameof(observeItem));
#endif
        _source = source;
        _observeItem = observeItem;

        lock (_gate)
        {
            try
            {
                _membershipSubscription = _source.SubscribeMembership(OnMembershipChanged);
                InitializeLocked();
            }
            catch (Exception error)
            {
                FailConstructionLocked();
                ExceptionDispatchInfo.Capture(error).Throw();
                throw;
            }
        }
    }

    /// <summary>
    /// Returns the hot output. When requested, this subscription receives one
    /// atomic subscriber-local <see cref="AggregateChangeReason.Initial"/> seed.
    /// </summary>
    public IObservable<AggregateChange<T>> Observe(bool emitInitial = false) =>
        new AggregateObservable(this, emitInitial);

    /// <summary>
    /// Runs <paramref name="action"/> in a nested ref-counted coalescing scope.
    /// The outermost dirty scope emits one <see cref="AggregateChangeReason.Batch"/>.
    /// </summary>
    public void Batch(Action action)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(action);
#else
        if (action is null) throw new ArgumentNullException(nameof(action));
#endif
        lock (_gate)
        {
#if NET8_0_OR_GREATER
            ObjectDisposedException.ThrowIf(_completed || _terminalError is not null, this);
#else
            if (_completed || _terminalError is not null)
                throw new ObjectDisposedException(nameof(AggregateChangeStream<T>));
#endif
            _batchDepth++;
        }

        Exception? bodyError = null;
        try
        {
            action();
        }
        catch (Exception error)
        {
            bodyError = error;
        }

        Exception? deliveryError = null;
        try
        {
            ExitBatch();
        }
        catch (Exception error)
        {
            deliveryError = error;
        }

        if (bodyError is not null) ExceptionDispatchInfo.Capture(bodyError).Throw();
        if (deliveryError is not null) ExceptionDispatchInfo.Capture(deliveryError).Throw();
    }

    /// <summary>Detaches owned subscriptions, completes output, and is idempotent.</summary>
    public void Dispose()
    {
        bool start;
        lock (_gate)
        {
            if (_completed || _terminalError is not null) return;
            _completed = true;
            CleanupSubscriptionsLocked();
            _work.Clear();
            Registration[] recipients = CurrentRegistrationsLocked();
            _registrations.Clear();
            if (recipients.Length > 0)
                _work.AddLast(Work.Completion(recipients));
            start = StartProcessingLocked();
        }

        if (start) ProcessWork();
    }

    private void InitializeLocked()
    {
        while (true)
        {
            long version = Volatile.Read(ref _structuralState);
            IReadOnlyList<T> snapshot = GetValidatedSnapshot();
            if (version != Volatile.Read(ref _structuralState)) continue;

            SnapshotPlan plan = BuildPlanLocked(snapshot);
            try
            {
                StageNewEntriesLocked(plan);
            }
            catch
            {
                DisposeStagedLocked(plan);
                throw;
            }

            if (version != Volatile.Read(ref _structuralState))
            {
                DisposeStagedLocked(plan);
                continue;
            }

            CommitPlanLocked(plan);
            if (version != Volatile.Read(ref _structuralState)) continue;

            DiscardBufferedItemsLocked();
            if (Interlocked.CompareExchange(
                    ref _structuralState,
                    version & ~SetupFlag,
                    version) == version)
            {
                return;
            }
        }
    }

    private void OnMembershipChanged()
    {
        // Version publication and setup classification are one atomic handoff:
        // either setup reconciliation sees this increment, or this is post-setup work.
        long state = Interlocked.Add(ref _structuralState, StructuralVersionIncrement);
        bool setupActivity = (state & SetupFlag) != 0;
        bool start = false;
        lock (_gate)
        {
            if (_completed || _terminalError is not null) return;
            if (setupActivity) return;

            bool coalesced = _batchDepth > 0;
            Registration[] recipients = CurrentRegistrationsLocked();
            if (coalesced) MarkBatchDirtyLocked(recipients);
            _work.AddLast(Work.Structural(coalesced, recipients));
            start = StartProcessingLocked();
        }

        if (start) ProcessWork();
    }

    private void OnItem(Entry entry)
    {
        // Synchronous/background values begun during initial staging are
        // pre-existing state even when they acquire the gate after construction.
        bool setupActivity = (Volatile.Read(ref _structuralState) & SetupFlag) != 0;
        bool start = false;
        lock (_gate)
        {
            if (_completed || _terminalError is not null || entry.Terminal) return;
            if (setupActivity) return;
            if (!entry.Admitted)
            {
                entry.BufferedItems++;
                return;
            }

            bool coalesced = _batchDepth > 0;
            Registration[] recipients = CurrentRegistrationsLocked();
            if (coalesced) MarkBatchDirtyLocked(recipients);
            _work.AddLast(Work.Item(
                entry,
                entry.Epoch,
                coalesced,
                recipients));
            start = StartProcessingLocked();
        }

        if (start) ProcessWork();
    }

    private void OnItemTerminal(Entry entry)
    {
        lock (_gate)
        {
            if (_completed || _terminalError is not null || entry.Terminal) return;
            entry.Terminal = true;
            entry.BufferedItems = 0;
            SafeDispose(entry.Subscription);
            entry.Subscription = null;
        }
    }

    private void ProcessWork()
    {
        Exception? firstDeliveryError = null;
        while (true)
        {
            Work? current = null;
            bool finished = false;
            lock (_gate)
            {
                if (_work.Count == 0)
                {
                    _processing = false;
                    finished = true;
                }
                else
                {
                    current = _work.First!.Value;
                    _work.RemoveFirst();

                    if (current.Kind == WorkKind.Structural)
                    {
                        ProcessStructuralLocked(current.Coalesced, current.Recipients!);
                        continue;
                    }

                    if (current.Kind == WorkKind.Item)
                    {
                        ProcessItemLocked(current);
                        continue;
                    }
                }
            }

            if (finished)
            {
                if (firstDeliveryError is not null)
                    ExceptionDispatchInfo.Capture(firstDeliveryError).Throw();
                return;
            }

            if (!AdmitGuardedDelivery(current!)) continue;
            try
            {
                Deliver(current!);
            }
            catch (Exception error)
            {
                firstDeliveryError ??= error;
            }
        }
    }

    private void ProcessStructuralLocked(bool coalesced, Registration[] recipients)
    {
        if (_completed || _terminalError is not null) return;
        try
        {
            while (true)
            {
                long version = Volatile.Read(ref _structuralState);
                IReadOnlyList<T> snapshot = GetValidatedSnapshot();
                if (version != Volatile.Read(ref _structuralState)) continue;

                SnapshotPlan plan = BuildPlanLocked(snapshot);
                try
                {
                    StageNewEntriesLocked(plan);
                }
                catch
                {
                    DisposeStagedLocked(plan);
                    throw;
                }

                if (version != Volatile.Read(ref _structuralState))
                {
                    DisposeStagedLocked(plan);
                    continue;
                }

                CommitPlanLocked(plan);
                if (version != Volatile.Read(ref _structuralState)) continue;

                var changes = new List<PendingChange>
                {
                    new(new AggregateChange<T>(AggregateChangeReason.Membership)),
                };
                AppendBufferedItemsLocked(changes);
                PrependChangesLocked(changes, coalesced, recipients);
                return;
            }
        }
        catch (Exception error)
        {
            FailExistingLocked(error);
        }
    }

    private void ProcessItemLocked(Work work)
    {
        Entry entry = work.Entry!;
        if (_completed || _terminalError is not null || !entry.Admitted || entry.Terminal)
            return;
        if (entry.Epoch != work.Epoch || entry.RefCount == 0) return;
        PrependChangesLocked(
            new[]
            {
                new PendingChange(
                    new AggregateChange<T>(AggregateChangeReason.Item, entry.Item),
                    entry,
                    work.Epoch),
            },
            work.Coalesced,
            work.Recipients!);
    }

    private IReadOnlyList<T> GetValidatedSnapshot()
    {
        IReadOnlyList<T> snapshot = _source.Snapshot()
            ?? throw new InvalidOperationException("Membership source returned a null snapshot.");
        for (int index = 0; index < snapshot.Count; index++)
        {
            if (snapshot[index] is null)
                throw new ArgumentException("Membership snapshots cannot contain null items.");
        }

        return snapshot;
    }

    private static SnapshotPlan BuildPlanLocked(IReadOnlyList<T> snapshot)
    {
        var counts = new Dictionary<T, int>(ReferenceComparer.Instance);
        foreach (T item in snapshot)
        {
            counts.TryGetValue(item, out int count);
            counts[item] = count + 1;
        }

        return new SnapshotPlan(counts);
    }

    private void StageNewEntriesLocked(SnapshotPlan plan)
    {
        foreach (KeyValuePair<T, int> membership in plan.Counts)
        {
            if (_entries.ContainsKey(membership.Key)) continue;

            var entry = new Entry(membership.Key, ++_nextEpoch, membership.Value);
            IObservable<Unit> selected = _observeItem(entry.Item)
                ?? throw new InvalidOperationException("The item-change selector returned null.");
            IDisposable subscription = selected.Subscribe(
                _ => OnItem(entry),
                _ => OnItemTerminal(entry),
                () => OnItemTerminal(entry));
            entry.Subscription = subscription
                ?? throw new InvalidOperationException("The selected stream returned a null subscription.");
            if (entry.Terminal)
            {
                SafeDispose(entry.Subscription);
                entry.Subscription = null;
            }

            plan.Staged.Add(entry);
        }
    }

    private void CommitPlanLocked(SnapshotPlan plan)
    {
        foreach (Entry existing in _entries.Values.ToArray())
        {
            if (plan.Counts.TryGetValue(existing.Item, out int count))
            {
                existing.RefCount = count;
                continue;
            }

            existing.Admitted = false;
            existing.RefCount = 0;
            existing.BufferedItems = 0;
            SafeDispose(existing.Subscription);
            existing.Subscription = null;
            _entries.Remove(existing.Item);
        }

        foreach (Entry staged in plan.Staged)
        {
            staged.Admitted = true;
            _entries.Add(staged.Item, staged);
        }
    }

    private void AppendBufferedItemsLocked(List<PendingChange> changes)
    {
        foreach (Entry entry in _entries.Values)
        {
            int bufferedItems = entry.Terminal ? 0 : entry.BufferedItems;
            entry.BufferedItems = 0;
            for (int index = 0; index < bufferedItems; index++)
            {
                changes.Add(new PendingChange(
                    new AggregateChange<T>(AggregateChangeReason.Item, entry.Item),
                    entry,
                    entry.Epoch));
            }
        }
    }

    private void DiscardBufferedItemsLocked()
    {
        foreach (Entry entry in _entries.Values) entry.BufferedItems = 0;
    }

    private static void DisposeStagedLocked(SnapshotPlan plan)
    {
        foreach (Entry staged in plan.Staged)
        {
            staged.Admitted = false;
            staged.BufferedItems = 0;
            SafeDispose(staged.Subscription);
            staged.Subscription = null;
        }
    }

    private void PrependChangesLocked(
        IReadOnlyList<PendingChange> changes,
        bool coalesced,
        Registration[] recipients)
    {
        if (changes.Count == 0) return;
        // Coalesced work marked the active batch dirty when the source event
        // occurred. Processing it after ExitBatch must not dirty the next batch.
        if (coalesced) return;

        if (recipients.Length == 0) return;
        for (int index = changes.Count - 1; index >= 0; index--)
        {
            PendingChange pending = changes[index];
            _work.AddFirst(Work.Notification(
                pending.Change,
                recipients,
                pending.Entry,
                pending.Epoch));
        }
    }

    private void ExitBatch()
    {
        bool start = false;
        lock (_gate)
        {
            _batchDepth--;
            if (_batchDepth == 0)
            {
                Registration[] recipients = _batchRecipients
                    .Where(registration => registration.Active)
                    .ToArray();
                _batchRecipients.Clear();
                if (!_batchDirty) return;

                _batchDirty = false;
                if (!_completed && _terminalError is null)
                {
                    if (recipients.Length > 0)
                    {
                        _work.AddLast(Work.Notification(
                            new AggregateChange<T>(AggregateChangeReason.Batch),
                            recipients));
                        start = StartProcessingLocked();
                    }
                }
            }
        }

        if (start) ProcessWork();
    }

    private IDisposable Subscribe(IObserver<AggregateChange<T>> observer, bool emitInitial)
    {
#if NET8_0_OR_GREATER
        ArgumentNullException.ThrowIfNull(observer);
#else
        if (observer is null) throw new ArgumentNullException(nameof(observer));
#endif
        Registration? registration = null;
        Exception? terminalError;
        bool completed;
        bool start = false;
        lock (_gate)
        {
            terminalError = _terminalError;
            completed = _completed;
            if (terminalError is null && !completed)
            {
                registration = new Registration(observer);
                _registrations.Add(registration);
                if (emitInitial)
                {
                    _work.AddLast(Work.Notification(
                        new AggregateChange<T>(AggregateChangeReason.Initial),
                        new[] { registration }));
                    start = StartProcessingLocked();
                }
            }
        }

        if (terminalError is not null)
        {
            observer.OnError(terminalError);
            return Disposable.Empty;
        }

        if (completed)
        {
            observer.OnCompleted();
            return Disposable.Empty;
        }

        try
        {
            if (start) ProcessWork();
        }
        catch
        {
            RemoveRegistration(registration!);
            throw;
        }

        return Disposable.Create(() => RemoveRegistration(registration!));
    }

    private void RemoveRegistration(Registration registration)
    {
        lock (_gate)
        {
            if (!registration.Active) return;
            registration.Active = false;
            _registrations.Remove(registration);
        }
    }

    private void FailConstructionLocked()
    {
        CleanupSubscriptionsLocked();
        _completed = true;
        _work.Clear();
    }

    private void FailExistingLocked(Exception error)
    {
        if (_completed || _terminalError is not null) return;
        _terminalError = error;
        CleanupSubscriptionsLocked();
        _work.Clear();
        Registration[] recipients = CurrentRegistrationsLocked();
        _registrations.Clear();
        if (recipients.Length > 0)
            _work.AddFirst(Work.ErrorDelivery(error, recipients));
    }

    private void CleanupSubscriptionsLocked()
    {
        SafeDispose(_membershipSubscription);
        _membershipSubscription = null;
        foreach (Entry entry in _entries.Values)
        {
            entry.Admitted = false;
            entry.RefCount = 0;
            entry.BufferedItems = 0;
            SafeDispose(entry.Subscription);
            entry.Subscription = null;
        }

        _entries.Clear();
        _batchRecipients.Clear();
        _batchDirty = false;
    }

    private Registration[] CurrentRegistrationsLocked() =>
        _registrations.Where(registration => registration.Active).ToArray();

    private void MarkBatchDirtyLocked(IEnumerable<Registration> recipients)
    {
        _batchDirty = true;
        foreach (Registration recipient in recipients) _batchRecipients.Add(recipient);
    }

    private bool StartProcessingLocked()
    {
        if (_processing || _work.Count == 0) return false;
        _processing = true;
        return true;
    }

    private bool AdmitGuardedDelivery(Work work)
    {
        Entry? entry = work.GuardEntry;
        if (entry is null) return true;

        lock (_gate)
        {
            if (_completed || _terminalError is not null || !entry.Admitted || entry.Terminal)
                return false;
            if (entry.Epoch != work.GuardEpoch || entry.RefCount == 0) return false;

            // This is the guarded event's delivery linearization point. A
            // completion/error admitted after it ends the epoch only for later work.
            work.GuardEntry = null;
            return true;
        }
    }

    private static void Deliver(Work work)
    {
        foreach (Registration registration in work.Recipients!)
        {
            if (!registration.Active) continue;
            switch (work.Kind)
            {
                case WorkKind.Notification:
                    registration.Observer.OnNext(work.Change!);
                    break;
                case WorkKind.Error:
                    registration.Active = false;
                    registration.Observer.OnError(work.Error!);
                    break;
                case WorkKind.Completion:
                    registration.Active = false;
                    registration.Observer.OnCompleted();
                    break;
            }
        }
    }

    private static void SafeDispose(IDisposable? disposable)
    {
        if (disposable is null) return;
        try
        {
            disposable.Dispose();
        }
        catch
        {
            // Cleanup must not replace the selector/body failure that caused it.
        }
    }

    private sealed class AggregateObservable : IObservable<AggregateChange<T>>
    {
        private readonly AggregateChangeStream<T> _owner;
        private readonly bool _emitInitial;

        internal AggregateObservable(AggregateChangeStream<T> owner, bool emitInitial)
        {
            _owner = owner;
            _emitInitial = emitInitial;
        }

        public IDisposable Subscribe(IObserver<AggregateChange<T>> observer) =>
            _owner.Subscribe(observer, _emitInitial);
    }

    private sealed class Entry
    {
        internal Entry(T item, long epoch, int refCount)
        {
            Item = item;
            Epoch = epoch;
            RefCount = refCount;
        }

        internal T Item { get; }

        internal long Epoch { get; }

        internal int RefCount { get; set; }

        internal IDisposable? Subscription { get; set; }

        internal bool Admitted { get; set; }

        internal bool Terminal { get; set; }

        internal int BufferedItems { get; set; }
    }

    private sealed class SnapshotPlan
    {
        internal SnapshotPlan(Dictionary<T, int> counts) => Counts = counts;

        internal Dictionary<T, int> Counts { get; }

        internal List<Entry> Staged { get; } = new();
    }

    private sealed class PendingChange
    {
        internal PendingChange(AggregateChange<T> change, Entry? entry = null, long epoch = 0)
        {
            Change = change;
            Entry = entry;
            Epoch = epoch;
        }

        internal AggregateChange<T> Change { get; }

        internal Entry? Entry { get; }

        internal long Epoch { get; }
    }

    private sealed class Registration
    {
        internal Registration(IObserver<AggregateChange<T>> observer) => Observer = observer;

        internal IObserver<AggregateChange<T>> Observer { get; }

        internal bool Active { get; set; } = true;
    }

    private enum WorkKind
    {
        Structural,
        Item,
        Notification,
        Error,
        Completion,
    }

    private sealed class Work
    {
        private Work(WorkKind kind) => Kind = kind;

        internal WorkKind Kind { get; }

        internal bool Coalesced { get; private set; }

        internal Entry? Entry { get; private set; }

        internal long Epoch { get; private set; }

        internal AggregateChange<T>? Change { get; private set; }

        internal Registration[]? Recipients { get; private set; }

        internal Exception? Error { get; private set; }

        internal Entry? GuardEntry { get; set; }

        internal long GuardEpoch { get; private set; }

        internal static Work Structural(bool coalesced, Registration[] recipients) =>
            new(WorkKind.Structural) { Coalesced = coalesced, Recipients = recipients };

        internal static Work Item(
            Entry entry,
            long epoch,
            bool coalesced,
            Registration[] recipients) =>
            new(WorkKind.Item)
            {
                Entry = entry,
                Epoch = epoch,
                Coalesced = coalesced,
                Recipients = recipients,
            };

        internal static Work Notification(
            AggregateChange<T> change,
            Registration[] recipients,
            Entry? guardEntry = null,
            long guardEpoch = 0) =>
            new(WorkKind.Notification)
            {
                Change = change,
                Recipients = recipients,
                GuardEntry = guardEntry,
                GuardEpoch = guardEpoch,
            };

        internal static Work ErrorDelivery(Exception error, Registration[] recipients) =>
            new(WorkKind.Error) { Error = error, Recipients = recipients };

        internal static Work Completion(Registration[] recipients) =>
            new(WorkKind.Completion) { Recipients = recipients };
    }

    private sealed class ReferenceComparer : IEqualityComparer<T>
    {
        internal static ReferenceComparer Instance { get; } = new();

        public bool Equals(T? x, T? y) => ReferenceEquals(x, y);

        public int GetHashCode(T obj) => RuntimeHelpers.GetHashCode(obj);
    }
}

/// <summary>Factory methods for common aggregate change stream selectors.</summary>
public static class AggregateChangeStream
{
    /// <summary>Creates an aggregate that observes each component's property changes.</summary>
    public static AggregateChangeStream<T> ForComponents<T>(
        IObservableMembershipSource<T> source)
        where T : class, IComponentVM =>
        new(
            source,
            item => Observable
                .FromEventPattern<PropertyChangedEventHandler, PropertyChangedEventArgs>(
                    handler => item.PropertyChanged += handler,
                    handler => item.PropertyChanged -= handler)
                .Select(_ => Unit.Default));
}

#pragma warning restore CA1711
