use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use vmx::{
    Command, DialogService, FormVm, Message, MessageHub, ModalVm, NullDialogService, VmxError,
};

/// FORM-001 — Snapshot captured at construct
#[test]
fn snapshot_is_captured_at_construction() {
    let form = FormVm::new("form", "initial".to_string());

    assert_eq!(form.snapshot(), "initial");
    assert_eq!(form.model(), "initial");
    assert!(!form.is_dirty());
}

/// FORM-002 — Model mutation reflected in IsDirty
#[test]
fn model_mutation_marks_form_dirty() {
    let form = FormVm::new("form", "initial".to_string());

    form.set_model("changed".to_string());

    assert!(form.is_dirty());
    assert_eq!(form.snapshot(), "initial");
}

/// FORM-003 — IsDirty derivation via structural inequality
#[test]
fn dirty_uses_structural_equality() {
    let form = FormVm::new("form", vec![1, 2]);

    form.set_model(vec![1, 2]);
    assert!(!form.is_dirty());
    form.set_model(vec![2, 1]);
    assert!(form.is_dirty());
}

/// FORM-004 — DenyCommand reverts Model to Snapshot
#[test]
fn deny_command_reverts_to_snapshot_without_persisting() {
    let persisted = Arc::new(Mutex::new(0));
    let persisted_inner = persisted.clone();
    let form = FormVm::with_options(
        "form",
        1,
        move |_| {
            *persisted_inner.lock().unwrap() += 1;
            Ok(())
        },
        false,
        MessageHub::new(),
    );
    form.set_model(2);

    form.deny_command().execute();

    assert_eq!(form.model(), 1);
    assert!(!form.is_dirty());
    assert_eq!(*persisted.lock().unwrap(), 0);
}

/// FORM-005 — ApproveCommand invokes persister; snapshot advances on success
#[test]
fn approve_persists_and_advances_snapshot() {
    let persisted = Arc::new(Mutex::new(Vec::new()));
    let persisted_inner = persisted.clone();
    let form = FormVm::with_options(
        "form",
        1,
        move |model| {
            persisted_inner.lock().unwrap().push(*model);
            Ok(())
        },
        false,
        MessageHub::new(),
    );
    form.set_model(2);

    form.approve().unwrap();

    assert_eq!(*persisted.lock().unwrap(), vec![2]);
    assert_eq!(form.snapshot(), 2);
    assert!(!form.is_dirty());
}

/// FORM-006 — OnApproved fires only after successful persist
#[test]
fn on_approved_fires_after_success_only() {
    let approved = Arc::new(Mutex::new(Vec::new()));
    let approved_inner = approved.clone();
    let form = FormVm::with_options("form", 1, |_| Ok(()), false, MessageHub::new());
    form.on_approved(move |model| approved_inner.lock().unwrap().push(model));
    form.set_model(2);

    form.approve().unwrap();

    assert_eq!(*approved.lock().unwrap(), vec![2]);
}

/// FORM-007 — Persist failure leaves state unchanged
#[test]
fn persist_failure_leaves_state_unchanged() {
    let form = FormVm::with_options(
        "form",
        1,
        |_| Err(VmxError::Other("boom".to_string())),
        false,
        MessageHub::new(),
    );
    form.set_model(2);

    assert!(form.approve().is_err());
    assert_eq!(form.snapshot(), 1);
    assert_eq!(form.model(), 2);
    assert!(form.is_dirty());
}

/// FORM-008 — Hub messages on revert
#[test]
fn revert_publishes_form_reverted_and_model_changed() {
    let hub = MessageHub::new();
    let form = FormVm::with_options("form", 1, |_| Ok(()), false, hub.clone());
    form.set_model(2);

    form.revert();

    assert!(hub
        .history()
        .iter()
        .any(|message| matches!(message, Message::FormReverted(_))));
    assert!(hub.history().iter().any(
        |message| matches!(message, Message::PropertyChanged(change) if change.property_name == "Model")
    ));
}

/// FORM-009 — Strict mode: ApproveCommand.CanExecute gates on IsDirty
#[test]
fn strict_mode_gates_approval_on_dirty_state() {
    let strict = FormVm::with_options("form", 1, |_| Ok(()), true, MessageHub::new());
    assert!(!strict.approve_command().can_execute());
    strict.set_model(2);
    assert!(strict.approve_command().can_execute());

    let non_strict = FormVm::with_options("form", 1, |_| Ok(()), false, MessageHub::new());
    assert!(non_strict.approve_command().can_execute());
}

/// FORM-010 — Integration with IDialogService.Confirm
#[test]
fn confirm_decorator_can_guard_deny_command() {
    let form = FormVm::new("form", 1);
    form.set_model(2);
    let guarded = form
        .deny_command()
        .confirm(|| NullDialogService.confirm("Discard?", None));

    guarded.execute();

    assert_eq!(form.model(), 2);
    assert!(form.is_dirty());
}

/// FORM-011 — FormVMBuilder<TM>.Build validates required Initial + Persister
#[test]
fn builder_validates_required_fields() {
    assert!(FormVm::<i32>::builder().initial(1).build().is_err());
    assert!(FormVm::<i32>::builder()
        .persister(|_| Ok(()))
        .build()
        .is_err());
}

/// FORM-012 — FormVMBuilder<TM> repeated identical Build calls
#[test]
fn builder_repeated_builds_create_distinct_equivalent_forms() {
    let builder = FormVm::builder()
        .initial(1)
        .persister(|_| Ok(()))
        .strict(true)
        .snapshotter(|model| *model);

    let a = builder.clone().build().unwrap();
    let b = builder.build().unwrap();

    assert_eq!(a.model(), b.model());
    assert_eq!(a.snapshot(), b.snapshot());
    assert!(!a.is_dirty());
    assert!(!b.is_dirty());
}

/// FORM-013 — FormVMBuilder<TM> field defaults applied when not set
#[test]
fn builder_defaults_are_applied() {
    let form = FormVm::builder()
        .initial(1)
        .persister(|_| Ok(()))
        .build()
        .unwrap();

    assert_eq!(form.snapshot(), 1);
    assert!(form.approve_command().can_execute());
}

/// FORM-014 — Disposed form is inert
#[test]
fn disposed_form_is_inert() {
    let persisted = Arc::new(Mutex::new(0));
    let persisted_inner = persisted.clone();
    let form = FormVm::with_options(
        "form",
        1,
        move |_| {
            *persisted_inner.lock().unwrap() += 1;
            Ok(())
        },
        false,
        MessageHub::new(),
    );
    form.set_model(2);
    form.dispose();

    form.approve_command().execute();
    form.deny_command().execute();

    assert_eq!(*persisted.lock().unwrap(), 0);
    assert_eq!(form.model(), 2);
}

/// DISP-004 — interaction owners complete once and preserve their post-dispose contract
#[test]
fn repeated_form_and_modal_dispose_preserve_one_terminal_result() {
    let persisted = Arc::new(Mutex::new(0));
    let persisted_inner = persisted.clone();
    let form = FormVm::with_options(
        "form",
        1,
        move |_| {
            *persisted_inner.lock().unwrap() += 1;
            Ok(())
        },
        false,
        MessageHub::new(),
    );
    form.set_model(2);
    form.dispose();
    form.dispose();
    form.approve_command().execute();
    assert_eq!(*persisted.lock().unwrap(), 0);

    let modal = ModalVm::new("cancel");
    modal.dismiss("first");
    modal.dispose();
    modal.dispose();
    assert_eq!(modal.completion(), "first");
}

/// FORM-015 — ApproveCommand surfaces persister failure on ApproveErrors
#[test]
fn approve_command_surfaces_persister_failure_on_error_channel() {
    let form = FormVm::with_options(
        "form",
        1,
        |_| Err(VmxError::Other("boom".to_string())),
        false,
        MessageHub::new(),
    );
    form.set_model(2);

    form.approve_command().execute();

    assert_eq!(form.approve_errors().history().len(), 1);
    assert_eq!(form.snapshot(), 1);
    assert!(form.is_dirty());
}

/// FORM-016 — Field validator populates field error
#[test]
fn field_validator_populates_field_error() {
    let form = FormVm::new("form", "".to_string());
    form.with_field_validator("name", |model| {
        if model.is_empty() {
            Some("required".to_string())
        } else {
            None
        }
    });

    assert_eq!(form.field_error("name"), Some("required".to_string()));
    assert_eq!(form.error_map().get("name"), Some(&"required".to_string()));
}

/// FORM-017 — Model validator populates errors
#[test]
fn model_validator_populates_errors() {
    let form = FormVm::new("form", 0);
    form.with_model_validator(|model| {
        let mut errors = BTreeMap::new();
        if *model == 0 {
            errors.insert("amount".to_string(), "nonzero".to_string());
        }
        errors
    });

    assert_eq!(form.field_error("amount"), Some("nonzero".to_string()));
}

/// FORM-018 — IsValid reflects errors
#[test]
fn is_valid_reflects_errors() {
    let form = FormVm::new("form", 0);
    form.with_field_validator("amount", |model| {
        (*model == 0).then(|| "nonzero".to_string())
    });

    assert!(!form.is_valid());
    form.set_model(1);
    assert!(form.is_valid());
}

/// FORM-019 — Invalid form blocks approval
#[test]
fn invalid_form_blocks_approval() {
    let persisted = Arc::new(Mutex::new(0));
    let persisted_inner = persisted.clone();
    let form = FormVm::with_options(
        "form",
        0,
        move |_| {
            *persisted_inner.lock().unwrap() += 1;
            Ok(())
        },
        false,
        MessageHub::new(),
    );
    form.with_field_validator("amount", |model| {
        (*model == 0).then(|| "nonzero".to_string())
    });

    assert!(!form.approve_command().can_execute());
    assert!(form.approve().is_err());
    assert_eq!(*persisted.lock().unwrap(), 0);
}

/// FORM-020 — Validation reruns after model mutation
#[test]
fn validation_reruns_after_model_mutation() {
    let form = FormVm::new("form", 0);
    form.with_field_validator("amount", |model| {
        (*model == 0).then(|| "nonzero".to_string())
    });

    form.set_model(1);

    assert!(form.error_map().is_empty());
    assert!(form.is_valid());
}

/// FORM-021 — ErrorsChanged fires only on effective changes
#[test]
fn errors_changed_fires_only_on_effective_changes() {
    let form = FormVm::new("form", 0);
    form.with_field_validator("amount", |model| {
        (*model == 0).then(|| "nonzero".to_string())
    });
    let initial = form.errors_changed().history().len();

    form.set_model(0);
    assert_eq!(form.errors_changed().history().len(), initial);
    form.set_model(1);
    assert_eq!(form.errors_changed().history().len(), initial + 1);
}

/// FORM-022 — FormVMBuilder<TM> registers validators immutably
#[test]
fn builder_registers_validators_immutably() {
    let base = FormVm::builder().initial(0).persister(|_| Ok(()));
    let with_validator = base.clone().validator("amount", |model| {
        (*model == 0).then(|| "nonzero".to_string())
    });

    assert!(base.build().unwrap().is_valid());
    assert!(!with_validator.build().unwrap().is_valid());
}

/// FORM-023 — Clearing errors enables approval when other gates pass
#[test]
fn clearing_errors_enables_approval() {
    let form = FormVm::with_options("form", 0, |_| Ok(()), true, MessageHub::new());
    form.with_field_validator("amount", |model| {
        (*model == 0).then(|| "nonzero".to_string())
    });

    form.set_model(1);

    assert!(form.is_valid());
    assert!(form.approve_command().can_execute());
}
