use vmx::DiscriminatorVm;

/// DISC-001 — Initial active key and IsActive
#[test]
fn initial_active_key_and_is_active() {
    let vm = DiscriminatorVm::new("home", ["home", "settings"]);

    assert_eq!(vm.active_key(), "home");
    assert!(vm.is_active(&"home"));
    assert!(!vm.is_active(&"settings"));
}

/// DISC-002 — Changing active key emits once
#[test]
fn changing_active_key_emits_once() {
    let vm = DiscriminatorVm::new("home", ["home", "settings"]);

    vm.set_active_key("settings").unwrap();

    assert_eq!(vm.active_key(), "settings");
    assert_eq!(vm.active_changed().history().len(), 1);
}

/// DISC-003 — Setting the same key is a no-op
#[test]
fn setting_same_key_is_noop() {
    let vm = DiscriminatorVm::new("home", ["home", "settings"]);

    vm.set_active_key("home").unwrap();

    assert!(vm.active_changed().history().is_empty());
}

/// DISC-004 — Modal open activates modal key
#[test]
fn modal_open_activates_modal_key() {
    let vm = DiscriminatorVm::new("home", ["home"]);

    vm.modal_open("modal").unwrap();

    assert_eq!(vm.active_key(), "modal");
    assert!(vm.is_active(&"modal"));
}

/// DISC-005 — Modal close restores prior key
#[test]
fn modal_close_restores_prior_key() {
    let vm = DiscriminatorVm::new("home", ["home", "settings"]);
    vm.set_active_key("settings").unwrap();
    vm.modal_open("modal").unwrap();

    vm.modal_close().unwrap();

    assert_eq!(vm.active_key(), "settings");
}

/// DISC-006 — Nested modal precedence restores in LIFO order
#[test]
fn nested_modal_precedence_restores_lifo() {
    let vm = DiscriminatorVm::new("home", ["home"]);

    vm.modal_open("a").unwrap();
    vm.modal_open("b").unwrap();
    vm.modal_close().unwrap();
    assert_eq!(vm.active_key(), "a");
    vm.modal_close().unwrap();
    assert_eq!(vm.active_key(), "home");
}
