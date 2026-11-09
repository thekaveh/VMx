//! A container walk that waited on a child of another dispatcher resumes on
//! its own foreground dispatcher (spec/02 §6, ADR-0218 rule 3, #1326). A walk
//! whose children settle at once finishes on the caller.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;
use vmx::{ComponentVm, CompositeVm, ConstructionStatus, ManualDispatcher, Message, MessageHub};

type Child = ComponentVm<i32, ManualDispatcher>;

fn child(hub: &MessageHub, dispatcher: &ManualDispatcher, name: &str, background: bool) -> Child {
    ComponentVm::builder()
        .name(name)
        .model(1)
        .background(background)
        .services(hub.clone(), dispatcher.clone())
        .build()
        .unwrap()
}

/// Where a callback ran: `true` while the test drains the child's dispatcher.
type Places = Arc<Mutex<Vec<(&'static str, bool)>>>;

fn note(places: &Places, in_child_drain: &AtomicBool, what: &'static str) {
    places
        .lock()
        .unwrap()
        .push((what, in_child_drain.load(Ordering::SeqCst)));
}

/// Drains `dispatcher` with `flag` set, so a callback can tell it ran there.
fn drain_flagged(dispatcher: &ManualDispatcher, flag: &AtomicBool) {
    flag.store(true, Ordering::SeqCst);
    dispatcher.drain();
    flag.store(false, Ordering::SeqCst);
}

/// The walk of composite `c` (dispatcher D1) waits on background child `b`
/// (dispatcher D2). When `b` settles on D2, the rest of the walk, the
/// selector, the `Current` change, the hooks of the sibling `x` and the
/// terminal status of `c` run on D1, not inside D2's drain.
#[test]
fn walk_resumes_on_the_container_foreground() {
    let hub = MessageHub::new();
    let d1 = ManualDispatcher::new();
    let d2 = ManualDispatcher::new();
    let in_d2 = Arc::new(AtomicBool::new(false));
    let places: Places = Arc::default();
    let b = child(&hub, &d2, "b", true);
    let x = child(&hub, &d1, "x", false);
    {
        let (places, in_d2) = (Arc::clone(&places), Arc::clone(&in_d2));
        x.on_construct(move || {
            note(&places, &in_d2, "x.on_construct");
            Ok(())
        });
    }
    {
        let (places, in_d2) = (Arc::clone(&places), Arc::clone(&in_d2));
        x.on_destruct(move || {
            note(&places, &in_d2, "x.on_destruct");
            Ok(())
        });
    }
    let c = CompositeVm::with_services("c", hub.clone(), d1.clone());
    c.add(b.clone()).unwrap();
    c.add(x.clone()).unwrap();
    {
        let (places, in_d2) = (Arc::clone(&places), Arc::clone(&in_d2));
        let wanted = x.id();
        c.set_current_selector(move |members: Vec<Child>| {
            note(&places, &in_d2, "selector");
            members.into_iter().find(|member| member.id() == wanted)
        });
    }
    {
        let (places, in_d2) = (Arc::clone(&places), Arc::clone(&in_d2));
        c.on_current_changed(move |_| note(&places, &in_d2, "on_current_changed"));
    }
    let _terminal = {
        let (places, in_d2) = (Arc::clone(&places), Arc::clone(&in_d2));
        let c_id = c.id();
        hub.subscribe(move |message| {
            if let Message::ConstructionStatusChanged(change) = message {
                if change.sender_id == c_id {
                    match change.status {
                        ConstructionStatus::Constructed => {
                            note(&places, &in_d2, "c Constructed");
                        }
                        ConstructionStatus::Destructed => {
                            note(&places, &in_d2, "c Destructed");
                        }
                        _ => {}
                    }
                }
            }
        })
    };

    c.construct().unwrap();
    assert_eq!(c.status(), ConstructionStatus::Constructing);
    drain_flagged(&d2, &in_d2);
    assert_eq!(b.status(), ConstructionStatus::Constructed);
    assert_eq!(
        x.status(),
        ConstructionStatus::Destructed,
        "the walk does not continue inside the child's dispatcher"
    );
    assert_eq!(c.status(), ConstructionStatus::Constructing);
    d1.drain();
    assert_eq!(x.status(), ConstructionStatus::Constructed);
    assert_eq!(c.status(), ConstructionStatus::Constructed);
    assert_eq!(c.current().map(|current| current.id()), Some(x.id()));
    assert!(x.is_current());

    c.destruct().unwrap();
    assert_eq!(c.status(), ConstructionStatus::Destructing);
    drain_flagged(&d2, &in_d2);
    assert_eq!(b.status(), ConstructionStatus::Destructed);
    assert_eq!(x.status(), ConstructionStatus::Constructed);
    d1.drain();
    assert_eq!(x.status(), ConstructionStatus::Destructed);
    assert_eq!(c.status(), ConstructionStatus::Destructed);

    let places = places.lock().unwrap().clone();
    for what in [
        "x.on_construct",
        "selector",
        "on_current_changed",
        "c Constructed",
        "x.on_destruct",
        "c Destructed",
    ] {
        assert!(
            places.iter().any(|(name, _)| *name == what),
            "{what} ran: {places:?}"
        );
    }
    assert!(
        places.iter().all(|(_, in_child_drain)| !in_child_drain),
        "nothing ran inside the child's dispatcher: {places:?}"
    );
}

/// A walk whose children all settle at once runs to its end on the caller:
/// `construct()` and `destruct()` return with the terminal status published.
#[test]
fn walk_without_a_wait_finishes_on_the_caller() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let first = child(&hub, &dispatcher, "first", false);
    let second = child(&hub, &dispatcher, "second", false);
    let c = CompositeVm::with_services("c", hub.clone(), dispatcher.clone());
    c.add(first.clone()).unwrap();
    c.add(second.clone()).unwrap();

    c.construct().unwrap();
    assert_eq!(c.status(), ConstructionStatus::Constructed);
    assert_eq!(second.status(), ConstructionStatus::Constructed);
    c.destruct().unwrap();
    assert_eq!(c.status(), ConstructionStatus::Destructed);
    assert_eq!(first.status(), ConstructionStatus::Destructed);
    assert_eq!(dispatcher.queued_len(), 0);
}

/// A walk that waited for a late add on another thread resumes on the
/// container's foreground once that add ends, not on the adding thread.
#[test]
fn walk_waiting_on_a_late_add_resumes_on_the_container_foreground() {
    let hub = MessageHub::new();
    let d1 = ManualDispatcher::new();
    let d2 = ManualDispatcher::new();
    let first = child(&hub, &d2, "first", true);
    let late = child(&hub, &d1, "late", false);
    let (entered_tx, entered) = mpsc::channel();
    let (release, release_rx) = mpsc::channel::<()>();
    {
        let release_rx = Mutex::new(release_rx);
        late.on_construct(move || {
            entered_tx.send(()).unwrap();
            let _ = release_rx
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5));
            Ok(())
        });
    }
    let c = CompositeVm::with_services("c", hub.clone(), d1.clone());
    c.set_auto_construct_on_add(true);
    c.add(first.clone()).unwrap();

    c.construct().unwrap();
    let adder = {
        let (c, late) = (c.clone(), late.clone());
        thread::spawn(move || c.add(late))
    };
    entered
        .recv_timeout(Duration::from_secs(5))
        .expect("the add starts the late child");
    d2.drain();
    d1.drain();
    assert_eq!(first.status(), ConstructionStatus::Constructed);
    assert_eq!(c.status(), ConstructionStatus::Constructing);
    release.send(()).unwrap();
    assert_eq!(adder.join().unwrap(), Ok(()));

    assert_eq!(late.status(), ConstructionStatus::Constructed);
    assert_eq!(
        c.status(),
        ConstructionStatus::Constructing,
        "the walk does not continue on the adding thread"
    );
    d1.drain();
    assert_eq!(c.status(), ConstructionStatus::Constructed);
}
