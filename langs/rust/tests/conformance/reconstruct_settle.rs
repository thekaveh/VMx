//! Settle waiters and the deferred construct of a reconstruct (spec/02 §6).
//!
//! `ComponentCore::reconstruct` releases settle waiters through a drop guard,
//! so a hook panic during `reconstruct()` still runs them (#738, #1284). The
//! blanket `Reconstructable::reconstruct` constructs again from a settle
//! callback only when the node is still `Destructed` (#748, #1284).

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use vmx::{
    ComponentVm, ConstructionStatus, ManualDispatcher, Message, MessageHub, NullDispatcher,
    Reconstructable, VmNode, VmxResult,
};

type Leaf = ComponentVm<i32>;
type Background = ComponentVm<i32, ManualDispatcher>;
type Log = Arc<Mutex<Vec<&'static str>>>;

/// Which hook of a synchronous reconstruct panics.
#[derive(Clone, Copy)]
enum PanickingHook {
    Destruct,
    Construct,
}

/// Reconstructs a constructed synchronous component whose `hook` registers a
/// settle callback through [`VmNode::when_lifecycle_settled`] and then
/// panics. Returns whether the panic reached the caller, the number of
/// callback runs and the final status.
fn reconstruct_with_panicking_hook(hook: PanickingHook) -> (bool, usize, ConstructionStatus) {
    let leaf = Leaf::with_model("leaf", 1, MessageHub::new(), NullDispatcher::new());
    leaf.construct().unwrap();

    // The hook reaches the component through this slot. The test empties
    // the slot at the end, so the hook does not keep the component alive.
    let slot: Arc<Mutex<Option<Leaf>>> = Arc::new(Mutex::new(Some(leaf.clone())));
    let settled = Arc::new(AtomicUsize::new(0));
    let panicking = {
        let (slot, settled) = (Arc::clone(&slot), Arc::clone(&settled));
        move || -> VmxResult<()> {
            let node = slot.lock().unwrap().clone().expect("the component is set");
            let counter = Arc::clone(&settled);
            let registered = VmNode::when_lifecycle_settled(
                &node,
                Box::new(move || {
                    counter.fetch_add(1, Ordering::SeqCst);
                }),
            );
            assert!(registered, "the reconstruct is in flight");
            panic!("reconstruct hook panicked")
        }
    };
    match hook {
        PanickingHook::Destruct => leaf.on_destruct(panicking),
        PanickingHook::Construct => leaf.on_construct(panicking),
    }

    let panicked = catch_unwind(AssertUnwindSafe(|| leaf.reconstruct())).is_err();
    let outcome = (panicked, settled.load(Ordering::SeqCst), leaf.status());
    slot.lock().unwrap().take();
    outcome
}

/// #1284 — a panicking `on_destruct` hook during `reconstruct()` still
/// releases the settle waiters: the callback runs once and the component
/// rolls back to `Constructed`.
#[test]
fn panicking_destruct_hook_during_reconstruct_releases_settle_waiters() {
    let (panicked, callbacks, status) = reconstruct_with_panicking_hook(PanickingHook::Destruct);

    assert!(panicked, "the hook panic reaches the caller");
    assert_eq!(callbacks, 1, "the settle callback runs once");
    assert_eq!(status, ConstructionStatus::Constructed);
}

/// #1284 — a panicking `on_construct` hook during `reconstruct()` still
/// releases the settle waiters: the callback runs once and the component
/// ends `Destructed`.
#[test]
fn panicking_construct_hook_during_reconstruct_releases_settle_waiters() {
    let (panicked, callbacks, status) = reconstruct_with_panicking_hook(PanickingHook::Construct);

    assert!(panicked, "the hook panic reaches the caller");
    assert_eq!(callbacks, 1, "the settle callback runs once");
    assert_eq!(status, ConstructionStatus::Destructed);
}

/// A constructed background component that logs each construct and
/// destruct hook run.
fn constructed_background(hub: &MessageHub, dispatcher: &ManualDispatcher) -> (Background, Log) {
    let log: Log = Arc::default();
    let (constructs, destructs) = (Arc::clone(&log), Arc::clone(&log));
    let vm = ComponentVm::builder()
        .name("background")
        .model(1)
        .background(true)
        .on_construct(move || {
            constructs.lock().unwrap().push("construct");
            Ok(())
        })
        .on_destruct(move || {
            destructs.lock().unwrap().push("destruct");
            Ok(())
        })
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap();
    vm.construct().unwrap();
    dispatcher.drain();
    assert_eq!(vm.status(), ConstructionStatus::Constructed);
    assert_eq!(*log.lock().unwrap(), ["construct"]);
    (vm, log)
}

/// #1284 — a node disposed while the trait reconstruct waits for its
/// background destruct is not constructed again.
#[test]
fn reconstructable_trait_skips_the_construct_after_a_disposal() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let (vm, log) = constructed_background(&hub, &dispatcher);

    Reconstructable::reconstruct(&vm);
    assert_eq!(vm.status(), ConstructionStatus::Destructing);
    vm.dispose().unwrap();
    dispatcher.drain();

    assert_eq!(vm.status(), ConstructionStatus::Disposed);
    assert_eq!(
        log.lock()
            .unwrap()
            .iter()
            .filter(|run| **run == "construct")
            .count(),
        1,
        "the construct hook did not run again: {:?}",
        log.lock().unwrap()
    );
}

/// #1284 — when a hub subscriber constructs the node on its `Destructed`
/// publication, the trait reconstruct does not construct it a second time.
#[test]
fn reconstructable_trait_skips_the_construct_after_a_subscriber_constructs() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let (vm, log) = constructed_background(&hub, &dispatcher);
    let subscription = {
        let (node, id) = (vm.clone(), vm.id());
        hub.subscribe(move |message| {
            if let Message::ConstructionStatusChanged(change) = message {
                if change.sender_id == id && change.status == ConstructionStatus::Destructed {
                    node.construct().unwrap();
                }
            }
        })
    };

    Reconstructable::reconstruct(&vm);
    assert_eq!(vm.status(), ConstructionStatus::Destructing);
    dispatcher.drain();

    assert_eq!(vm.status(), ConstructionStatus::Constructed);
    assert_eq!(
        *log.lock().unwrap(),
        ["construct", "destruct", "construct"],
        "the construct hook ran once after the destruct"
    );
    drop(subscription);
}
