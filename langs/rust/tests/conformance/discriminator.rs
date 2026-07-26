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

    vm.set_active_key("settings");

    assert_eq!(vm.active_key(), "settings");
    assert_eq!(vm.active_changed().history().len(), 1);
}

/// DISC-003 — Setting the same key is a no-op
#[test]
fn setting_same_key_is_noop() {
    let vm = DiscriminatorVm::new("home");

    vm.set_active_key("home");

    assert!(vm.active_changed().history().is_empty());
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
    vm.modal_open("a");
    vm.modal_open("b");
    let change_count = vm.active_changed().history().len();

    vm.clear_modals();

    assert_eq!(vm.modal_depth(), 0);
    assert_eq!(vm.active_key(), "b");
    assert_eq!(vm.active_changed().history().len(), change_count);
    vm.modal_close();
    assert_eq!(vm.active_key(), "b");
}

/// DISC-009 — non-modal set abandons history including for the active key.
#[test]
fn non_modal_set_abandons_history_including_same_key() {
    let vm = DiscriminatorVm::new("home");
    vm.modal_open("a");
    vm.modal_open("b");

    vm.set_active_key("route");

    assert_eq!(vm.modal_depth(), 0);
    vm.modal_close();
    assert_eq!(vm.active_key(), "route");

    vm.modal_open("modal");
    let change_count = vm.active_changed().history().len();
    vm.set_active_key("modal");
    assert_eq!(vm.modal_depth(), 0);
    assert_eq!(vm.active_changed().history().len(), change_count);
}

/// DISC-003 — arbitrary keys are valid and disposal makes later mutations inert.
#[test]
fn arbitrary_keys_are_valid_and_disposal_is_terminal() {
    let vm = DiscriminatorVm::new("home");

    vm.set_active_key("unlisted");
    assert_eq!(vm.active_key(), "unlisted");
    assert_eq!(vm.active_changed().history().len(), 1);

    vm.dispose();
    vm.set_active_key("after-dispose");
    vm.modal_open("modal-after-dispose");
    vm.modal_close();
    vm.dispose();

    assert_eq!(vm.active_key(), "unlisted");
    assert_eq!(vm.active_changed().history().len(), 1);
}
