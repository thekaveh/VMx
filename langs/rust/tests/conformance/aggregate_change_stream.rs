use std::collections::HashMap;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{Arc, Condvar, Mutex};

use vmx::{
    AggregateChange, AggregateChangeReason, AggregateChangeStream, AggregateChangeSubscription,
    AggregateObserveOptions, ComponentVm, CompositeVm, ConstructionStatus, GroupVm,
    KeyedServicedObservableCollection, Message, MessageHub, NullDispatcher,
    ObservableMembershipSource, ObservablePropertySource, PropertyChangedStream,
    ServicedObservableCollection, Subscription, VmNode, VmxResult,
};

fn locked<T>(value: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    value
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[derive(Clone)]
struct TestNode {
    logical_id: usize,
    inner: ComponentVm,
    dispose_count: Arc<Mutex<usize>>,
    lifetime: Arc<()>,
}

impl TestNode {
    fn new(logical_id: usize, name: &str) -> Self {
        Self {
            logical_id,
            inner: ComponentVm::new(name),
            dispose_count: Arc::new(Mutex::new(0)),
            lifetime: Arc::new(()),
        }
    }

    fn emit(&self) {
        self.inner.notify_property_changed("value");
    }

    fn weak_lifetime(&self) -> std::sync::Weak<()> {
        Arc::downgrade(&self.lifetime)
    }

    fn hub(&self) -> MessageHub {
        self.inner.hub()
    }
}

impl PartialEq for TestNode {
    fn eq(&self, other: &Self) -> bool {
        self.logical_id == other.logical_id
    }
}

impl VmNode for TestNode {
    fn id(&self) -> usize {
        self.logical_id
    }

    fn construct(&self) -> VmxResult<()> {
        self.inner.construct()
    }

    fn destruct(&self) -> VmxResult<()> {
        self.inner.destruct()
    }

    fn dispose(&self) -> VmxResult<()> {
        *locked(&self.dispose_count) += 1;
        self.inner.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.inner.parent_id()
    }
}

impl ObservablePropertySource for TestNode {
    fn property_changed(&self) -> PropertyChangedStream {
        self.inner.property_changed()
    }
}

type SnapshotHook = Arc<Mutex<Option<Arc<dyn Fn() + Send + Sync>>>>;

#[derive(Default)]
struct EmissionGateState {
    entered_hub: bool,
    released: bool,
    emission_done: bool,
}

#[derive(Clone, Default)]
struct EmissionGate {
    state: Arc<(Mutex<EmissionGateState>, Condvar)>,
}

impl EmissionGate {
    fn block_hub(&self, node: &TestNode) -> Subscription {
        let state = Arc::clone(&self.state);
        node.hub().subscribe(move |message| {
            if !matches!(message, Message::PropertyChanged(_)) {
                return;
            }
            let (mutex, ready) = state.as_ref();
            let mut gate = locked(mutex);
            gate.entered_hub = true;
            ready.notify_all();
            while !gate.released {
                gate = ready
                    .wait(gate)
                    .unwrap_or_else(|poisoned| poisoned.into_inner());
            }
        })
    }

    fn wait_until_blocked(&self) {
        let (mutex, ready) = self.state.as_ref();
        let mut gate = locked(mutex);
        while !gate.entered_hub {
            gate = ready
                .wait(gate)
                .unwrap_or_else(|poisoned| poisoned.into_inner());
        }
    }

    fn release_and_wait(&self) {
        let (mutex, ready) = self.state.as_ref();
        let mut gate = locked(mutex);
        gate.released = true;
        ready.notify_all();
        while !gate.emission_done {
            gate = ready
                .wait(gate)
                .unwrap_or_else(|poisoned| poisoned.into_inner());
        }
    }

    fn mark_done(&self) {
        let (mutex, ready) = self.state.as_ref();
        locked(mutex).emission_done = true;
        ready.notify_all();
    }
}

#[derive(Clone)]
struct TestSource {
    items: Arc<Mutex<Vec<TestNode>>>,
    membership: MessageHub,
    snapshot_hook: SnapshotHook,
    snapshot_count: Arc<Mutex<usize>>,
}

impl TestSource {
    fn new(items: Vec<TestNode>) -> Self {
        Self {
            items: Arc::new(Mutex::new(items)),
            membership: MessageHub::new(),
            snapshot_hook: Arc::new(Mutex::new(None)),
            snapshot_count: Arc::new(Mutex::new(0)),
        }
    }

    fn pulse(&self) {
        self.membership.send(Message::Custom {
            sender_id: 0,
            name: "membership".to_string(),
        });
    }

    fn add(&self, item: TestNode) {
        locked(&self.items).push(item);
        self.pulse();
    }

    fn remove_id(&self, id: usize) {
        let mut items = locked(&self.items);
        if let Some(index) = items.iter().position(|item| item.id() == id) {
            items.remove(index);
        }
        drop(items);
        self.pulse();
    }

    fn on_next_snapshot<F>(&self, hook: F)
    where
        F: Fn() + Send + Sync + 'static,
    {
        *locked(&self.snapshot_hook) = Some(Arc::new(hook));
    }

    fn replace_all(&self, items: Vec<TestNode>) {
        *locked(&self.items) = items;
        self.pulse();
    }
}

impl ObservableMembershipSource<TestNode> for TestSource {
    fn snapshot(&self) -> Vec<TestNode> {
        *locked(&self.snapshot_count) += 1;
        let snapshot = locked(&self.items).clone();
        if let Some(hook) = locked(&self.snapshot_hook).take() {
            hook();
        }
        snapshot
    }

    fn subscribe_membership<F>(&self, handler: F) -> Subscription
    where
        F: Fn() + Send + Sync + 'static,
    {
        self.membership.subscribe(move |_| handler())
    }
}

fn aggregate<S>(source: S) -> AggregateChangeStream<TestNode>
where
    S: ObservableMembershipSource<TestNode>,
{
    AggregateChangeStream::new(source, |item| item.property_changed())
}

fn reasons(changes: &Arc<Mutex<Vec<AggregateChange<TestNode>>>>) -> Vec<AggregateChangeReason> {
    locked(changes).iter().map(|change| change.reason).collect()
}

type CollectedChanges = Arc<Mutex<Vec<AggregateChange<TestNode>>>>;
type Collected = (CollectedChanges, AggregateChangeSubscription<TestNode>);

fn collect(
    aggregate: &AggregateChangeStream<TestNode>,
    options: AggregateObserveOptions,
) -> Collected {
    let changes = Arc::new(Mutex::new(Vec::new()));
    let captured = Arc::clone(&changes);
    let subscription = aggregate
        .observe(options)
        .subscribe(move |change| locked(&captured).push(change));
    (changes, subscription)
}

/// AGCH-001 — optional initial delivery is atomic and subscriber-local
#[test]
fn aggregate_initial_is_subscriber_local_and_precedes_reentrant_work() {
    let source = TestSource::new(vec![TestNode::new(1, "first")]);
    let aggregate = aggregate(source.clone());
    let (plain, _plain_subscription) = collect(&aggregate, AggregateObserveOptions::default());
    let seeded = Arc::new(Mutex::new(Vec::new()));
    let seeded_capture = Arc::clone(&seeded);
    let source_capture = source.clone();
    let subscription = aggregate
        .observe(AggregateObserveOptions::default().emit_initial(true))
        .subscribe(move |change| {
            let initial = change.reason == AggregateChangeReason::Initial;
            locked(&seeded_capture).push(change);
            if initial {
                source_capture.add(TestNode::new(2, "racing"));
            }
        });

    assert_eq!(
        reasons(&seeded),
        vec![
            AggregateChangeReason::Initial,
            AggregateChangeReason::Membership
        ]
    );
    assert_eq!(reasons(&plain), vec![AggregateChangeReason::Membership]);
    drop(subscription);
}

/// AGCH-002 — structural reconciliation commits before staged item delivery
#[test]
fn aggregate_structural_reconciliation_orders_membership_before_item() {
    let first = TestNode::new(2, "first");
    let raced = TestNode::new(3, "setup-race");
    let source = TestSource::new(vec![first]);
    let race_source = source.clone();
    source.on_next_snapshot(move || race_source.add(raced.clone()));
    let aggregate = aggregate(source.clone());
    assert_eq!(*locked(&source.snapshot_count), 2);
    let (changes, _subscription) = collect(&aggregate, AggregateObserveOptions::default());
    let added = TestNode::new(18, "added");
    source.add(added.clone());
    added.emit();

    assert_eq!(
        reasons(&changes),
        vec![
            AggregateChangeReason::Membership,
            AggregateChangeReason::Item
        ]
    );
    assert_eq!(locked(&changes)[1].item.as_ref().map(VmNode::id), Some(18));

    let staged_nodes = vec![
        TestNode::new(21, "staged-a"),
        TestNode::new(22, "staged-b"),
        TestNode::new(23, "staged-c"),
    ];
    let gates = Arc::new(
        staged_nodes
            .iter()
            .map(|node| (node.id(), EmissionGate::default()))
            .collect::<HashMap<_, _>>(),
    );
    let staged_source = TestSource::new(Vec::new());
    let selected_order = Arc::new(Mutex::new(Vec::new()));
    let selector_order = Arc::clone(&selected_order);
    let selector_gates = Arc::clone(&gates);
    let staged_aggregate =
        AggregateChangeStream::new(staged_source.clone(), move |item: &TestNode| {
            let previous = {
                let mut order = locked(&selector_order);
                let previous = order.last().copied();
                order.push(item.id());
                previous
            };
            if let Some(previous) = previous {
                selector_gates[&previous].release_and_wait();
            }
            item.property_changed()
        });
    let (staged_changes, _staged_subscription) =
        collect(&staged_aggregate, AggregateObserveOptions::default());
    let blockers = staged_nodes
        .iter()
        .map(|node| gates[&node.id()].block_hub(node))
        .collect::<Vec<_>>();
    let emitters = staged_nodes
        .iter()
        .map(|node| {
            let node = node.clone();
            let gate = gates[&node.id()].clone();
            std::thread::spawn(move || {
                node.emit();
                gate.mark_done();
            })
        })
        .collect::<Vec<_>>();
    for gate in gates.values() {
        gate.wait_until_blocked();
    }

    staged_source.replace_all(staged_nodes);

    let order = locked(&selected_order).clone();
    assert_eq!(
        reasons(&staged_changes),
        vec![
            AggregateChangeReason::Membership,
            AggregateChangeReason::Item,
            AggregateChangeReason::Item,
        ]
    );
    let item_order = locked(&staged_changes)[1..]
        .iter()
        .filter_map(|change| change.item.as_ref().map(VmNode::id))
        .collect::<Vec<_>>();
    assert_eq!(item_order, order[..2]);
    gates[order.last().expect("three selectors")].release_and_wait();
    for emitter in emitters {
        emitter.join().unwrap();
    }
    drop(blockers);
}

/// AGCH-003 — selected changes carry the identical current member
#[test]
fn aggregate_item_change_carries_current_member() {
    let item = TestNode::new(4, "nested");
    let aggregate = aggregate(TestSource::new(vec![item.clone()]));
    let (changes, _subscription) = collect(&aggregate, AggregateObserveOptions::default());

    item.emit();

    assert_eq!(reasons(&changes), vec![AggregateChangeReason::Item]);
    assert_eq!(locked(&changes)[0].item.as_ref().map(VmNode::id), Some(4));
}

/// AGCH-004 — zero-refcount and terminal membership epochs are silent
#[test]
fn aggregate_terminal_epoch_stays_silent_until_remove_and_readd() {
    let item = TestNode::new(5, "terminal");
    let source = TestSource::new(vec![item.clone()]);
    let aggregate = aggregate(source.clone());
    let (changes, _subscription) = collect(&aggregate, AggregateObserveOptions::default());

    item.dispose().unwrap();
    item.emit();
    source.pulse();
    assert_eq!(reasons(&changes), vec![AggregateChangeReason::Membership]);

    source.remove_id(item.id());
    let fresh = TestNode::new(5, "fresh-epoch");
    source.add(fresh.clone());
    fresh.emit();
    assert_eq!(reasons(&changes).last(), Some(&AggregateChangeReason::Item));
}

/// AGCH-005 — Reset rebuilds membership transactionally
#[test]
fn aggregate_keyed_reset_retains_and_rebuilds_membership() {
    let first = TestNode::new(6, "first");
    let retained = TestNode::new(7, "retained");
    let added = TestNode::new(8, "added");
    let source = KeyedServicedObservableCollection::new(50, |item: &TestNode| Ok(item.id()));
    source.push(first.clone()).unwrap();
    source.push(retained.clone()).unwrap();
    let aggregate = aggregate(source.clone());
    let (changes, _subscription) = collect(&aggregate, AggregateObserveOptions::default());

    source
        .replace_all([retained.clone(), added.clone()])
        .unwrap();
    added.emit();

    assert_eq!(
        reasons(&changes),
        vec![
            AggregateChangeReason::Membership,
            AggregateChangeReason::Item
        ]
    );
    first.emit();
    assert_eq!(reasons(&changes).len(), 2);
}

/// AGCH-006 — duplicate VM identities share one refcounted subscription
#[test]
fn aggregate_duplicate_id_has_one_behavioral_subscription() {
    let item = TestNode::new(9, "duplicate");
    let source = TestSource::new(vec![item.clone(), item.clone()]);
    let aggregate = aggregate(source.clone());
    let (changes, _subscription) = collect(&aggregate, AggregateObserveOptions::default());

    item.emit();
    assert_eq!(reasons(&changes), vec![AggregateChangeReason::Item]);
    source.remove_id(item.id());
    item.emit();
    assert_eq!(reasons(&changes).last(), Some(&AggregateChangeReason::Item));
    source.remove_id(item.id());
    let before = reasons(&changes).len();
    item.emit();
    assert_eq!(reasons(&changes).len(), before);
}

/// AGCH-007 — nested exceptional batches emit once and preserve body panic
#[test]
fn aggregate_nested_exceptional_batch_preserves_body_panic() {
    let item = TestNode::new(10, "batched");
    let source = TestSource::new(vec![item.clone()]);
    let aggregate = aggregate(source.clone());
    let (changes, _subscription) = collect(&aggregate, AggregateObserveOptions::default());
    let throwing = aggregate
        .observe(AggregateObserveOptions::default())
        .subscribe(|change| {
            if change.reason == AggregateChangeReason::Batch {
                panic!("delivery");
            }
        });

    let outcome = catch_unwind(AssertUnwindSafe(|| {
        aggregate.batch(|| {
            item.emit();
            aggregate.batch(|| source.add(TestNode::new(11, "added")));
            panic!("body");
        });
    }));

    let body = outcome.unwrap_err();
    assert_eq!(body.downcast_ref::<&str>(), Some(&"body"));
    assert_eq!(reasons(&changes), vec![AggregateChangeReason::Batch]);
    drop(throwing);
    item.emit();
    assert_eq!(reasons(&changes).last(), Some(&AggregateChangeReason::Item));
}

/// AGCH-008 — empty batches are silent and Move preserves item observation
#[test]
fn aggregate_empty_batch_and_serviced_move_are_stable() {
    let first = TestNode::new(12, "first");
    let second = TestNode::new(13, "second");
    let source = ServicedObservableCollection::new(51);
    source.push(first.clone());
    source.push(second);
    let aggregate = aggregate(source.clone());
    let (changes, _subscription) = collect(&aggregate, AggregateObserveOptions::default());

    aggregate.batch(|| {});
    assert!(locked(&changes).is_empty());
    source.move_item(0, 1).unwrap();
    first.emit();
    assert_eq!(
        reasons(&changes),
        vec![
            AggregateChangeReason::Membership,
            AggregateChangeReason::Item
        ]
    );

    let late = Arc::new(Mutex::new(Vec::new()));
    let late_capture = Arc::clone(&late);
    let mut late_subscription = None;
    aggregate.batch(|| {
        first.emit();
        late_subscription = Some(
            aggregate
                .observe(AggregateObserveOptions::default())
                .subscribe(move |change| locked(&late_capture).push(change)),
        );
    });
    assert_eq!(
        reasons(&changes).last(),
        Some(&AggregateChangeReason::Batch)
    );
    assert!(locked(&late).is_empty());
    drop(late_subscription);
}

/// AGCH-009 — reentrant FIFO delivery rejects removed-epoch callbacks
#[test]
fn aggregate_reentrant_removal_is_fifo_and_stale_safe() {
    let item = TestNode::new(14, "reentrant");
    let source = TestSource::new(vec![item.clone()]);
    let aggregate = aggregate(source.clone());
    let changes = Arc::new(Mutex::new(Vec::new()));
    let changes_capture = Arc::clone(&changes);
    let source_capture = source.clone();
    let item_capture = item.clone();
    let subscription = aggregate
        .observe(AggregateObserveOptions::default())
        .subscribe(move |change| {
            let should_remove = change.reason == AggregateChangeReason::Item
                && locked(&source_capture.items).len() == 1;
            locked(&changes_capture).push(change);
            if should_remove {
                source_capture.remove_id(item_capture.id());
                item_capture.emit();
            }
        });

    item.emit();

    assert_eq!(
        reasons(&changes),
        vec![
            AggregateChangeReason::Item,
            AggregateChangeReason::Membership
        ]
    );
    drop(subscription);
}

/// AGCH-010 — disposal, ownership, adapters, and subscribers are bounded
#[test]
fn aggregate_disposal_ownership_and_normal_adapters_are_bounded() {
    let item = TestNode::new(15, "owned");
    let source = TestSource::new(vec![item.clone()]);
    let aggregate = AggregateChangeStream::for_components(source.clone());
    let completions = Arc::new(Mutex::new(0));
    let completions_capture = Arc::clone(&completions);
    let subscription = aggregate
        .observe(AggregateObserveOptions::default())
        .subscribe_with_completion(|_| {}, move || *locked(&completions_capture) += 1);

    item.emit();
    aggregate.dispose();
    aggregate.dispose();
    item.emit();
    source.add(TestNode::new(16, "ignored"));
    assert_eq!(*locked(&completions), 1);
    assert_eq!(*locked(&item.dispose_count), 0);
    drop(subscription);

    let shared_hub = MessageHub::new();
    let composite =
        CompositeVm::with_services("composite", shared_hub.clone(), NullDispatcher::new());
    let group = GroupVm::with_services("group", shared_hub.clone(), NullDispatcher::new());
    let child = TestNode::new(17, "child");
    let composite_pulses = Arc::new(Mutex::new(0));
    let group_pulses = Arc::new(Mutex::new(0));
    let composite_capture = Arc::clone(&composite_pulses);
    let group_capture = Arc::clone(&group_pulses);
    let composite_subscription =
        composite.subscribe_membership(move || *locked(&composite_capture) += 1);
    let group_subscription = group.subscribe_membership(move || *locked(&group_capture) += 1);
    composite.add(child.clone()).unwrap();
    assert_eq!(*locked(&group_pulses), 0);
    group.add(child).unwrap();
    assert_eq!(composite.snapshot().len(), 1);
    assert_eq!(group.snapshot().len(), 1);
    assert_eq!(*locked(&composite_pulses), 1);
    assert_eq!(*locked(&group_pulses), 1);
    shared_hub.send(Message::CollectionChanged(vmx::CollectionChangedMessage {
        sender_id: usize::MAX,
        property_name: "items".to_string(),
        action: vmx::CollectionChangeAction::Reset,
        old_index: None,
        new_index: None,
    }));
    assert_eq!(*locked(&composite_pulses), 1);
    assert_eq!(*locked(&group_pulses), 1);
    drop((composite_subscription, group_subscription));

    let panic_source = TestSource::new(vec![TestNode::new(19, "panic-initial")]);
    let panic_item = panic_source.snapshot()[0].clone();
    let panic_mutation = panic_source.clone();
    let panic_aggregate =
        AggregateChangeStream::new(panic_source, |item: &TestNode| item.property_changed());
    let panic_calls = Arc::new(Mutex::new(0));
    let panic_capture = Arc::clone(&panic_calls);
    let result = catch_unwind(AssertUnwindSafe(|| {
        let _unreachable = panic_aggregate
            .observe(AggregateObserveOptions::default().emit_initial(true))
            .subscribe(move |_| {
                *locked(&panic_capture) += 1;
                if *locked(&panic_capture) == 1 {
                    panic_mutation.add(TestNode::new(24, "reentrant-after-initial"));
                }
                panic!("initial subscriber");
            });
    }));
    assert!(result.is_err());
    panic_item.emit();
    assert_eq!(*locked(&panic_calls), 1);

    let retried_item = TestNode::new(20, "retry");
    let lifetime = retried_item.weak_lifetime();
    let retry_source = TestSource::new(vec![retried_item.clone()]);
    let selector_source = retry_source.clone();
    let race_once = Arc::new(Mutex::new(true));
    let selector_race = Arc::clone(&race_once);
    let retried = AggregateChangeStream::new(retry_source.clone(), move |item: &TestNode| {
        let mut race = locked(&selector_race);
        if *race {
            *race = false;
            drop(race);
            selector_source.pulse();
        }
        item.property_changed()
    });
    retry_source.replace_all(Vec::new());
    retried.dispose();
    drop(retried);
    drop(retry_source);
    drop(retried_item);
    assert!(lifetime.upgrade().is_none());
}
