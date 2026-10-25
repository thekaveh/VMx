//! Regression tests: a user value or closure that a VMx owner replaces,
//! discards, or clears is dropped only after the owner's internal locks are
//! released, so a `Drop` that reads its owner returns instead of deadlocking.

use std::cell::Cell;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::RecvTimeoutError;
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;
use vmx::{
    AggregateChangeStream, AggregateObserveOptions, AsyncResourceRetention, AsyncResourceVm,
    CancellationToken, ComponentVm, CompositeVm, DerivedProperty, FilteredCompositeVm, FormVm,
    GroupVm, HierarchicalVm, ManualDispatcher, MessageHub, MissingParentPolicy, NullDispatcher,
    PagedComposition, ValueStream,
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
