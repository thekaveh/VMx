use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use vmx::{ComponentVm, FormVm, MessageHub, NullDispatcher};

#[derive(Clone, Debug)]
struct CountingModel {
    value: i32,
    equality_calls: Arc<AtomicUsize>,
}

impl PartialEq for CountingModel {
    fn eq(&self, other: &Self) -> bool {
        self.equality_calls.fetch_add(1, Ordering::SeqCst);
        self.value == other.value
    }
}

/// DISP-014 — Modeled assignment after disposal is inert.
#[test]
fn modeled_assignment_after_disposal_is_inert() {
    let component_hub = MessageHub::new();
    let equality_calls = Arc::new(AtomicUsize::new(0));
    let hinter_calls = Arc::new(AtomicUsize::new(0));
    let initial = CountingModel {
        value: 1,
        equality_calls: equality_calls.clone(),
    };
    let replacement = CountingModel {
        value: 2,
        equality_calls: equality_calls.clone(),
    };
    let hinter_calls_for_component = hinter_calls.clone();
    let component = ComponentVm::with_model(
        "component",
        initial.clone(),
        component_hub.clone(),
        NullDispatcher::new(),
    )
    .with_model_hint(move |model| {
        hinter_calls_for_component.fetch_add(1, Ordering::SeqCst);
        Some(format!("hint:{}", model.value))
    });
    let initial_hint = component.hint();
    let local_changes = Arc::new(Mutex::new(Vec::new()));
    let local_changes_for_subscription = local_changes.clone();
    let _local_subscription = component.property_changed().subscribe(move |name| {
        local_changes_for_subscription
            .lock()
            .unwrap()
            .push(name.to_string());
    });

    component.dispose().unwrap();
    equality_calls.store(0, Ordering::SeqCst);
    hinter_calls.store(0, Ordering::SeqCst);
    local_changes.lock().unwrap().clear();
    let component_history_len = component_hub.history().len();
    let late_component_completion = || component.set_model(replacement.clone());

    late_component_completion();

    assert_eq!(component.model().value, initial.value);
    assert_eq!(equality_calls.load(Ordering::SeqCst), 0);
    assert_eq!(hinter_calls.load(Ordering::SeqCst), 0);
    assert!(local_changes.lock().unwrap().is_empty());
    assert_eq!(component_hub.history().len(), component_history_len);
    assert_eq!(component.hint(), initial_hint);

    let form_hub = MessageHub::new();
    let form_equality_calls = Arc::new(AtomicUsize::new(0));
    let validator_calls = Arc::new(AtomicUsize::new(0));
    let initial_form_model = CountingModel {
        value: 1,
        equality_calls: form_equality_calls.clone(),
    };
    let form = FormVm::with_options(
        "form",
        initial_form_model.clone(),
        |_| Ok(()),
        true,
        form_hub.clone(),
    );
    let validator_calls_for_form = validator_calls.clone();
    form.with_field_validator("value", move |model| {
        validator_calls_for_form.fetch_add(1, Ordering::SeqCst);
        (model.value < 0).then(|| "negative".to_string())
    });
    let initial_snapshot = form.snapshot();
    let initial_errors = form.error_map();
    let initial_dirty = form.is_dirty();
    let initial_valid = form.is_valid();
    let error_signals = Arc::new(AtomicUsize::new(0));
    let error_signals_for_subscription = error_signals.clone();
    let _errors_subscription = form.errors_changed().subscribe(move |_| {
        error_signals_for_subscription.fetch_add(1, Ordering::SeqCst);
    });
    let command = form.approve_command();
    let command_signals = Arc::new(AtomicUsize::new(0));
    let command_signals_for_subscription = command_signals.clone();
    let _command_subscription = command.can_execute_changed().subscribe(move |_| {
        command_signals_for_subscription.fetch_add(1, Ordering::SeqCst);
    });

    form.dispose();
    form_equality_calls.store(0, Ordering::SeqCst);
    validator_calls.store(0, Ordering::SeqCst);
    error_signals.store(0, Ordering::SeqCst);
    command_signals.store(0, Ordering::SeqCst);
    let form_history_len = form_hub.history().len();
    let late_form_completion = || {
        form.set_model(CountingModel {
            value: -1,
            equality_calls: form_equality_calls.clone(),
        });
    };

    late_form_completion();

    assert_eq!(form.model().value, initial_form_model.value);
    assert_eq!(form.snapshot().value, initial_snapshot.value);
    assert_eq!(form.error_map(), initial_errors);
    assert_eq!(form_equality_calls.load(Ordering::SeqCst), 0);
    assert_eq!(validator_calls.load(Ordering::SeqCst), 0);
    assert_eq!(error_signals.load(Ordering::SeqCst), 0);
    assert_eq!(command_signals.load(Ordering::SeqCst), 0);
    assert_eq!(form_hub.history().len(), form_history_len);
    assert_eq!(form.is_dirty(), initial_dirty);
    assert_eq!(form.is_valid(), initial_valid);
}
