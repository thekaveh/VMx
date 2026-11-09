//! Composite selection rules for disposed children, for a composite that is
//! `Destructing`, and for refused child `select()` and `deselect()` calls
//! (spec/06 §3, §3.1, §4.3 rules 2, 8 and 9, §5; ADR-0188, ADR-0189).

use std::sync::{Arc, Mutex};
use std::thread;

use vmx::{
    ComponentVm, CompositeVm, ConstructionStatus, ForwardingComponentVm, ManualDispatcher, Message,
    MessageHub, NullDispatcher, Subscription, VmNode, VmxError,
};

type Child = ComponentVm<&'static str>;
type Parent = CompositeVm<Child>;
type Log<T> = Arc<Mutex<Vec<T>>>;

fn child(hub: &MessageHub, name: &'static str) -> Child {
    Child::with_model(name, name, hub.clone(), NullDispatcher::new())
}

fn parent(hub: &MessageHub, children: &[&Child]) -> Parent {
    let parent = Parent::with_services("p", hub.clone(), NullDispatcher::new());
    for child in children {
        parent.add((*child).clone()).unwrap();
    }
    parent
}

/// Records each hub message as `(sender, "status:<status>")` or
/// `(sender, "<property>")`.
fn record(hub: &MessageHub) -> (Log<(usize, String)>, Subscription) {
    let log: Log<(usize, String)> = Arc::default();
    let sink = Arc::clone(&log);
    let subscription = hub.subscribe(move |message| {
        let entry = match message {
            Message::PropertyChanged(change) => (change.sender_id, change.property_name.clone()),
            Message::ConstructionStatusChanged(change) => {
                (change.sender_id, format!("status:{:?}", change.status))
            }
            _ => return,
        };
        sink.lock().unwrap().push(entry);
    });
    (log, subscription)
}

fn count(log: &Log<(usize, String)>, sender: usize, property: &str) -> usize {
    log.lock()
        .unwrap()
        .iter()
        .filter(|(id, name)| *id == sender && name == property)
        .count()
}

fn record_callbacks<T: VmNode>(composite: &CompositeVm<T>) -> Log<Option<usize>> {
    let log: Log<Option<usize>> = Arc::default();
    let sink = Arc::clone(&log);
    composite.on_current_changed(move |value: Option<T>| {
        sink.lock().unwrap().push(value.map(|value| value.id()));
    });
    log
}

/// COMP-050 — disposing the current child clears `current` once before
/// `dispose()` returns. The child reads `is_current` false and publishes no
/// `is_current` change after `Disposed`. The disposed child is not
/// selectable. The composite's own dispose cascade does not clear `current`.
#[test]
fn disposing_the_current_child_clears_current() {
    let hub = MessageHub::new();
    let a = child(&hub, "a");
    let b = child(&hub, "b");
    let p = parent(&hub, &[&a, &b]);
    p.construct().unwrap();
    p.set_current(Some(a.clone())).unwrap();
    let callbacks = record_callbacks(&p);
    let (log, _subscription) = record(&hub);

    a.dispose().unwrap();

    assert_eq!(p.current(), None);
    assert!(!a.is_current());
    assert_eq!(count(&log, p.id(), "current"), 1);
    assert_eq!(*callbacks.lock().unwrap(), vec![None]);
    let entries = log.lock().unwrap().clone();
    let disposed = entries
        .iter()
        .position(|entry| *entry == (a.id(), "status:Disposed".to_string()))
        .expect("a publishes Disposed");
    assert!(!entries[disposed..]
        .iter()
        .any(|entry| *entry == (a.id(), "is_current".to_string())));
    assert!(!p.can_select_component(&a));
    assert_eq!(p.set_current(Some(a.clone())), Err(VmxError::NonChild));
    assert_eq!(p.current(), None);

    p.set_current(Some(b.clone())).unwrap();
    log.lock().unwrap().clear();
    p.dispose().unwrap();

    assert_eq!(b.status(), ConstructionStatus::Disposed);
    assert_eq!(count(&log, p.id(), "current"), 0);
}

/// COMP-051 — a non-null selection while the composite is `Destructing`
/// changes nothing and raises nothing, on the setter, `select_component` and
/// the child `select` path, also in the destruct phase of `reconstruct()`.
#[test]
fn selection_while_destructing_changes_nothing() {
    let hub = MessageHub::new();
    let a = child(&hub, "a");
    let b = child(&hub, "b");
    let c = child(&hub, "c");
    let p = parent(&hub, &[&a, &b, &c]);
    let errors: Log<VmxError> = Arc::default();
    let can_select: Log<bool> = Arc::default();
    let callbacks: Log<Option<usize>> = Arc::default();
    {
        let p2 = p.clone();
        let b2 = b.clone();
        let errors = Arc::clone(&errors);
        let callbacks = Arc::clone(&callbacks);
        p.on_current_changed(move |value: Option<Child>| {
            callbacks
                .lock()
                .unwrap()
                .push(value.as_ref().map(Child::id));
            if value.is_none() && p2.status() == ConstructionStatus::Destructing {
                let set = p2.set_current(Some(b2.clone()));
                let select = p2.select_component(&b2);
                b2.select();
                let mut errors = errors.lock().unwrap();
                errors.extend(set.err());
                errors.extend(select.err());
            }
        });
    }
    {
        let p2 = p.clone();
        let a2 = a.clone();
        let c2 = c.clone();
        let errors = Arc::clone(&errors);
        let can_select = Arc::clone(&can_select);
        b.on_destruct(move || {
            let mut results = vec![p2.set_current(Some(c2.clone()))];
            c2.select();
            can_select
                .lock()
                .unwrap()
                .push(p2.can_select_component(&c2));
            results.push(p2.set_current(Some(a2.clone())));
            results.push(p2.set_current(None));
            errors
                .lock()
                .unwrap()
                .extend(results.into_iter().filter_map(Result::err));
            Ok(())
        });
    }
    p.construct().unwrap();
    p.set_current(Some(a.clone())).unwrap();
    callbacks.lock().unwrap().clear();
    let (log, _subscription) = record(&hub);

    assert_eq!(p.destruct(), Ok(()));

    assert!(errors.lock().unwrap().is_empty());
    for status in [p.status(), a.status(), b.status(), c.status()] {
        assert_eq!(status, ConstructionStatus::Destructed);
    }
    assert_eq!(p.current(), None);
    assert_eq!(*can_select.lock().unwrap(), vec![false]);
    assert_eq!(count(&log, p.id(), "current"), 1);
    assert_eq!(*callbacks.lock().unwrap(), vec![None]);

    p.construct().unwrap();
    p.set_current(Some(a.clone())).unwrap();
    callbacks.lock().unwrap().clear();
    can_select.lock().unwrap().clear();
    log.lock().unwrap().clear();

    assert_eq!(p.reconstruct(), Ok(()));

    assert!(errors.lock().unwrap().is_empty());
    assert_eq!(p.status(), ConstructionStatus::Constructed);
    assert_eq!(p.current(), None);
    assert_eq!(*can_select.lock().unwrap(), vec![false]);
    assert_eq!(count(&log, p.id(), "current"), 1);
    assert_eq!(*callbacks.lock().unwrap(), vec![None]);
}

/// COMP-052 — a refused child `select()` or `deselect()` changes nothing and
/// raises nothing: a member that is not `Constructed`, a `deselect()` of a
/// child that is not current, a call inside the caller's own uncommitted
/// membership transaction, and a call while disposal is pending.
#[test]
fn refused_child_select_and_deselect_change_nothing() {
    let hub = MessageHub::new();
    let a = child(&hub, "a");
    let b = child(&hub, "b");
    let c = child(&hub, "c");
    let members = vec![a.clone(), b.clone(), c.clone()];
    let p = Parent::builder()
        .name("p")
        .services(hub.clone(), NullDispatcher::new())
        .children(move || members.clone())
        .auto_construct_on_add(true)
        .build()
        .unwrap();
    p.construct().unwrap();
    b.destruct().unwrap();
    let (log, _subscription) = record(&hub);

    b.select();
    a.deselect();
    let d = {
        let a2 = a.clone();
        Child::builder()
            .name("d")
            .model("d")
            .on_construct(move || {
                a2.select();
                Ok(())
            })
            .services(hub.clone(), NullDispatcher::new())
            .build()
            .unwrap()
    };
    p.add(d.clone()).unwrap();

    assert_eq!(p.current(), None);
    assert_eq!(d.status(), ConstructionStatus::Constructed);

    {
        let p2 = p.clone();
        let a2 = a.clone();
        p.on_current_changed(move |value: Option<Child>| {
            if value.is_some() {
                p2.dispose().unwrap();
                a2.select();
            }
        });
    }
    p.set_current(Some(c.clone())).unwrap();

    assert_eq!(count(&log, p.id(), "current"), 1);
    assert_eq!(p.status(), ConstructionStatus::Disposed);
    assert_eq!(p.current(), Some(c.clone()));
    assert!(!a.is_current());
}

/// ADR-0189 rule 6 — a forwarding decorator that is current is cleared when
/// it is disposed, as the wrapped component is the node that publishes
/// `Disposed`.
#[test]
fn disposing_a_current_forwarding_decorator_clears_current() {
    let hub = MessageHub::new();
    let wrapped = ForwardingComponentVm::new(child(&hub, "a"));
    let other = ForwardingComponentVm::new(child(&hub, "b"));
    let p = CompositeVm::<ForwardingComponentVm<&'static str>>::with_services(
        "p",
        hub.clone(),
        NullDispatcher::new(),
    );
    p.add(wrapped.clone()).unwrap();
    p.add(other).unwrap();
    p.construct().unwrap();
    p.set_current(Some(wrapped.clone())).unwrap();
    let callbacks = record_callbacks(&p);

    wrapped.dispose().unwrap();

    assert!(p.current().is_none());
    assert!(!wrapped.is_current());
    assert_eq!(*callbacks.lock().unwrap(), vec![None]);
}

/// ADR-0189 rules 5 and 6 — `on_current_changed(None)` of the dispose clear
/// cannot select the disposed child again: the setter returns the non-member
/// error and `current` stays empty.
#[test]
fn dispose_clear_callback_cannot_reselect_the_disposed_child() {
    let hub = MessageHub::new();
    let a = child(&hub, "a");
    let b = child(&hub, "b");
    let p = parent(&hub, &[&a, &b]);
    p.construct().unwrap();
    p.set_current(Some(a.clone())).unwrap();
    let results: Log<Result<(), VmxError>> = Arc::default();
    {
        let p2 = p.clone();
        let a2 = a.clone();
        let results = Arc::clone(&results);
        p.on_current_changed(move |value: Option<Child>| {
            if value.is_none() {
                results
                    .lock()
                    .unwrap()
                    .push(p2.set_current(Some(a2.clone())));
            }
        });
    }

    a.dispose().unwrap();

    assert_eq!(*results.lock().unwrap(), vec![Err(VmxError::NonChild)]);
    assert_eq!(p.current(), None);
    assert!(!a.is_current());
}

/// ADR-0188 rule 2 — a selection from another thread while the composite
/// walks its children is refused silently, so `destruct()` returns with
/// `current` empty.
#[test]
fn selection_from_another_thread_while_destructing_changes_nothing() {
    let hub = MessageHub::new();
    let a = child(&hub, "a");
    let b = child(&hub, "b");
    let p = parent(&hub, &[&a, &b]);
    let result: Log<Result<(), VmxError>> = Arc::default();
    {
        let p2 = p.clone();
        let b2 = b.clone();
        let result = Arc::clone(&result);
        a.on_destruct(move || {
            let p3 = p2.clone();
            let b3 = b2.clone();
            let outcome = thread::spawn(move || p3.set_current(Some(b3)))
                .join()
                .unwrap();
            result.lock().unwrap().push(outcome);
            Ok(())
        });
    }
    p.construct().unwrap();

    assert_eq!(p.destruct(), Ok(()));

    assert_eq!(*result.lock().unwrap(), vec![Ok(())]);
    assert_eq!(p.current(), None);
    assert!(!b.is_current());
    assert_eq!(p.status(), ConstructionStatus::Destructed);
}

/// ADR-0188 rule 2 — with async selection, a call scheduled before
/// `destruct()` and delivered while the composite is `Destructing` is
/// dropped, and a call made while `Destructing` schedules nothing.
#[test]
fn async_selection_delivered_while_destructing_is_dropped() {
    let hub = MessageHub::new();
    let dispatcher = ManualDispatcher::new();
    let a = Child::with_model("a", "a", hub.clone(), NullDispatcher::new());
    let b = Child::with_model("b", "b", hub.clone(), NullDispatcher::new());
    let p =
        CompositeVm::<Child, ManualDispatcher>::with_services("p", hub.clone(), dispatcher.clone());
    p.set_async_selection(true);
    p.add(a.clone()).unwrap();
    p.add(b.clone()).unwrap();
    p.construct().unwrap();
    dispatcher.drain();
    let result: Log<Result<(), VmxError>> = Arc::default();
    {
        let p2 = p.clone();
        let b2 = b.clone();
        let dispatcher = dispatcher.clone();
        let result = Arc::clone(&result);
        a.on_destruct(move || {
            dispatcher.drain_foreground();
            result
                .lock()
                .unwrap()
                .push(p2.set_current(Some(b2.clone())));
            Ok(())
        });
    }
    p.set_current(Some(b.clone())).unwrap();

    assert_eq!(p.destruct(), Ok(()));
    dispatcher.drain();

    assert_eq!(*result.lock().unwrap(), vec![Ok(())]);
    assert_eq!(p.current(), None);
    assert!(!b.is_current());
    assert_eq!(p.status(), ConstructionStatus::Destructed);
}
