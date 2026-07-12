using System.Reactive;
using System.Reactive.Disposables;
using VMx.Collections;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>Conformance tests for the dynamic aggregate change stream.</summary>
public sealed class AggregateChangeStreamConformanceTests
{
    [Fact, Trait("Conformance", "AGCH-001")]
    public void AGCH_001_InitialIsAtomicSubscriberLocalAndDoesNotReplayHistory()
    {
        var first = new TestItem("first");
        var source = new TestSource<TestItem>(first);
        using var aggregate = CreateAggregate(source);

        first.Changes.Emit();
        var withoutInitial = new List<AggregateChange<TestItem>>();
        var withInitial = new List<AggregateChange<TestItem>>();
        using var plainSubscription = aggregate.Observe().Subscribe(withoutInitial.Add);
        using var initialSubscription = aggregate.Observe(emitInitial: true).Subscribe(change =>
        {
            withInitial.Add(change);
            if (change.Reason == AggregateChangeReason.Initial)
                source.Add(new TestItem("racing"));
        });

        Assert.Empty(withoutInitial.Where(change => change.Reason == AggregateChangeReason.Initial));
        Assert.Equal(AggregateChangeReason.Initial, withInitial[0].Reason);
        Assert.Equal(AggregateChangeReason.Membership, withInitial[1].Reason);
        Assert.Single(withInitial.Where(change => change.Reason == AggregateChangeReason.Initial));
        Assert.Single(withoutInitial);
        Assert.Equal(AggregateChangeReason.Membership, withoutInitial[0].Reason);

        var queuedFirst = new TestItem("queued-first");
        var queuedSource = new TestSource<TestItem>(queuedFirst);
        using var queuedAggregate = CreateAggregate(queuedSource);
        var lateChanges = new List<AggregateChange<TestItem>>();
        IDisposable? lateSubscription = null;
        using var drivingSubscription = queuedAggregate.Observe().Subscribe(change =>
        {
            if (change.Reason != AggregateChangeReason.Item) return;
            queuedSource.Add(new TestItem("queued-before-subscribe"));
            lateSubscription = queuedAggregate.Observe(emitInitial: true).Subscribe(lateChanges.Add);
        });

        queuedFirst.Changes.Emit();

        Assert.Single(lateChanges);
        Assert.Equal(AggregateChangeReason.Initial, lateChanges[0].Reason);
        lateSubscription!.Dispose();
    }

    [Fact, Trait("Conformance", "AGCH-002")]
    public void AGCH_002_SetupRaceCommitsLatestMembershipAndStagesBehindMembership()
    {
        var first = new TestItem("first");
        var raced = new TestItem("raced");
        var source = new TestSource<TestItem>(first);
        var firstSnapshot = true;
        source.SnapshotOverride = () =>
        {
            TestItem[] snapshot = source.Items.ToArray();
            if (firstSnapshot)
            {
                firstSnapshot = false;
                source.AddWithoutPulse(raced);
                source.Pulse();
            }

            return snapshot;
        };

        using var aggregate = CreateAggregate(source);
        Assert.Equal(2, source.SnapshotCount);
        Assert.Equal(1, first.Changes.SubscribeCount);
        Assert.Equal(1, raced.Changes.SubscribeCount);

        var observed = new List<AggregateChange<TestItem>>();
        using var subscription = aggregate.Observe().Subscribe(observed.Add);
        var synchronous = new TestItem("synchronous");
        synchronous.Changes.EmitOnSubscribe = true;

        source.Add(synchronous);

        Assert.Equal(
            new[] { AggregateChangeReason.Membership, AggregateChangeReason.Item },
            observed.Select(change => change.Reason));
        Assert.Same(synchronous, observed[1].Item);

        var setupStructuralObserved = new List<AggregateChange<TestItem>>();
        var setupStructuralFirst = new TestItem("setup-structural-first");
        var setupStructuralRaced = new TestItem("setup-structural-raced");
        var setupStructuralSource = new TestSource<TestItem>(setupStructuralFirst);
        IDisposable? setupStructuralSubscription = null;
        Thread? setupStructuralThread = null;
        var runStructuralRace = true;
        setupStructuralSource.SnapshotOverride = () =>
        {
            TestItem[] snapshot = setupStructuralSource.Items.ToArray();
            if (!runStructuralRace) return snapshot;

            runStructuralRace = false;
            setupStructuralSource.AddWithoutPulse(setupStructuralRaced);
            var constructingAggregate = Assert.IsType<AggregateChangeStream<TestItem>>(
                setupStructuralSource.CallbackTarget);
            setupStructuralSubscription = constructingAggregate.Observe()
                .Subscribe(setupStructuralObserved.Add);
            setupStructuralThread = setupStructuralSource.PulseOnBackgroundAndWaitUntilBlocked();
            return snapshot;
        };

        using var setupStructuralAggregate = CreateAggregate(setupStructuralSource);
        Assert.True(setupStructuralThread!.Join(TimeSpan.FromSeconds(5)));
        Assert.Equal(1, setupStructuralRaced.Changes.SubscribeCount);
        Assert.Empty(setupStructuralObserved);
        setupStructuralSubscription!.Dispose();

        var setupItemObserved = new List<AggregateChange<TestItem>>();
        var setupItem = new TestItem("setup-item");
        var setupItemSource = new TestSource<TestItem>(setupItem);
        IDisposable? setupItemSubscription = null;
        setupItem.Changes.BeforeBackgroundEmitOnSubscribe = () =>
        {
            var constructingAggregate = Assert.IsType<AggregateChangeStream<TestItem>>(
                setupItemSource.CallbackTarget);
            setupItemSubscription = constructingAggregate.Observe().Subscribe(setupItemObserved.Add);
        };
        setupItem.Changes.EmitFromBackgroundOnSubscribe = true;

        using var setupItemAggregate = CreateAggregate(setupItemSource);
        Assert.True(setupItem.Changes.BackgroundEmitThread!.Join(TimeSpan.FromSeconds(5)));
        Assert.Empty(setupItemObserved);
        setupItemSubscription!.Dispose();
    }

    [Fact, Trait("Conformance", "AGCH-003")]
    public void AGCH_003_SelectedChangeCarriesCurrentMemberIdentity()
    {
        var item = new TestItem("nested");
        var source = new TestSource<TestItem>(item);
        using var aggregate = CreateAggregate(source);
        AggregateChange<TestItem>? observed = null;
        using var subscription = aggregate.Observe().Subscribe(change => observed = change);

        item.Changes.Emit();

        Assert.NotNull(observed);
        Assert.Equal(AggregateChangeReason.Item, observed!.Reason);
        Assert.Same(item, observed.Item);
    }

    [Fact, Trait("Conformance", "AGCH-004")]
    public void AGCH_004_ZeroRefcountAndTerminalEpochsStaySilentUntilReadd()
    {
        var first = new TestItem("first");
        var second = new TestItem("second");
        var source = new ServicedObservableCollection<TestItem> { first, second };
        using var aggregate = CreateAggregate(source);
        var observed = new List<AggregateChange<TestItem>>();
        using var subscription = aggregate.Observe().Subscribe(change =>
        {
            if (change.Reason == AggregateChangeReason.Membership && !source.Contains(first))
                Assert.Equal(1, first.Changes.DisposeCount);
            observed.Add(change);
        });

        first.Changes.Complete();
        first.Changes.EmitStale();
        second.Changes.Error(new SelectedStreamException());
        second.Changes.EmitStale();
        Assert.Empty(observed);

        source.Move(0, 1);
        source.ReplaceAll(new[] { second, first });
        source.Add(first);
        Assert.Equal(1, first.Changes.SubscribeCount);
        Assert.Equal(1, second.Changes.SubscribeCount);

        source.Remove(first);
        Assert.Equal(1, first.Changes.DisposeCount);
        source.Remove(first);
        Assert.Equal(1, first.Changes.DisposeCount);
        first.Changes.EmitStale();
        source.Add(first);
        Assert.Equal(2, first.Changes.SubscribeCount);
        first.Changes.Emit();
        Assert.Same(first, observed.Last().Item);
    }

    [Fact, Trait("Conformance", "AGCH-005")]
    public void AGCH_005_KeyedResetRebuildsTransactionallyAndRetainsIdentities()
    {
        var first = new TestItem("first");
        var retained = new TestItem("retained");
        var added = new TestItem("added");
        var source = new KeyedServicedObservableCollection<string, TestItem>(item => item.Name)
        {
            first,
            retained,
        };
        using var aggregate = CreateAggregate(source);
        var observed = new List<AggregateChange<TestItem>>();
        using var subscription = aggregate.Observe().Subscribe(observed.Add);

        source.ReplaceAll(new[] { retained, added });

        Assert.Single(observed);
        Assert.Equal(AggregateChangeReason.Membership, observed[0].Reason);
        Assert.Equal(1, first.Changes.DisposeCount);
        Assert.Equal(1, retained.Changes.SubscribeCount);
        Assert.Equal(1, added.Changes.SubscribeCount);
        added.Changes.Emit();
        Assert.Same(added, observed.Last().Item);
    }

    [Fact, Trait("Conformance", "AGCH-006")]
    public void AGCH_006_DuplicateReferencesShareOneRefcountedSubscription()
    {
        var item = new TestItem("duplicate");
        var source = new ServicedObservableCollection<TestItem> { item, item };
        using var aggregate = CreateAggregate(source);
        var observed = new List<AggregateChange<TestItem>>();
        using var subscription = aggregate.Observe().Subscribe(observed.Add);

        Assert.Equal(1, item.Changes.SubscribeCount);
        item.Changes.Emit();
        Assert.Single(observed.Where(change => change.Reason == AggregateChangeReason.Item));

        source.RemoveAt(0);
        Assert.Equal(0, item.Changes.DisposeCount);
        item.Changes.Emit();
        Assert.Equal(2, observed.Count(change => change.Reason == AggregateChangeReason.Item));

        source.RemoveAt(0);
        Assert.Equal(1, item.Changes.DisposeCount);
        item.Changes.EmitStale();
        Assert.Equal(2, observed.Count(change => change.Reason == AggregateChangeReason.Item));
    }

    [Fact, Trait("Conformance", "AGCH-007")]
    public void AGCH_007_NestedExceptionalBatchEmitsOnceAndPreservesBodyFailure()
    {
        var item = new TestItem("item");
        var source = new TestSource<TestItem>(item);
        using var aggregate = CreateAggregate(source);
        var observed = new List<AggregateChange<TestItem>>();
        using var safe = aggregate.Observe().Subscribe(observed.Add);
        using var throwing = aggregate.Observe().Subscribe(change =>
        {
            if (change.Reason == AggregateChangeReason.Batch)
                throw new DeliveryException();
        });
        var added = new TestItem("added");

        BodyException failure = Assert.Throws<BodyException>(() =>
            aggregate.Batch(() => aggregate.Batch(() =>
            {
                source.Add(added);
                item.Changes.Emit();
                throw new BodyException();
            })));

        Assert.NotNull(failure);
        Assert.Single(observed);
        Assert.Equal(AggregateChangeReason.Batch, observed[0].Reason);
        source.Remove(item);
        Assert.Equal(AggregateChangeReason.Membership, observed.Last().Reason);

        Assert.Throws<DeliveryException>(() => aggregate.Batch(added.Changes.Emit));
    }

    [Fact, Trait("Conformance", "AGCH-008")]
    public void AGCH_008_EmptyBatchAndMovePreserveSilenceAndSubscriptionsAcrossSourceFamilies()
    {
        var first = new TestItem("first");
        var second = new TestItem("second");
        var source = new TestSource<TestItem>(first, second);
        using var aggregate = CreateAggregate(source);
        var observed = new List<AggregateChange<TestItem>>();
        using var subscription = aggregate.Observe().Subscribe(observed.Add);

        aggregate.Batch(() => { });
        Assert.Empty(observed);
        source.Move(0, 1);
        Assert.Single(observed);
        Assert.Equal(AggregateChangeReason.Membership, observed[0].Reason);
        Assert.Equal(1, first.Changes.SubscribeCount);
        Assert.Equal(0, first.Changes.DisposeCount);

        var pendingItem = new TestItem("pending-item");
        var pendingSource = new TestSource<TestItem>(pendingItem);
        using var pendingAggregate = CreateAggregate(pendingSource);
        var pendingObserved = new List<AggregateChange<TestItem>>();
        var drivePendingBatch = true;
        using var pendingSubscription = pendingAggregate.Observe().Subscribe(change =>
        {
            pendingObserved.Add(change);
            if (!drivePendingBatch || change.Reason != AggregateChangeReason.Item) return;
            drivePendingBatch = false;
            pendingAggregate.Batch(() => pendingSource.Add(new TestItem("pending-added")));
        });

        pendingItem.Changes.Emit();
        Assert.Equal(
            new[] { AggregateChangeReason.Item, AggregateChangeReason.Batch },
            pendingObserved.Select(change => change.Reason));
        pendingObserved.Clear();
        pendingAggregate.Batch(() => { });
        Assert.Empty(pendingObserved);

        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var child = ComponentVM<string>.Builder()
            .Name("child").Services(hub, dispatcher).Model("before").Build();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("composite").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        var group = GroupVM<ComponentVM<string>>.Builder()
            .Name("group").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        AssertMembershipCapability(composite, child);
        AssertMembershipCapability(group, child);
    }

    [Fact, Trait("Conformance", "AGCH-009")]
    public void AGCH_009_ReentrantRemovalIsFifoAndRejectsQueuedStaleEpochWork()
    {
        var item = new TestItem("item");
        var source = new TestSource<TestItem>(item);
        using var aggregate = CreateAggregate(source);
        var observed = new List<AggregateChange<TestItem>>();
        using var subscription = aggregate.Observe().Subscribe(change =>
        {
            observed.Add(change);
            if (change.Reason == AggregateChangeReason.Item)
            {
                source.Remove(item);
                item.Changes.EmitStale();
            }
        });

        item.Changes.Emit();

        Assert.Equal(
            new[] { AggregateChangeReason.Item, AggregateChangeReason.Membership },
            observed.Select(change => change.Reason));
        source.Add(item);
        Assert.Equal(2, item.Changes.SubscribeCount);
        item.Changes.Emit();
        Assert.Equal(2, observed.Count(change => change.Reason == AggregateChangeReason.Item));
    }

    [Fact, Trait("Conformance", "AGCH-010")]
    public void AGCH_010_FailureDisposalOwnershipAndSubscriberEffectsAreBounded()
    {
        var valid = new TestItem("valid");
        var nullSource = new TestSource<TestItem>();
        nullSource.AddWithoutPulse(null!);
        Assert.Throws<ArgumentException>(() => CreateAggregate(nullSource));
        Assert.Equal(0, nullSource.StructuralSubscriberCount);

        var constructionFailure = new TestSource<TestItem>(valid, new TestItem("bad"));
        Assert.Throws<SelectorException>(() => new AggregateChangeStream<TestItem>(
            constructionFailure,
            item => item.Name == "bad" ? throw new SelectorException() : item.Changes));
        Assert.Equal(0, constructionFailure.StructuralSubscriberCount);
        Assert.Equal(1, valid.Changes.DisposeCount);

        var staged = new TestItem("staged");
        var subscribeFailureItem = new TestItem("subscribe-failure");
        var subscribeFailure = new SubscriptionException();
        subscribeFailureItem.Changes.SubscribeError = subscribeFailure;
        var subscriptionFailureSource = new TestSource<TestItem>(staged, subscribeFailureItem);
        Exception observedSubscriptionFailure = Assert.Throws<SubscriptionException>(() =>
            CreateAggregate(subscriptionFailureSource));
        Assert.Same(subscribeFailure, observedSubscriptionFailure);
        Assert.Equal(1, staged.Changes.DisposeCount);
        Assert.Equal(0, subscriptionFailureSource.StructuralSubscriberCount);

        var nullSelectedSource = new TestSource<TestItem>(new TestItem("null-selected"));
        Assert.Throws<InvalidOperationException>(() => new AggregateChangeStream<TestItem>(
            nullSelectedSource,
            _ => null!));
        Assert.Equal(0, nullSelectedSource.StructuralSubscriberCount);

        var laterValid = new TestItem("later-valid");
        var laterBad = new TestItem("later-bad");
        var source = new TestSource<TestItem>(laterValid);
        using var aggregate = new AggregateChangeStream<TestItem>(
            source,
            item => item.Name == "later-bad" ? throw new SelectorException() : item.Changes);
        Exception? terminal = null;
        var completed = 0;
        using var subscription = aggregate.Observe().Subscribe(_ => { }, error => terminal = error, () => completed++);

        source.Add(laterBad);

        Assert.IsType<SelectorException>(terminal);
        Assert.Equal(0, source.StructuralSubscriberCount);
        Assert.Equal(1, laterValid.Changes.DisposeCount);
        source.Add(new TestItem("ignored"));
        Assert.IsType<SelectorException>(terminal);

        aggregate.Dispose();
        aggregate.Dispose();
        Assert.Equal(0, laterValid.DisposeCount);
        Assert.Equal(0, completed);

        var componentHub = new TestHub();
        var dispatcher = new TestDispatcher();
        var component = ComponentVM<string>.Builder()
            .Name("component").Services(componentHub, dispatcher).Model("before").Build();
        var components = new ServicedObservableCollection<ComponentVM<string>> { component };
        using var componentAggregate = AggregateChangeStream.ForComponents(components);
        var componentChanges = new List<AggregateChange<ComponentVM<string>>>();
        var componentCompletions = 0;
        using var componentSubscription = componentAggregate.Observe().Subscribe(
            componentChanges.Add,
            () => componentCompletions++);
        component.Model = "after";
        Assert.Contains(componentChanges, change =>
            change.Reason == AggregateChangeReason.Item && ReferenceEquals(change.Item, component));

        componentAggregate.Dispose();
        componentAggregate.Dispose();
        Assert.Equal(1, componentCompletions);
        Assert.Equal("after", component.Model);

        var reentrantFirst = new TestItem("reentrant-first");
        var reentrantSecond = new TestItem("reentrant-second");
        var reentrantSource = new TestSource<TestItem>(reentrantFirst);
        using var reentrantAggregate = CreateAggregate(reentrantSource);
        var safeChanges = new List<AggregateChange<TestItem>>();
        var lateInitialChanges = new List<AggregateChange<TestItem>>();
        IDisposable? lateInitialSubscription = null;
        var throwOnce = true;
        using var failingObserver = reentrantAggregate.Observe().Subscribe(change =>
        {
            if (!throwOnce || change.Reason != AggregateChangeReason.Item) return;
            throwOnce = false;
            reentrantSource.Add(reentrantSecond);
            lateInitialSubscription = reentrantAggregate.Observe(emitInitial: true)
                .Subscribe(lateInitialChanges.Add);
            throw new DeliveryException();
        });
        using var safeObserver = reentrantAggregate.Observe().Subscribe(safeChanges.Add);

        Assert.Throws<DeliveryException>(reentrantFirst.Changes.Emit);
        Assert.Single(lateInitialChanges);
        Assert.Equal(AggregateChangeReason.Initial, lateInitialChanges[0].Reason);
        reentrantSecond.Changes.Emit();
        Assert.Equal(1, reentrantSecond.Changes.SubscribeCount);
        Assert.Contains(safeChanges, change =>
            change.Reason == AggregateChangeReason.Item && ReferenceEquals(change.Item, reentrantSecond));
        lateInitialSubscription!.Dispose();

        var completionItem = new TestItem("completion-item");
        var completionSource = new TestSource<TestItem>(completionItem);
        using var completionAggregate = CreateAggregate(completionSource);
        var completionCount = 0;
        using var completionFailingObserver = completionAggregate.Observe().Subscribe(change =>
        {
            if (change.Reason != AggregateChangeReason.Item) return;
            completionAggregate.Dispose();
            throw new DeliveryException();
        });
        using var completionObserver = completionAggregate.Observe().Subscribe(
            _ => { },
            () => completionCount++);
        Assert.Throws<DeliveryException>(completionItem.Changes.Emit);
        Assert.Equal(1, completionCount);
    }

    private static AggregateChangeStream<TestItem> CreateAggregate(
        IObservableMembershipSource<TestItem> source) =>
        new(source, item => item.Changes);

    private static void AssertMembershipCapability(
        IList<ComponentVM<string>> collection,
        ComponentVM<string> child)
    {
        var source = Assert.IsAssignableFrom<IObservableMembershipSource<ComponentVM<string>>>(collection);
        var pulses = 0;
        using var subscription = source.SubscribeMembership(() => pulses++);
        collection.Add(child);
        Assert.Equal(1, pulses);
        Assert.Single(source.Snapshot());
        collection.Remove(child);
        Assert.Equal(2, pulses);
    }

    private sealed class TestSource<T> : IObservableMembershipSource<T>
        where T : class
    {
        private readonly List<Action> _handlers = new();

        internal TestSource(params T[] items) => Items.AddRange(items);

        internal List<T> Items { get; } = new();

        internal Func<IReadOnlyList<T>>? SnapshotOverride { get; set; }

        internal int SnapshotCount { get; private set; }

        internal int StructuralSubscriberCount => _handlers.Count;

        internal object? CallbackTarget { get; private set; }

        public IReadOnlyList<T> Snapshot()
        {
            SnapshotCount++;
            return SnapshotOverride?.Invoke() ?? Items.ToArray();
        }

        public IDisposable SubscribeMembership(Action callback)
        {
            CallbackTarget = callback.Target;
            _handlers.Add(callback);
            return Disposable.Create(() => _handlers.Remove(callback));
        }

        internal void Add(T item)
        {
            Items.Add(item);
            Pulse();
        }

        internal void AddWithoutPulse(T item) => Items.Add(item);

        internal void Remove(T item)
        {
            Items.Remove(item);
            Pulse();
        }

        internal void Move(int oldIndex, int newIndex)
        {
            T item = Items[oldIndex];
            Items.RemoveAt(oldIndex);
            Items.Insert(newIndex, item);
            Pulse();
        }

        internal void Pulse()
        {
            foreach (Action handler in _handlers.ToArray()) handler();
        }

        internal Thread PulseOnBackgroundAndWaitUntilBlocked()
        {
            var thread = new Thread(Pulse);
            thread.Start();
            Assert.True(SpinWait.SpinUntil(
                () => (thread.ThreadState & ThreadState.WaitSleepJoin) != 0,
                TimeSpan.FromSeconds(5)));
            return thread;
        }
    }

    private sealed class TestItem : IDisposable
    {
        internal TestItem(string name) => Name = name;

        internal string Name { get; }

        internal CountedObservable Changes { get; } = new();

        internal int DisposeCount { get; private set; }

        public void Dispose() => DisposeCount++;
    }

    private sealed class CountedObservable : IObservable<Unit>
    {
        private readonly List<Observation> _observations = new();

        internal int SubscribeCount { get; private set; }

        internal int DisposeCount { get; private set; }

        internal bool EmitOnSubscribe { get; set; }

        internal bool EmitFromBackgroundOnSubscribe { get; set; }

        internal Action? BeforeBackgroundEmitOnSubscribe { get; set; }

        internal Thread? BackgroundEmitThread { get; private set; }

        internal Exception? SubscribeError { get; set; }

        public IDisposable Subscribe(IObserver<Unit> observer)
        {
            SubscribeCount++;
            if (SubscribeError is not null) throw SubscribeError;
            var observation = new Observation(observer);
            _observations.Add(observation);
            if (EmitOnSubscribe) observer.OnNext(Unit.Default);
            if (EmitFromBackgroundOnSubscribe)
            {
                BeforeBackgroundEmitOnSubscribe?.Invoke();
                BackgroundEmitThread = new Thread(() => observer.OnNext(Unit.Default));
                BackgroundEmitThread.Start();
                Assert.True(SpinWait.SpinUntil(
                    () => (BackgroundEmitThread.ThreadState & ThreadState.WaitSleepJoin) != 0,
                    TimeSpan.FromSeconds(5)));
            }
            return Disposable.Create(() =>
            {
                if (!observation.Active) return;
                observation.Active = false;
                DisposeCount++;
            });
        }

        internal void Emit()
        {
            foreach (Observation observation in _observations.Where(item => item.Active).ToArray())
                observation.Observer.OnNext(Unit.Default);
        }

        internal void EmitStale()
        {
            foreach (Observation observation in _observations.ToArray())
                observation.Observer.OnNext(Unit.Default);
        }

        internal void Complete()
        {
            foreach (Observation observation in _observations.Where(item => item.Active).ToArray())
                observation.Observer.OnCompleted();
        }

        internal void Error(Exception error)
        {
            foreach (Observation observation in _observations.Where(item => item.Active).ToArray())
                observation.Observer.OnError(error);
        }

        private sealed class Observation
        {
            internal Observation(IObserver<Unit> observer) => Observer = observer;

            internal IObserver<Unit> Observer { get; }

            internal bool Active { get; set; } = true;
        }
    }

    private sealed class BodyException : Exception;

    private sealed class DeliveryException : Exception;

    private sealed class SelectedStreamException : Exception;

    private sealed class SelectorException : Exception;

    private sealed class SubscriptionException : Exception;
}
