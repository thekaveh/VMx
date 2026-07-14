use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Barrier, Mutex};
use std::time::Duration;

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
    let start = hub.history().len();

    form.revert();

    let history = hub.history();
    let messages = &history[start..];
    assert_eq!(messages.len(), 2);
    assert!(matches!(messages[0], Message::FormReverted(_)));
    assert!(matches!(
        messages[1],
        Message::PropertyChanged(ref change) if change.property_name == "model"
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

#[test]
fn form_commands_are_stable_handles() {
    let form = FormVm::new("form", 1);
    let first = form.approve_command();
    let second = form.approve_command();
    let notifications = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&notifications);
    let _subscription = second.can_execute_changed().subscribe(move |_| {
        observed.fetch_add(1, Ordering::SeqCst);
    });

    first.raise_can_execute_changed();

    assert_eq!(notifications.load(Ordering::SeqCst), 1);
}

#[test]
fn form_dispose_closes_commands_and_owned_channels() {
    let form = FormVm::new("form", 1);
    let approve = form.approve_command();
    let deny = form.deny_command();
    let approve_changed = approve.can_execute_changed();
    let deny_changed = deny.can_execute_changed();
    let errors_changed = form.errors_changed();
    let approve_errors = form.approve_errors();
    let notifications = Arc::new(AtomicUsize::new(0));
    let mut subscriptions = Vec::new();
    for hub in [
        approve_changed.clone(),
        deny_changed.clone(),
        errors_changed.clone(),
        approve_errors.clone(),
    ] {
        let observed = Arc::clone(&notifications);
        subscriptions.push(hub.subscribe(move |_| {
            observed.fetch_add(1, Ordering::SeqCst);
        }));
    }

    form.dispose();
    approve.raise_can_execute_changed();
    deny.raise_can_execute_changed();
    for hub in [approve_changed, deny_changed] {
        hub.send(Message::Custom {
            sender_id: 0,
            name: "late-command-change".to_string(),
        });
    }
    errors_changed.send(Message::Custom {
        sender_id: 0,
        name: "late-error-change".to_string(),
    });
    approve_errors.send(Message::Custom {
        sender_id: 0,
        name: "late-approve-error".to_string(),
    });

    assert!(!approve.can_execute());
    assert!(!deny.can_execute());
    assert_eq!(notifications.load(Ordering::SeqCst), 0);
    drop(subscriptions);
}

#[test]
fn approved_callbacks_may_register_callbacks_reentrantly() {
    let form = FormVm::new("form", 1);
    let holder = Arc::new(Mutex::new(Some(form.clone())));
    let reentrant_holder = Arc::clone(&holder);
    form.on_approved(move |_| {
        let form = reentrant_holder.lock().unwrap().clone().unwrap();
        form.on_approved(|_| {});
    });
    form.set_model(2);
    let (completed, completion) = mpsc::channel();

    std::thread::spawn(move || {
        completed.send(form.approve()).unwrap();
    });

    assert!(completion
        .recv_timeout(Duration::from_secs(1))
        .expect("approval deadlocked while invoking a callback")
        .is_ok());
}

#[test]
fn validators_may_register_validators_reentrantly() {
    let form = FormVm::new("form", 1);
    let holder = Arc::new(Mutex::new(Some(form.clone())));
    let reentrant_holder = Arc::clone(&holder);
    let first_call = Arc::new(AtomicBool::new(true));
    let reentrant_first_call = Arc::clone(&first_call);
    let (completed, completion) = mpsc::channel();

    std::thread::spawn(move || {
        form.with_field_validator("outer", move |_| {
            if reentrant_first_call.swap(false, Ordering::SeqCst) {
                let form = reentrant_holder.lock().unwrap().clone().unwrap();
                form.with_field_validator("inner", |_| None);
            }
            None
        });
        completed.send(()).unwrap();
    });

    completion
        .recv_timeout(Duration::from_secs(1))
        .expect("validation deadlocked while invoking a validator");
}

#[test]
fn snapshotter_may_read_snapshot_reentrantly() {
    let holder = Arc::new(Mutex::new(None::<FormVm<i32>>));
    let reentrant_holder = Arc::clone(&holder);
    let armed = Arc::new(AtomicBool::new(false));
    let reentrant_armed = Arc::clone(&armed);
    let form = FormVm::builder()
        .initial(1)
        .persister(|_| Ok(()))
        .snapshotter(move |model| {
            if reentrant_armed.load(Ordering::SeqCst) {
                let form = reentrant_holder.lock().unwrap().clone().unwrap();
                let _ = form.snapshot();
            }
            *model
        })
        .build()
        .unwrap();
    *holder.lock().unwrap() = Some(form.clone());
    armed.store(true, Ordering::SeqCst);
    form.set_model(2);
    let (completed, completion) = mpsc::channel();

    std::thread::spawn(move || {
        form.revert();
        completed.send(()).unwrap();
    });

    completion
        .recv_timeout(Duration::from_secs(1))
        .expect("revert deadlocked while invoking the snapshotter");
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
    assert_eq!(modal.completion().wait(), "first");
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

/// FORM-024 — Reset runs after persistence and OnApproved receives the captured model
#[test]
fn reset_runs_after_persist_and_approved_uses_captured_model() {
    let order = Arc::new(Mutex::new(Vec::new()));
    let persist_order = order.clone();
    let reset_order = order.clone();
    let form = FormVm::builder()
        .initial("initial".to_string())
        .persister(move |model| {
            persist_order
                .lock()
                .unwrap()
                .push(format!("persist:{model}"));
            Ok(())
        })
        .reset_on_approved(move |model| {
            reset_order.lock().unwrap().push(format!("reset:{model}"));
            Ok("reset".to_string())
        })
        .build()
        .unwrap();
    let approved_order = order.clone();
    let observed_form = form.clone();
    form.on_approved(move |model| {
        assert_eq!(observed_form.model(), "reset");
        assert_eq!(observed_form.snapshot(), "reset");
        assert!(!observed_form.is_dirty());
        approved_order
            .lock()
            .unwrap()
            .push(format!("approved:{model}"));
    });
    form.set_model("saved".to_string());

    form.approve().unwrap();

    assert_eq!(
        *order.lock().unwrap(),
        vec!["persist:saved", "reset:saved", "approved:saved"]
    );
    assert_eq!(form.model(), "reset");
    assert_eq!(form.snapshot(), "reset");
    assert!(!form.is_dirty());
}

#[test]
fn reset_error_observer_mutation_runs_after_pristine_approval() {
    let form = FormVm::builder()
        .initial("saved".to_string())
        .persister(|_| Ok(()))
        .validator("value", |model| {
            model.is_empty().then(|| "required".to_string())
        })
        .reset_on_approved(|_| Ok(String::new()))
        .build()
        .unwrap();
    let reentrant_form = form.clone();
    let _subscription = form.errors_changed().subscribe(move |_| {
        reentrant_form.set_model("reentrant".to_string());
    });
    let observed = Arc::new(Mutex::new(Vec::new()));
    let observed_inner = Arc::clone(&observed);
    let approval_form = form.clone();
    form.on_approved(move |approved| {
        observed_inner.lock().unwrap().push((
            approved,
            approval_form.model(),
            approval_form.snapshot(),
            approval_form.is_dirty(),
        ));
    });

    form.approve().unwrap();

    assert_eq!(
        *observed.lock().unwrap(),
        vec![("saved".to_string(), String::new(), String::new(), false)]
    );
    assert_eq!(form.model(), "reentrant");
    assert_eq!(form.snapshot(), "");
    assert!(form.is_dirty());
}

#[derive(Clone, Debug)]
struct ResetModel {
    value: String,
    nested: Arc<Mutex<Vec<i32>>>,
}

impl PartialEq for ResetModel {
    fn eq(&self, other: &Self) -> bool {
        self.value == other.value && *self.nested.lock().unwrap() == *other.nested.lock().unwrap()
    }
}

/// FORM-025 — Reset output is snapshotted twice, independent, revalidated, and strict-clean
#[test]
fn reset_is_snapshotted_twice_and_revalidated() {
    let calls = Arc::new(Mutex::new(0));
    let calls_inner = calls.clone();
    let form = FormVm::builder()
        .initial(ResetModel {
            value: "initial".into(),
            nested: Arc::new(Mutex::new(vec![])),
        })
        .persister(|_| Ok(()))
        .strict(true)
        .snapshotter(move |model| {
            *calls_inner.lock().unwrap() += 1;
            ResetModel {
                value: model.value.clone(),
                nested: Arc::new(Mutex::new(model.nested.lock().unwrap().clone())),
            }
        })
        .validator("value", |model| {
            model.value.is_empty().then(|| "required".to_string())
        })
        .reset_on_approved(|_| {
            Ok(ResetModel {
                value: String::new(),
                nested: Arc::new(Mutex::new(vec![1])),
            })
        })
        .build()
        .unwrap();
    *calls.lock().unwrap() = 0;
    let approve_command = form.approve_command();
    form.set_model(ResetModel {
        value: "saved".into(),
        nested: Arc::new(Mutex::new(vec![])),
    });
    let notifications_before_approve = approve_command.can_execute_changed().history().len();

    form.approve().unwrap();

    assert_eq!(*calls.lock().unwrap(), 2);
    assert!(!Arc::ptr_eq(&form.model().nested, &form.snapshot().nested));
    assert_eq!(form.field_error("value"), Some("required".to_string()));
    assert!(!form.is_valid());
    assert!(!approve_command.can_execute());
    assert_eq!(
        approve_command.can_execute_changed().history().len(),
        notifications_before_approve + 1
    );
}

/// FORM-026 — Post-persist reset failure is atomic and observed exactly once
#[test]
fn reset_failure_is_atomic_and_singly_observed() {
    let persisted = Arc::new(Mutex::new(0));
    let persisted_inner = persisted.clone();
    let direct = FormVm::builder()
        .initial("initial".to_string())
        .persister(move |_| {
            *persisted_inner.lock().unwrap() += 1;
            Ok(())
        })
        .reset_on_approved(|_| Err(VmxError::Other("reset failed".to_string())))
        .build()
        .unwrap();
    direct.set_model("saved".to_string());
    assert!(direct.approve().is_err());
    assert_eq!(*persisted.lock().unwrap(), 1);
    assert_eq!(direct.model(), "saved");
    assert_eq!(direct.snapshot(), "initial");
    assert!(direct.approve_errors().history().is_empty());

    let command = FormVm::builder()
        .initial("initial".to_string())
        .persister(|_| Ok(()))
        .reset_on_approved(|_| Err(VmxError::Other("reset failed".to_string())))
        .build()
        .unwrap();
    command.set_model("saved".to_string());
    command.approve_command().execute();
    assert_eq!(command.approve_errors().history().len(), 1);
}

/// FORM-027 — Reset is skipped without successful approval
#[test]
fn reset_is_skipped_without_successful_approval() {
    let calls = Arc::new(Mutex::new(0));
    let reset = {
        let calls = calls.clone();
        move |model: &i32| {
            *calls.lock().unwrap() += 1;
            Ok(*model)
        }
    };
    let invalid = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .validator("value", |model| {
            (*model == 0).then(|| "required".to_string())
        })
        .reset_on_approved(reset)
        .build()
        .unwrap();
    assert!(invalid.approve().is_err());
    let failed_calls = calls.clone();
    let failed = FormVm::builder()
        .initial(1)
        .persister(|_| Err(VmxError::Other("persist failed".to_string())))
        .reset_on_approved(move |model| {
            *failed_calls.lock().unwrap() += 1;
            Ok(*model)
        })
        .build()
        .unwrap();
    assert!(failed.approve().is_err());
    let denied_calls = calls.clone();
    let denied = FormVm::builder()
        .initial(1)
        .persister(|_| Ok(()))
        .reset_on_approved(move |model| {
            *denied_calls.lock().unwrap() += 1;
            Ok(*model)
        })
        .build()
        .unwrap();
    denied.set_model(2);
    denied.deny_command().execute();
    assert_eq!(*calls.lock().unwrap(), 0);
}

/// FORM-028 — Disposal during persistence suppresses reset and notification
#[test]
fn disposal_during_persist_suppresses_reset() {
    let entered = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let persist_entered = entered.clone();
    let persist_release = release.clone();
    let resets = Arc::new(Mutex::new(0));
    let resets_inner = resets.clone();
    let form = FormVm::builder()
        .initial(1)
        .persister(move |_| {
            persist_entered.wait();
            persist_release.wait();
            Ok(())
        })
        .reset_on_approved(move |model| {
            *resets_inner.lock().unwrap() += 1;
            Ok(*model)
        })
        .build()
        .unwrap();
    form.set_model(2);
    let worker_form = form.clone();
    let worker = std::thread::spawn(move || worker_form.approve());
    entered.wait();
    form.dispose();
    release.wait();
    worker.join().unwrap().unwrap();

    assert_eq!(*resets.lock().unwrap(), 0);
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 1);
}

/// FORM-029 — Reset is authoritative over a racing model mutation
#[test]
fn reset_wins_racing_model_mutation() {
    let entered = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let persist_entered = entered.clone();
    let persist_release = release.clone();
    let reset_inputs = Arc::new(Mutex::new(Vec::new()));
    let reset_inputs_inner = reset_inputs.clone();
    let form = FormVm::builder()
        .initial("initial".to_string())
        .persister(move |_| {
            persist_entered.wait();
            persist_release.wait();
            Ok(())
        })
        .validator("value", |model| {
            model.is_empty().then(|| "required".to_string())
        })
        .reset_on_approved(move |model| {
            reset_inputs_inner.lock().unwrap().push(model.clone());
            Ok(format!("reset:{model}"))
        })
        .build()
        .unwrap();
    let approve_command = form.approve_command();
    form.set_model("saved".to_string());
    let worker_form = form.clone();
    let worker = std::thread::spawn(move || worker_form.approve());
    entered.wait();
    form.set_model(String::new());
    release.wait();
    worker.join().unwrap().unwrap();

    assert_eq!(*reset_inputs.lock().unwrap(), vec!["saved"]);
    assert_eq!(form.model(), "reset:saved");
    assert_eq!(form.snapshot(), "reset:saved");
    assert!(!form.is_dirty());
    assert!(approve_command.can_execute());
    assert_eq!(approve_command.can_execute_changed().history().len(), 2);
}
