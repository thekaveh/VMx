//! Regression tests: a user value or closure that a VMx owner replaces,
//! discards, or clears is dropped only after the owner's internal locks are
//! released, so a `Drop` that reads its owner returns instead of deadlocking.

use std::cell::Cell;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::RecvTimeoutError;
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;
use vmx::{
    AggregateChangeStream, AggregateObserveOptions, AggregateVm1, AsyncResourceRetention,
    AsyncResourceVm, CancellationToken, ComponentVm, CompositeVm, ConstructionStatus,
    DerivedProperty, FilteredCompositeVm, FormVm, GroupVm, HierarchicalVm,
    KeyedServicedObservableCollection, ManualDispatcher, MessageHub, MissingParentPolicy,
    NullDispatcher, PagedComposition, ValueStream,
};

/// Runs `body` on a worker and fails if it does not finish in time, so a
/// deadlock regression fails the test instead of hanging the suite. A worker
/// panic is reported as a panic, with its message, not as a deadlock.
fn within_timeout<R: Send + 'static>(what: &str, body: impl FnOnce() -> R + Send + 'static) -> R {
    let (tx, rx) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let _ = tx.send(body());
    });
    match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(value) => value,
        Err(RecvTimeoutError::Timeout) => {
            panic!("{what} deadlocked: a user value was dropped under an internal lock")
        }
        Err(RecvTimeoutError::Disconnected) => {
            let message = match worker.join() {
                Ok(()) => "worker exited without a result".to_string(),
                Err(payload) => payload
                    .downcast_ref::<&str>()
                    .map(|text| (*text).to_string())
                    .or_else(|| payload.downcast_ref::<String>().cloned())
                    .unwrap_or_else(|| "non-string panic payload".to_string()),
            };
            panic!("{what} worker panicked: {message}")
        }
    }
}

thread_local! {
    static IN_HOOK: Cell<bool> = const { Cell::new(false) };
}

type HookBody = Arc<dyn Fn() + Send + Sync>;

/// A drop hook shared by every clone of a [`DropProbe`]. It is inert until
/// armed and counts how often it re-entered its owner.
#[derive(Clone, Default)]
struct Hook {
    body: Arc<Mutex<Option<HookBody>>>,
    fired: Arc<AtomicUsize>,
}

impl Hook {
    fn arm(&self, body: impl Fn() + Send + Sync + 'static) {
        *self.body.lock().unwrap() = Some(Arc::new(body));
    }

    fn disarm(&self) -> usize {
        *self.body.lock().unwrap() = None;
        self.fired.load(Ordering::SeqCst)
    }
}

/// A value whose `Drop` runs its armed hook, which reads the owner the value
/// lives in. The hook does not re-enter itself on the same thread.
#[derive(Clone)]
struct DropProbe {
    id: u32,
    hook: Hook,
}

impl DropProbe {
    fn new(id: u32, hook: &Hook) -> Self {
        Self {
            id,
            hook: hook.clone(),
        }
    }
}

impl PartialEq for DropProbe {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl Eq for DropProbe {}

impl std::hash::Hash for DropProbe {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

impl std::fmt::Debug for DropProbe {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "DropProbe({})", self.id)
    }
}

impl Drop for DropProbe {
    fn drop(&mut self) {
        let body = self.hook.body.lock().unwrap().clone();
        let Some(body) = body else {
            return;
        };
        if IN_HOOK.with(|active| active.replace(true)) {
            return;
        }
        self.hook.fired.fetch_add(1, Ordering::SeqCst);
        body();
        IN_HOOK.with(|active| active.set(false));
    }
}

fn component(name: &str, model: DropProbe) -> ComponentVm<DropProbe> {
    ComponentVm::with_model(name, model, MessageHub::new(), NullDispatcher::new())
}

/// Replacing a field validator drops the old one after the lock.
#[test]
fn form_replaced_field_validator_drop_may_read_the_form() {
    let hook = Hook::default();
    let form = FormVm::new("form", 0);
    let probe = DropProbe::new(1, &hook);
    form.with_field_validator("a", move |_| {
        let _ = &probe;
        None
    });
    let reader = form.clone();
    hook.arm(move || reader.with_field_validator("other", |_| None));
    within_timeout("FormVm::with_field_validator", {
        let form = form.clone();
        move || form.with_field_validator("a", |_| None)
    });
    assert!(hook.disarm() > 0);
    assert!(form.is_valid());
}

/// Disposing a form drops its validators after the lock.
#[test]
fn form_dispose_validator_drop_may_read_the_form() {
    let hook = Hook::default();
    let form = FormVm::new("form", 0);
    let probe = DropProbe::new(1, &hook);
    form.with_field_validator("a", move |_| {
        let _ = &probe;
        None
    });
    let reader = form.clone();
    hook.arm(move || {
        reader.set_model(7);
        reader.revert();
        let _ = reader.can_approve();
    });
    within_timeout("FormVm::dispose", {
        let form = form.clone();
        move || form.dispose()
    });
    assert!(hook.disarm() > 0);
}

/// Invalidated children drop after the topology gate is released.
#[test]
fn hierarchical_invalidate_children_drop_may_read_the_node() {
    let hook = Hook::default();
    // Setup runs under the timeout too: materializing takes the process-wide
    // hierarchy topology gate, which a deadlocked sibling test could hold.
    let materialized = within_timeout("HierarchicalVm::invalidate_children", {
        let hook = hook.clone();
        move || {
            let factory_hook = hook.clone();
            let root = HierarchicalVm::with_children_factory(
                "root",
                DropProbe::new(0, &Hook::default()),
                move |_| {
                    vec![HierarchicalVm::new(
                        "child",
                        DropProbe::new(1, &factory_hook),
                    )]
                },
                false,
                MessageHub::new(),
            );
            assert_eq!(root.children().len(), 1);
            let reader = root.clone();
            hook.arm(move || {
                let _ = reader.is_children_materialized();
            });
            root.invalidate_children();
            root.is_children_materialized()
        }
    });
    assert!(hook.disarm() > 0);
    assert!(!materialized);
}

/// Parked batch items drop after the parked-state lock.
#[test]
fn hierarchical_dispose_parked_drop_may_read_the_node() {
    let hook = Hook::default();
    // Setup runs under the timeout too: attaching takes the process-wide
    // hierarchy topology gate, which a deadlocked sibling test could hold.
    let parked = within_timeout("HierarchicalVm::dispose", {
        let hook = hook.clone();
        move || {
            let root = HierarchicalVm::new("root", DropProbe::new(0, &Hook::default()));
            let orphan = HierarchicalVm::new("orphan", DropProbe::new(1, &hook));
            let result = root.attach_many(
                vec![orphan],
                |node| Ok(node.name()),
                |_| Ok(Some("missing".to_string())),
                MissingParentPolicy::Park,
            );
            drop(result);
            assert_eq!(root.parked_attach_count(), 1);
            let reader = root.clone();
            hook.arm(move || {
                let _ = reader.parked_attach_count();
            });
            let _ = root.dispose();
            root.parked_attach_count()
        }
    });
    assert!(hook.disarm() > 0);
    assert_eq!(parked, 0);
}

/// A replaced filter predicate drops after the predicate lock.
#[test]
fn filtered_set_predicate_drop_may_read_the_projection() {
    let hook = Hook::default();
    let source: CompositeVm<ComponentVm<()>> = CompositeVm::new("source");
    let probe = DropProbe::new(1, &hook);
    let filtered = FilteredCompositeVm::new(source, move |_| {
        let _ = &probe;
        true
    });
    let reader = filtered.clone();
    hook.arm(move || {
        let _ = reader.visible();
    });
    within_timeout("FilteredCompositeVm::set_predicate", {
        let filtered = filtered.clone();
        move || filtered.set_predicate(|_| false)
    });
    assert!(hook.disarm() > 0);
}

/// A filtered current item that the source removed drops after the current
/// lock when a read reconciles the selection, so its `Drop` may read the
/// projection.
#[test]
fn filtered_current_item_drop_may_read_the_projection() {
    let hook = Hook::default();
    let source: CompositeVm<ComponentVm<DropProbe>> = CompositeVm::new("source");
    source
        .add(component("first", DropProbe::new(1, &hook)))
        .unwrap();
    source
        .add(component("second", DropProbe::new(2, &Hook::default())))
        .unwrap();
    let filtered = FilteredCompositeVm::new(source.clone(), |_| true);
    let first = filtered.current().unwrap();
    assert_eq!(first.name(), "first");
    source.remove(&first).unwrap();
    // The projection's current slot now owns the removed item's last handle.
    drop(first);

    let reader = filtered.clone();
    hook.arm(move || {
        let _ = reader.current();
        let _ = reader.visible();
    });
    let current = within_timeout("FilteredCompositeVm::current", {
        let filtered = filtered.clone();
        move || filtered.current().map(|item| item.name())
    });
    assert!(hook.disarm() > 0);
    assert_eq!(current.as_deref(), Some("second"));
}

/// Keyed `replace`, `remove_at` and `remove_key` drop the captured key of the
/// membership they release after the collection lock, so the key's `Drop`
/// may read the collection.
#[test]
fn keyed_collection_replace_remove_at_and_remove_key_drop_may_read_the_collection() {
    let hook = Hook::default();
    // Only the captured keys carry the armed hook, so every count below comes
    // from a key the collection itself drops.
    let key_hook = hook.clone();
    let collection = KeyedServicedObservableCollection::new(1, move |item: &DropProbe| {
        Ok(DropProbe::new(item.id, &key_hook))
    });
    for id in 1..=4 {
        collection
            .push(DropProbe::new(id, &Hook::default()))
            .unwrap();
    }
    let reader = collection.clone();
    hook.arm(move || {
        let _ = reader.len();
        let _ = reader.to_vec();
    });
    let fired = |hook: &Hook| hook.fired.load(Ordering::SeqCst);

    let before = fired(&hook);
    let replaced = within_timeout("KeyedServicedObservableCollection::replace", {
        let collection = collection.clone();
        move || {
            let old = collection
                .replace(0, DropProbe::new(10, &Hook::default()))
                .unwrap();
            (old.id, collection.len())
        }
    });
    assert_eq!(replaced, (1, 4));
    assert!(fired(&hook) > before, "replace dropped no captured key");

    let before = fired(&hook);
    let removed = within_timeout("KeyedServicedObservableCollection::remove_at", {
        let collection = collection.clone();
        move || {
            let old = collection.remove_at(0).unwrap();
            (old.id, collection.len())
        }
    });
    assert_eq!(removed, (10, 3));
    assert!(fired(&hook) > before, "remove_at dropped no captured key");

    let before = fired(&hook);
    let removed = within_timeout("KeyedServicedObservableCollection::remove_key", {
        let collection = collection.clone();
        move || {
            let old = collection
                .remove_key(&DropProbe::new(3, &Hook::default()))
                .unwrap();
            (old.id, collection.len())
        }
    });
    assert_eq!(removed, (3, 2));
    assert!(fired(&hook) > before, "remove_key dropped no captured key");
    hook.disarm();
}

/// A replaced current selector drops after the selector lock.
#[test]
fn composite_set_current_selector_drop_may_read_the_composite() {
    let hook = Hook::default();
    let composite: CompositeVm<ComponentVm<()>> = CompositeVm::new("composite");
    let probe = DropProbe::new(1, &hook);
    composite.set_current_selector(move |_| {
        let _ = &probe;
        None
    });
    let reader = composite.clone();
    hook.arm(move || reader.set_current_selector(|_| None));
    within_timeout("CompositeVm::set_current_selector", {
        let composite = composite.clone();
        move || composite.set_current_selector(|_| None)
    });
    assert!(hook.disarm() > 0);
}

/// A replaced current-changed callback drops after its lock.
#[test]
fn composite_on_current_changed_drop_may_read_the_composite() {
    let hook = Hook::default();
    let composite: CompositeVm<ComponentVm<()>> = CompositeVm::new("composite");
    let probe = DropProbe::new(1, &hook);
    composite.on_current_changed(move |_| {
        let _ = &probe;
    });
    let reader = composite.clone();
    hook.arm(move || reader.on_current_changed(|_| {}));
    within_timeout("CompositeVm::on_current_changed", {
        let composite = composite.clone();
        move || composite.on_current_changed(|_| {})
    });
    assert!(hook.disarm() > 0);
}

/// Cleared children drop after the membership gate is released.
#[test]
fn composite_clear_drop_may_dispose_the_composite() {
    let hook = Hook::default();
    let composite: CompositeVm<ComponentVm<DropProbe>> = CompositeVm::new("composite");
    composite
        .add(component("child", DropProbe::new(1, &hook)))
        .unwrap();
    let reader = composite.clone();
    hook.arm(move || {
        let _ = reader.dispose();
    });
    let len = within_timeout("CompositeVm::clear", {
        let composite = composite.clone();
        move || {
            composite.clear();
            composite.items().len()
        }
    });
    assert!(hook.disarm() > 0);
    assert_eq!(len, 0);
}

/// Cleared group children drop after the membership gate.
#[test]
fn group_clear_drop_may_dispose_the_group() {
    let hook = Hook::default();
    let group: GroupVm<ComponentVm<DropProbe>> = GroupVm::new("group");
    group
        .add(component("child", DropProbe::new(1, &hook)))
        .unwrap();
    let reader = group.clone();
    hook.arm(move || {
        let _ = reader.dispose();
    });
    let len = within_timeout("GroupVm::clear", {
        let group = group.clone();
        move || {
            group.clear();
            group.items().len()
        }
    });
    assert!(hook.disarm() > 0);
    assert_eq!(len, 0);
}

/// A membership entry removed by resynchronization drops after the
/// stream lock is released.
#[test]
fn aggregate_stream_removed_entry_drop_may_observe_the_stream() {
    let hook = Hook::default();
    let composite: CompositeVm<ComponentVm<DropProbe>> = CompositeVm::new("composite");
    let stream = Arc::new(AggregateChangeStream::for_components(composite.clone()));
    composite
        .add(component("child", DropProbe::new(1, &hook)))
        .unwrap();
    let reader = Arc::clone(&stream);
    hook.arm(move || {
        let subscription = reader
            .observe(AggregateObserveOptions::default())
            .subscribe(|_| {});
        drop(subscription);
    });
    within_timeout("AggregateChangeStream membership removal", {
        let composite = composite.clone();
        move || composite.clear()
    });
    assert!(hook.disarm() > 0);
}

/// A replaced paging source drops after the source lock.
#[test]
fn paged_set_source_drop_may_read_the_composition() {
    let hook = Hook::default();
    let paged = PagedComposition::new(vec![DropProbe::new(1, &hook)], 2);
    let reader = paged.clone();
    hook.arm(move || {
        let _ = reader.page_count();
    });
    let pages = within_timeout("PagedComposition::set_source", {
        let paged = paged.clone();
        move || {
            paged.set_source(Vec::new());
            paged.page_count()
        }
    });
    assert!(hook.disarm() > 0);
    assert!(pages <= 1);
}

/// The replaced current value of a value stream (the reactive
/// facade behind `ValueChanged`) drops after the stream lock.
#[test]
fn value_stream_send_drop_may_read_the_stream() {
    let hook = Hook::default();
    let stream = ValueStream::new(DropProbe::new(1, &hook));
    let reader = stream.clone();
    hook.arm(move || {
        let _ = reader.value();
    });
    let id = within_timeout("ValueStream::send", {
        let stream = stream.clone();
        move || {
            stream.send(DropProbe::new(2, &Hook::default()));
            stream.value().id
        }
    });
    assert!(hook.disarm() > 0);
    assert_eq!(id, 2);
}

/// A recomputed derived value drops the old value after the
/// value lock.
#[test]
fn derived_recompute_drop_may_read_the_property() {
    let hook = Hook::default();
    let property = DerivedProperty::new(DropProbe::new(1, &hook));
    let reader = property.clone();
    hook.arm(move || {
        let _ = reader.value();
    });
    let id = within_timeout("DerivedProperty::recompute", {
        let property = property.clone();
        move || {
            property.recompute(|_| DropProbe::new(2, &Hook::default()));
            property.value().id
        }
    });
    assert!(hook.disarm() > 0);
    assert_eq!(id, 2);
}

fn probing_resource(hook: &Hook, retention: AsyncResourceRetention) -> AsyncResourceVm<DropProbe> {
    let loads = Arc::new(Mutex::new(0u32));
    let hook = hook.clone();
    let loader = move |_: CancellationToken| {
        let mut count = loads.lock().unwrap();
        *count += 1;
        Ok(DropProbe::new(*count, &hook))
    };
    AsyncResourceVm::with_options("resource", loader, retention, None)
}

/// A discard reload drops the replaced ready state after the machine lock.
#[test]
fn async_resource_reload_drop_may_read_the_resource() {
    let hook = Hook::default();
    let resource = probing_resource(&hook, AsyncResourceRetention::DiscardPrevious);
    resource.load_async().join().unwrap().unwrap();
    let reader = resource.clone();
    hook.arm(move || {
        let _ = reader.state();
    });
    within_timeout("AsyncResourceVm::reload_async", {
        let resource = resource.clone();
        move || resource.reload_async().join().unwrap().unwrap()
    });
    assert!(hook.disarm() > 0);
}

/// A retained reload drops replaced state clones after the
/// machine lock.
#[test]
fn async_resource_retained_reload_drop_may_read_the_resource() {
    let hook = Hook::default();
    let resource = probing_resource(&hook, AsyncResourceRetention::RetainPrevious);
    resource.load_async().join().unwrap().unwrap();
    let reader = resource.clone();
    hook.arm(move || {
        let _ = reader.state();
    });
    within_timeout("AsyncResourceVm::reload_async retained", {
        let resource = resource.clone();
        move || resource.reload_async().join().unwrap().unwrap()
    });
    assert!(hook.disarm() > 0);
}

/// A child removed while its construct step is queued, whose last handle the
/// queue owns, drops after the core lock when the waiting composite is disposed.
#[test]
fn dispose_while_waiting_drops_a_queued_removed_child_after_the_core_lock() {
    let hook = Hook::default();
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = |name: &str, id: u32, background: bool| {
        ComponentVm::builder()
            .name(name)
            .model(DropProbe::new(id, &hook))
            .background(background)
            .services(hub.clone(), dispatcher.clone())
            .build()
            .unwrap()
    };
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.add(child("anchor", 1, true)).unwrap();
    let queued = child("queued", 2, false);
    composite.add(queued.clone()).unwrap();
    composite.construct().unwrap();
    assert_eq!(composite.status(), vmx::ConstructionStatus::Constructing);
    composite.remove(&queued).unwrap();
    drop(queued);

    let reader = composite.clone();
    hook.arm(move || {
        let _ = reader.status();
    });
    within_timeout("CompositeVm::dispose while waiting", {
        let composite = composite.clone();
        move || composite.dispose()
    })
    .unwrap();
    assert!(hook.disarm() > 0);
}

/// A group child removed while its construct step is queued, whose last
/// handle the queue owns, drops after the core lock when the waiting group is
/// disposed.
#[test]
fn group_dispose_while_waiting_drops_a_queued_removed_child_after_the_core_lock() {
    let hook = Hook::default();
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = |name: &str, id: u32, background: bool| {
        ComponentVm::builder()
            .name(name)
            .model(DropProbe::new(id, &hook))
            .background(background)
            .services(hub.clone(), dispatcher.clone())
            .build()
            .unwrap()
    };
    let group = GroupVm::with_services("group", hub.clone(), dispatcher.clone());
    group.add(child("anchor", 1, true)).unwrap();
    let queued = child("queued", 2, false);
    group.add(queued.clone()).unwrap();
    group.construct().unwrap();
    assert_eq!(group.status(), ConstructionStatus::Constructing);
    group.remove(&queued).unwrap();
    drop(queued);

    let reader = group.clone();
    hook.arm(move || {
        let _ = reader.status();
    });
    within_timeout("GroupVm::dispose while waiting", {
        let group = group.clone();
        move || group.dispose()
    })
    .unwrap();
    assert!(hook.disarm() > 0);
    assert_eq!(group.status(), ConstructionStatus::Disposed);
}

/// An `AggregateVm1` disposed while it waits on its component releases a
/// value after every core lock: the component is a composite waiting on a
/// background child, and its queued step owns the last handle to a removed
/// child whose `Drop` reads the aggregate and the composite. The aggregate's
/// own settle queue holds no step while it waits on its only component, so
/// the released value comes from the component's queue.
#[test]
fn aggregate_dispose_while_waiting_drops_a_released_child_after_the_core_lock() {
    let hook = Hook::default();
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let child = |name: &str, id: u32, background: bool| {
        ComponentVm::builder()
            .name(name)
            .model(DropProbe::new(id, &hook))
            .background(background)
            .services(hub.clone(), dispatcher.clone())
            .build()
            .unwrap()
    };
    let composite = CompositeVm::with_services("composite", hub.clone(), dispatcher.clone());
    composite.add(child("anchor", 1, true)).unwrap();
    let queued = child("queued", 2, false);
    composite.add(queued.clone()).unwrap();
    let aggregate =
        AggregateVm1::with_services("aggregate", hub.clone(), dispatcher.clone(), composite);
    aggregate.construct().unwrap();
    assert_eq!(aggregate.status(), ConstructionStatus::Constructing);
    let composite = aggregate.component_1().unwrap();
    assert_eq!(composite.status(), ConstructionStatus::Constructing);
    composite.remove(&queued).unwrap();
    drop(queued);

    let reader = aggregate.clone();
    let component = composite.clone();
    hook.arm(move || {
        let _ = reader.status();
        let _ = component.status();
    });
    drop(composite);
    within_timeout("AggregateVm1::dispose while waiting", {
        let aggregate = aggregate.clone();
        move || aggregate.dispose()
    })
    .unwrap();
    assert!(hook.disarm() > 0);
    assert_eq!(aggregate.status(), ConstructionStatus::Disposed);
}

/// A constructed composite whose only child is current.
fn composite_with_current_child(
    hub: &MessageHub,
) -> (CompositeVm<ComponentVm<u32>>, ComponentVm<u32>) {
    let composite = CompositeVm::with_services("composite", hub.clone(), NullDispatcher::new());
    let child = ComponentVm::with_model("child", 1u32, hub.clone(), NullDispatcher::new());
    composite.add(child.clone()).unwrap();
    composite.construct().unwrap();
    composite.select_component(&child).unwrap();
    assert!(child.is_current());
    (composite, child)
}

/// #749 — `clear()` publishes the current child's `is_current` change after
/// it releases the membership gate, so a hub subscriber that disposes the
/// composite does not deadlock it.
#[test]
fn composite_clear_survives_an_is_current_hub_subscriber_that_disposes_it() {
    let hub = MessageHub::new();
    let (composite, child) = composite_with_current_child(&hub);
    let is_current_messages = Arc::new(AtomicUsize::new(0));
    let _subscription = hub.subscribe({
        let composite = composite.clone();
        let child_id = child.id();
        let is_current_messages = Arc::clone(&is_current_messages);
        move |message| {
            if let vmx::Message::PropertyChanged(change) = message {
                if change.sender_id == child_id && change.property_name == "is_current" {
                    is_current_messages.fetch_add(1, Ordering::SeqCst);
                    let _ = composite.dispose();
                }
            }
        }
    });

    within_timeout("CompositeVm::clear", {
        let composite = composite.clone();
        move || composite.clear()
    });

    assert_eq!(composite.status(), ConstructionStatus::Disposed);
    assert!(!child.is_current());
    assert_eq!(is_current_messages.load(Ordering::SeqCst), 1);
}

/// #749 — the same from a `property_changed()` subscriber on the child.
#[test]
fn composite_clear_survives_an_is_current_child_subscriber_that_disposes_it() {
    let hub = MessageHub::new();
    let (composite, child) = composite_with_current_child(&hub);
    let is_current_messages = Arc::new(AtomicUsize::new(0));
    let _subscription = child.property_changed().subscribe({
        let composite = composite.clone();
        let is_current_messages = Arc::clone(&is_current_messages);
        move |name| {
            if name == "is_current" {
                is_current_messages.fetch_add(1, Ordering::SeqCst);
                let _ = composite.dispose();
            }
        }
    });

    within_timeout("CompositeVm::clear", {
        let composite = composite.clone();
        move || composite.clear()
    });

    assert_eq!(composite.status(), ConstructionStatus::Disposed);
    assert!(!child.is_current());
    assert_eq!(is_current_messages.load(Ordering::SeqCst), 1);
}

/// #1066 — an `add` or `insert` whose admission fails destructs the child after
/// it releases the membership gate. A hub subscriber disposes the container on
/// every message from the child: the first disposal, inside the transaction,
/// defers and fails the admission. The next one, from the rollback's destruct
/// messages, must not deadlock on the gate. Returns the call's result and the
/// child.
fn rollback_with_a_disposing_subscriber<C: Clone + Send + Sync + 'static>(
    what: &'static str,
    hub: &MessageHub,
    container: &C,
    dispose: fn(&C) -> vmx::VmxResult<()>,
    attach: fn(&C, ComponentVm<u32>) -> vmx::VmxResult<()>,
) -> (vmx::VmxResult<()>, ComponentVm<u32>) {
    let child = ComponentVm::with_model("child", 1u32, hub.clone(), NullDispatcher::new());
    let _subscription = hub.subscribe({
        let container = container.clone();
        let child_id = child.id();
        move |message| {
            if message.sender_id() == child_id {
                let _ = dispose(&container);
            }
        }
    });
    let result = within_timeout(what, {
        let (container, child) = (container.clone(), child.clone());
        move || attach(&container, child)
    });
    (result, child)
}

fn constructed_composite(hub: &MessageHub) -> CompositeVm<ComponentVm<u32>> {
    let composite = CompositeVm::with_services("composite", hub.clone(), NullDispatcher::new());
    composite.set_auto_construct_on_add(true);
    composite.construct().unwrap();
    composite
}

fn constructed_group(hub: &MessageHub) -> GroupVm<ComponentVm<u32>> {
    let group = GroupVm::with_services("group", hub.clone(), NullDispatcher::new());
    group.set_auto_construct_on_add(true);
    group.construct().unwrap();
    group
}

#[test]
fn composite_add_rollback_survives_a_subscriber_that_disposes_it() {
    let hub = MessageHub::new();
    let composite = constructed_composite(&hub);
    let (result, child) = rollback_with_a_disposing_subscriber(
        "CompositeVm::add",
        &hub,
        &composite,
        CompositeVm::dispose,
        |composite, child| composite.add(child),
    );

    assert_eq!(result, Err(vmx::VmxError::Disposed));
    assert_eq!(composite.status(), ConstructionStatus::Disposed);
    assert!(composite.items().iter().all(|item| item.id() != child.id()));
    assert_eq!(child.parent_id(), None);
}

#[test]
fn composite_insert_rollback_survives_a_subscriber_that_disposes_it() {
    let hub = MessageHub::new();
    let composite = constructed_composite(&hub);
    let (result, child) = rollback_with_a_disposing_subscriber(
        "CompositeVm::insert",
        &hub,
        &composite,
        CompositeVm::dispose,
        |composite, child| composite.insert(0, child),
    );

    assert_eq!(result, Err(vmx::VmxError::Disposed));
    assert_eq!(composite.status(), ConstructionStatus::Disposed);
    assert!(composite.items().iter().all(|item| item.id() != child.id()));
    assert_eq!(child.parent_id(), None);
}

#[test]
fn group_add_rollback_survives_a_subscriber_that_disposes_it() {
    let hub = MessageHub::new();
    let group = constructed_group(&hub);
    let (result, child) = rollback_with_a_disposing_subscriber(
        "GroupVm::add",
        &hub,
        &group,
        GroupVm::dispose,
        |group, child| group.add(child),
    );

    assert_eq!(result, Err(vmx::VmxError::Disposed));
    assert_eq!(group.status(), ConstructionStatus::Disposed);
    assert!(group.items().iter().all(|item| item.id() != child.id()));
    assert_eq!(child.parent_id(), None);
}

#[test]
fn group_insert_rollback_survives_a_subscriber_that_disposes_it() {
    let hub = MessageHub::new();
    let group = constructed_group(&hub);
    let (result, child) = rollback_with_a_disposing_subscriber(
        "GroupVm::insert",
        &hub,
        &group,
        GroupVm::dispose,
        |group, child| group.insert(0, child),
    );

    assert_eq!(result, Err(vmx::VmxError::Disposed));
    assert_eq!(group.status(), ConstructionStatus::Disposed);
    assert!(group.items().iter().all(|item| item.id() != child.id()));
    assert_eq!(child.parent_id(), None);
}
