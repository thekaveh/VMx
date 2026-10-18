//! Regression tests: user `PartialEq` code never runs while a VMx mutex is
//! held, so an `eq` that reads its owner returns instead of deadlocking, and
//! deterministic notification clocks saturate instead of overflowing.

use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;
use vmx::{
    ComponentVm, ConfirmationVm, DiscriminatorVm, KeyedServicedObservableCollection, MessageHub,
    NotificationHub, NotificationReaction, NotificationType, NotificationVm, NullDispatcher,
    ObservableDictionary, ServicedObservableCollection, TokenPagedComposition,
};

/// Runs `body` on a worker and fails if it does not finish in time, so a
/// deadlock regression fails the test instead of hanging the suite.
fn within_timeout<R: Send + 'static>(what: &str, body: impl FnOnce() -> R + Send + 'static) -> R {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(body());
    });
    rx.recv_timeout(Duration::from_secs(5))
        .unwrap_or_else(|_| panic!("{what} deadlocked: user eq ran under an internal lock"))
}

type Probe = Arc<Mutex<Option<Arc<dyn Fn() + Send + Sync>>>>;

/// A value whose `eq` calls `probe`, which reads the owner it lives in.
#[derive(Clone)]
struct Probing {
    id: u32,
    probe: Probe,
}

impl Probing {
    fn new(id: u32, probe: &Probe) -> Self {
        Self {
            id,
            probe: Arc::clone(probe),
        }
    }
}

impl PartialEq for Probing {
    fn eq(&self, other: &Self) -> bool {
        let probe = self.probe.lock().unwrap().clone();
        if let Some(probe) = probe {
            probe();
        }
        self.id == other.id
    }
}

impl Eq for Probing {}

impl std::hash::Hash for Probing {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

#[test]
fn component_set_model_eq_may_read_the_component() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let vm = ComponentVm::with_model(
        "probing",
        Probing::new(1, &probe),
        MessageHub::new(),
        NullDispatcher::new(),
    );
    let reader = vm.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.model();
    }));
    let (equal, changed) = within_timeout("ComponentVm::set_model", {
        let vm = vm.clone();
        let probe = Arc::clone(&probe);
        move || {
            vm.set_model(Probing::new(1, &probe));
            let equal = vm.model().id;
            vm.set_model(Probing::new(2, &probe));
            (equal, vm.model().id)
        }
    });
    assert_eq!(equal, 1);
    assert_eq!(changed, 2);
    *probe.lock().unwrap() = None;
}

#[test]
fn serviced_collection_remove_eq_may_read_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(Probing::new(1, &probe));
    collection.push(Probing::new(2, &probe));
    let reader = collection.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.len();
    }));
    let removed = within_timeout("ServicedObservableCollection::remove", {
        let collection = collection.clone();
        let probe = Arc::clone(&probe);
        move || collection.remove(&Probing::new(2, &probe))
    });
    assert!(removed);
    assert_eq!(
        collection
            .to_vec()
            .iter()
            .map(|item| item.id)
            .collect::<Vec<_>>(),
        [1]
    );
    *probe.lock().unwrap() = None;
}

#[test]
fn serviced_collection_remove_rescans_after_eq_mutates_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = ServicedObservableCollection::new(1);
    collection.push(Probing::new(1, &probe));
    collection.push(Probing::new(2, &probe));
    let writer = collection.clone();
    let once = Arc::new(Mutex::new(true));
    *probe.lock().unwrap() = Some(Arc::new(move || {
        if std::mem::take(&mut *once.lock().unwrap()) {
            // Shifts the target, so the index found on the copy is stale.
            let _ = writer.remove_at(0);
        }
    }));
    let removed = within_timeout("ServicedObservableCollection::remove", {
        let collection = collection.clone();
        let probe = Arc::clone(&probe);
        move || collection.remove(&Probing::new(2, &probe))
    });
    assert!(removed);
    assert!(collection.is_empty());
    *probe.lock().unwrap() = None;
}

#[test]
fn keyed_collection_remove_eq_may_read_the_collection() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let collection = KeyedServicedObservableCollection::new(1, |item: &Probing| Ok(item.id));
    collection.push(Probing::new(1, &probe)).unwrap();
    collection.push(Probing::new(2, &probe)).unwrap();
    let reader = collection.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.len();
    }));
    let removed = within_timeout("KeyedServicedObservableCollection::remove", {
        let collection = collection.clone();
        let probe = Arc::clone(&probe);
        move || collection.remove(&Probing::new(1, &probe))
    });
    assert!(removed);
    assert_eq!(collection.len(), 1);
    *probe.lock().unwrap() = None;
}

#[test]
fn dictionary_eq_may_read_the_dictionary() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let dictionary = ObservableDictionary::new(1, MessageHub::new());
    dictionary.insert(Probing::new(1, &probe), "one");
    let reader = dictionary.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.keys();
    }));
    let (value, removed) = within_timeout("ObservableDictionary", {
        let dictionary = dictionary.clone();
        let probe = Arc::clone(&probe);
        move || {
            dictionary.insert(Probing::new(1, &probe), "uno");
            let value = dictionary.get(&Probing::new(1, &probe));
            (value, dictionary.remove(&Probing::new(1, &probe)))
        }
    });
    assert_eq!(value, Some("uno"));
    assert_eq!(removed, Some("uno"));
    assert!(dictionary.keys().is_empty());
    *probe.lock().unwrap() = None;
}

#[test]
fn discriminator_eq_may_read_the_discriminator() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let discriminator = DiscriminatorVm::new(Probing::new(1, &probe));
    let reader = discriminator.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.active_key();
    }));
    let active = within_timeout("DiscriminatorVm::set_active_key", {
        let discriminator = discriminator.clone();
        let probe = Arc::clone(&probe);
        move || {
            discriminator.set_active_key(Probing::new(2, &probe));
            discriminator.is_active(&Probing::new(2, &probe))
        }
    });
    assert!(active);
    *probe.lock().unwrap() = None;
}

#[test]
fn token_paged_refresh_eq_may_read_the_pager() {
    let probe: Probe = Arc::new(Mutex::new(None));
    let pages_probe = Arc::clone(&probe);
    let pager = TokenPagedComposition::with_loader(None, move |token: Option<u8>| match token {
        None => (vec![Probing::new(1, &pages_probe)], Some(1)),
        Some(_) => (vec![Probing::new(2, &pages_probe)], None),
    });
    pager.load_next();
    pager.load_next();
    let reader = pager.clone();
    *probe.lock().unwrap() = Some(Arc::new(move || {
        let _ = reader.items();
    }));
    let ids = within_timeout("TokenPagedComposition::refresh", {
        let pager = pager.clone();
        move || {
            pager.refresh();
            pager.items().iter().map(|item| item.id).collect::<Vec<_>>()
        }
    });
    // The refreshed page matches the loaded prefix, so the tail is kept.
    assert_eq!(ids, [1, 2]);
    *probe.lock().unwrap() = None;
}

#[test]
fn notification_clock_saturates_instead_of_overflowing() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Notification, "info");
    let vm = NotificationVm::with_hub(notification.clone(), hub.clone(), 10_000);

    vm.advance_by_ms(1);
    vm.advance_by_ms(u64::MAX);

    assert_eq!(vm.remaining_time_ms(), 0);
    assert!(vm.is_resolved());
    assert_eq!(hub.reaction(notification.id), NotificationReaction::Approve);
}

#[test]
fn confirmation_clock_saturates_instead_of_overflowing() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Confirmation, "confirm?");
    let vm = ConfirmationVm::with_hub(notification, hub);

    vm.advance_by_ms(1);
    vm.advance_by_ms(u64::MAX);

    assert_eq!(vm.remaining_time_ms(), 0);
    assert_eq!(vm.opacity(), 0.0);
    assert!(!vm.is_resolved(), "an expired confirmation stays pending");
}
