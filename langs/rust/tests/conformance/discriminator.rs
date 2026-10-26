use vmx::DiscriminatorVm;

/// DISC-001 — Initial active key and IsActive
#[test]
fn initial_active_key_and_is_active() {
    let vm = DiscriminatorVm::new("home");

    assert_eq!(vm.active_key(), "home");
    assert!(vm.is_active(&"home"));
    assert!(!vm.is_active(&"settings"));
}

/// DISC-002 — Changing active key emits once
#[test]
fn changing_active_key_emits_once() {
    let vm = DiscriminatorVm::new("home");
    let vm_active_changed_record = vm.active_changed().record(1024);

    vm.set_active_key("settings");

    assert_eq!(vm.active_key(), "settings");
    assert_eq!(vm_active_changed_record.messages().len(), 1);
}

/// DISC-002 — The change stream carries the new active key
#[test]
fn active_key_changes_carry_the_new_key() {
    let vm = DiscriminatorVm::new("home");
    let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let _subscription = vm.active_key_changes().subscribe({
        let seen = std::sync::Arc::clone(&seen);
        move |key| seen.lock().unwrap().push(key)
    });

    vm.set_active_key("detail");
    vm.set_active_key("detail");
    vm.modal_open("modal");
    vm.modal_close();

    assert_eq!(*seen.lock().unwrap(), vec!["detail", "modal", "detail"]);
}

/// DISC-002 — a hub subscriber that changes the key again leaves the stream on
/// the active key.
#[test]
fn active_key_changes_end_on_the_active_key_after_a_reentrant_change() {
    let vm = DiscriminatorVm::new("home");
    let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let _keys = vm.active_key_changes().subscribe({
        let seen = std::sync::Arc::clone(&seen);
        move |key| seen.lock().unwrap().push(key)
    });
    let _redirect = vm.active_changed().subscribe({
        let vm = vm.clone();
        move |_| {
            if vm.active_key() == "detail" {
                vm.set_active_key("settings");
            }
        }
    });

    vm.set_active_key("detail");

    assert_eq!(vm.active_key(), "settings");
    assert_eq!(*seen.lock().unwrap(), vec!["detail", "settings"]);
}

/// DISC-003 — Setting the same key is a no-op
#[test]
fn setting_same_key_is_noop() {
    let vm = DiscriminatorVm::new("home");
    let vm_active_changed_record = vm.active_changed().record(1024);

    vm.set_active_key("home");

    assert!(vm_active_changed_record.messages().is_empty());
}

/// DISC-004 — Modal open activates modal key
#[test]
fn modal_open_activates_modal_key() {
    let vm = DiscriminatorVm::new("home");

    vm.modal_open("modal");

    assert_eq!(vm.active_key(), "modal");
    assert!(vm.is_active(&"modal"));
}

/// DISC-005 — Modal close restores prior key
#[test]
fn modal_close_restores_prior_key() {
    let vm = DiscriminatorVm::new("home");
    vm.set_active_key("settings");
    vm.modal_open("modal");

    vm.modal_close();

    assert_eq!(vm.active_key(), "settings");
}

/// DISC-006 — Nested modal precedence restores in LIFO order
#[test]
fn nested_modal_precedence_restores_lifo() {
    let vm = DiscriminatorVm::new("home");

    vm.modal_open("a");
    vm.modal_open("b");
    vm.modal_close();
    assert_eq!(vm.active_key(), "a");
    vm.modal_close();
    assert_eq!(vm.active_key(), "home");
}

/// DISC-007 — modal depth tracks frames and disposal releases them.
#[test]
fn modal_depth_tracks_frames_and_disposal_releases_them() {
    let vm = DiscriminatorVm::new("home");
    assert_eq!(vm.modal_depth(), 0);
    vm.modal_open("a");
    assert_eq!(vm.modal_depth(), 1);
    vm.modal_open("b");
    assert_eq!(vm.modal_depth(), 2);
    vm.modal_close();
    assert_eq!(vm.modal_depth(), 1);
    vm.dispose();
    assert_eq!(vm.modal_depth(), 0);
}

/// DISC-008 — clear modals drains without changing the active key.
#[test]
fn clear_modals_drains_without_changing_active_key() {
    let vm = DiscriminatorVm::new("home");
    let vm_active_changed_record = vm.active_changed().record(1024);
    vm.modal_open("a");
    vm.modal_open("b");
    let change_count = vm_active_changed_record.messages().len();

    vm.clear_modals();

    assert_eq!(vm.modal_depth(), 0);
    assert_eq!(vm.active_key(), "b");
    assert_eq!(vm_active_changed_record.messages().len(), change_count);
    vm.modal_close();
    assert_eq!(vm.active_key(), "b");
}

/// DISC-009 — non-modal set abandons history including for the active key.
#[test]
fn non_modal_set_abandons_history_including_same_key() {
    let vm = DiscriminatorVm::new("home");
    let vm_active_changed_record = vm.active_changed().record(1024);
    vm.modal_open("a");
    vm.modal_open("b");

    vm.set_active_key("route");

    assert_eq!(vm.modal_depth(), 0);
    vm.modal_close();
    assert_eq!(vm.active_key(), "route");

    vm.modal_open("modal");
    let change_count = vm_active_changed_record.messages().len();
    vm.set_active_key("modal");
    assert_eq!(vm.modal_depth(), 0);
    assert_eq!(vm_active_changed_record.messages().len(), change_count);
}

/// DISC-003 — arbitrary keys are valid and disposal makes later mutations inert.
#[test]
fn arbitrary_keys_are_valid_and_disposal_is_terminal() {
    let vm = DiscriminatorVm::new("home");
    let vm_active_changed_record = vm.active_changed().record(1024);

    vm.set_active_key("unlisted");
    assert_eq!(vm.active_key(), "unlisted");
    assert_eq!(vm_active_changed_record.messages().len(), 1);

    vm.dispose();
    vm.set_active_key("after-dispose");
    vm.modal_open("modal-after-dispose");
    vm.modal_close();
    vm.dispose();

    assert_eq!(vm.active_key(), "unlisted");
    assert_eq!(vm_active_changed_record.messages().len(), 1);
}

/// A key whose id-0 instances run `on_replaced` once, when dropped after
/// key 0 stopped being active: that is the replaced key, not a compared copy.
#[derive(Clone)]
struct ProbeKey {
    id: u32,
    probe: std::sync::Arc<KeyProbe>,
}

type OnReplaced = Box<dyn FnOnce(&DiscriminatorVm<ProbeKey>) + Send>;

struct KeyProbe {
    vm: std::sync::OnceLock<DiscriminatorVm<ProbeKey>>,
    on_replaced: std::sync::Mutex<Option<OnReplaced>>,
    in_drop: std::sync::atomic::AtomicBool,
}

impl PartialEq for ProbeKey {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl Drop for ProbeKey {
    fn drop(&mut self) {
        use std::sync::atomic::Ordering;
        if self.id != 0 || self.probe.in_drop.swap(true, Ordering::SeqCst) {
            return;
        }
        if let Some(vm) = self.probe.vm.get() {
            if vm.active_key().id != 0 {
                let action = self.probe.on_replaced.lock().unwrap().take();
                if let Some(action) = action {
                    action(vm);
                }
            }
        }
        self.probe.in_drop.store(false, Ordering::SeqCst);
    }
}

/// A discriminator on key 0 whose replaced key 0 runs `on_replaced`, and a
/// record of the keys `active_key_changes` delivers.
type ProbedDiscriminator = (
    DiscriminatorVm<ProbeKey>,
    std::sync::Arc<KeyProbe>,
    std::sync::Arc<std::sync::Mutex<Vec<u32>>>,
    vmx::ValueSubscription,
);

fn probed_discriminator(
    on_replaced: impl FnOnce(&DiscriminatorVm<ProbeKey>) + Send + 'static,
) -> ProbedDiscriminator {
    let probe = std::sync::Arc::new(KeyProbe {
        vm: std::sync::OnceLock::new(),
        on_replaced: std::sync::Mutex::new(Some(Box::new(on_replaced))),
        in_drop: std::sync::atomic::AtomicBool::new(false),
    });
    let vm = DiscriminatorVm::new(ProbeKey {
        id: 0,
        probe: probe.clone(),
    });
    let _ = probe.vm.set(vm.clone());
    let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let subscription = vm.active_key_changes().subscribe({
        let seen = seen.clone();
        move |key: ProbeKey| seen.lock().unwrap().push(key.id)
    });
    (vm, probe, seen, subscription)
}

fn key(probe: &std::sync::Arc<KeyProbe>, id: u32) -> ProbeKey {
    ProbeKey {
        id,
        probe: probe.clone(),
    }
}

/// Asserts that the stream ended on the active key.
fn assert_stream_ends_on_the_active_key(
    vm: &DiscriminatorVm<ProbeKey>,
    seen: &std::sync::Mutex<Vec<u32>>,
) {
    let active = vm.active_key().id;
    assert_eq!(seen.lock().unwrap().last(), Some(&active));
    assert_eq!(vm.active_key_changes().value().id, active);
}

/// #752 — the replaced key's `Drop` sets another key; the stream still ends
/// on the active key.
#[test]
fn active_key_changes_end_on_the_active_key_after_a_change_from_drop() {
    let (vm, probe, seen, _subscription) = probed_discriminator(|vm| {
        let probe = vm.active_key().probe.clone();
        vm.set_active_key(key(&probe, 2));
    });
    let changes = vm.active_changed().record(1024);

    vm.set_active_key(key(&probe, 1));

    assert_eq!(vm.active_key().id, 2);
    assert_stream_ends_on_the_active_key(&vm, &seen);
    assert_eq!(
        changes.messages().len(),
        2,
        "one message per effective change"
    );
}

/// #752 — the same through `modal_open`.
#[test]
fn active_key_changes_end_on_the_active_key_after_a_modal_open_change_from_drop() {
    let (vm, probe, seen, _subscription) = probed_discriminator(|vm| {
        let probe = vm.active_key().probe.clone();
        vm.set_active_key(key(&probe, 2));
    });

    vm.modal_open(key(&probe, 1));

    assert_eq!(vm.active_key().id, 2);
    assert_stream_ends_on_the_active_key(&vm, &seen);
}

/// #752 — a setter paused after its commit while another thread's setter
/// completes does not leave the stream on its older key.
#[test]
fn active_key_changes_end_on_the_active_key_across_threads() {
    let (paused_tx, paused_rx) = std::sync::mpsc::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel::<()>();
    let (vm, probe, seen, _subscription) = probed_discriminator(move |_| {
        paused_tx.send(()).unwrap();
        release_rx.recv().unwrap();
    });
    let first = {
        let vm = vm.clone();
        let one = key(&probe, 1);
        std::thread::spawn(move || vm.set_active_key(one))
    };
    paused_rx
        .recv_timeout(std::time::Duration::from_secs(3))
        .unwrap();
    let second = {
        let vm = vm.clone();
        let two = key(&probe, 2);
        std::thread::spawn(move || vm.set_active_key(two))
    };
    second.join().unwrap();
    release_tx.send(()).unwrap();
    first.join().unwrap();

    assert_eq!(vm.active_key().id, 2);
    assert_stream_ends_on_the_active_key(&vm, &seen);
}
