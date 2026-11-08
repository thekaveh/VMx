//! `FormVm` queues updates made during approval publication and replays them
//! after the approval subscribers (spec/20 §5.1, §5.3 and §5.4, ADR-0174).
//!
//! The pre-publication window opens when the post-persist commit starts and
//! ends when the approval subscribers start. A `set_model` or deny made on the
//! approving thread inside it prepares at once, is queued, and replays as a
//! new call after the subscribers return. Rust failures are panics: a replay
//! panic does not stop the later replays, and the first one resumes from
//! `approve()` unless the approval already carries a failure (#740, #1050).

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use vmx::{ApprovalSubscription, Command, FormVm, Message, MessageHub, Subscription, VmxError};

/// Holds the form for callbacks that the builder needs before it exists.
type Slot = Arc<Mutex<Option<FormVm<i32>>>>;
type Log = Arc<Mutex<Vec<String>>>;

fn form_in(slot: &Slot) -> FormVm<i32> {
    slot.lock().unwrap().clone().expect("the form is built")
}

fn panic_message(payload: &(dyn std::any::Any + Send)) -> String {
    payload
        .downcast_ref::<String>()
        .cloned()
        .or_else(|| {
            payload
                .downcast_ref::<&str>()
                .map(|text| (*text).to_string())
        })
        .unwrap_or_default()
}

/// Records each notification of a form with the model it sees then:
/// `errors_changed`, the approve command's eligibility change, the hub's
/// `"model"` and `FormReverted` messages, and each approval.
struct Recorder {
    log: Log,
    _observers: Vec<Subscription>,
    _approved: ApprovalSubscription,
}

impl Recorder {
    fn new(form: &FormVm<i32>, hub: &MessageHub) -> Self {
        let log: Log = Arc::default();
        let errors = form.errors_changed().subscribe({
            let (form, log) = (form.clone(), Arc::clone(&log));
            move |_| log.lock().unwrap().push(format!("errors:{}", form.model()))
        });
        let can_execute = form.approve_command().can_execute_changed().subscribe({
            let (form, log) = (form.clone(), Arc::clone(&log));
            move |_| {
                log.lock()
                    .unwrap()
                    .push(format!("can_execute:{}", form.model()))
            }
        });
        let messages = hub.subscribe({
            let (form, log) = (form.clone(), Arc::clone(&log));
            move |message| {
                let entry = match message {
                    Message::PropertyChanged(change) if change.property_name == "model" => {
                        format!("model:{}", form.model())
                    }
                    Message::FormReverted(_) => format!("reverted:{}", form.model()),
                    _ => return,
                };
                log.lock().unwrap().push(entry);
            }
        });
        let approved = form.subscribe_approved({
            let (form, log) = (form.clone(), Arc::clone(&log));
            move |approved| {
                log.lock().unwrap().push(format!(
                    "approved:{approved}:{}:{}",
                    form.model(),
                    form.is_valid()
                ))
            }
        });
        Self {
            log,
            _observers: vec![errors, can_execute, messages],
            _approved: approved,
        }
    }

    fn entries(&self) -> Vec<String> {
        self.log.lock().unwrap().clone()
    }
}

/// FORM-039 — a `set_model` from `reset_on_approved` is queued: it publishes
/// nothing during the commit, the subscribers see the reset state, and it
/// replays after them with its own notifications.
#[test]
fn form_039_a_set_model_from_reset_on_approved_replays_after_the_subscribers() {
    let slot: Slot = Arc::default();
    let in_reset = Arc::new(Mutex::new(Vec::new()));
    let hub = MessageHub::new();
    let form = FormVm::builder()
        .initial(0)
        .persister(|_: &i32| Ok(()))
        .hub(hub.clone())
        .validator("value", |model: &i32| {
            (*model < 0).then(|| "negative".to_string())
        })
        .reset_on_approved({
            let (slot, in_reset) = (Arc::clone(&slot), Arc::clone(&in_reset));
            move |_| {
                let form = form_in(&slot);
                // The form rejects -1; the reset returns the pristine 0.
                form.set_model(-1);
                in_reset
                    .lock()
                    .unwrap()
                    .push((form.model(), form.is_valid()));
                Ok(0)
            }
        })
        .build()
        .unwrap();
    *slot.lock().unwrap() = Some(form.clone());
    form.set_model(2);
    let recorder = Recorder::new(&form, &hub);

    form.approve().unwrap();

    assert_eq!(
        *in_reset.lock().unwrap(),
        vec![(2, true)],
        "the queued call changes nothing while the commit runs"
    );
    assert_eq!(
        recorder.entries(),
        vec![
            "can_execute:2",
            "can_execute:0",
            "approved:2:0:true",
            "errors:-1",
            "can_execute:-1",
            "model:-1",
        ],
        "the subscribers see the reset state; the replay publishes after them"
    );
    assert_eq!(form.model(), -1);
    assert_eq!(form.snapshot(), 0);
    assert_eq!(form.field_error("value").as_deref(), Some("negative"));
    slot.lock().unwrap().take();
}

/// FORM-039 — a deny from a settlement eligibility-change observer, after an
/// edit that raced the persister, is queued. The subscribers see the edit,
/// and the revert replays after them.
#[test]
fn form_039_a_deny_from_a_settlement_observer_replays_after_the_subscribers() {
    let slot: Slot = Arc::default();
    let hub = MessageHub::new();
    let form = FormVm::builder()
        .initial(1)
        .persister({
            let slot = Arc::clone(&slot);
            // An edit that races the in-flight persistence.
            move |_: &i32| {
                form_in(&slot).set_model(5);
                Ok(())
            }
        })
        .hub(hub.clone())
        .build()
        .unwrap();
    *slot.lock().unwrap() = Some(form.clone());
    form.set_model(2);
    let recorder = Recorder::new(&form, &hub);
    let after_deny = Arc::new(Mutex::new(Vec::new()));
    let armed = Arc::new(AtomicBool::new(true));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, after_deny, armed) = (form.clone(), Arc::clone(&after_deny), Arc::clone(&armed));
        // The settlement notification runs after the snapshot advanced to 2.
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                form.deny_command().execute();
                after_deny.lock().unwrap().push(form.model());
            }
        }
    });

    form.approve().unwrap();

    assert_eq!(*after_deny.lock().unwrap(), vec![5], "the deny is queued");
    assert_eq!(
        recorder.entries(),
        vec![
            "can_execute:2",
            "model:5",
            "can_execute:5",
            "approved:2:5:true",
            "reverted:2",
            "model:2",
        ],
        "the subscribers never see the reverted model"
    );
    assert_eq!(form.model(), 2);
    assert_eq!(form.snapshot(), 2);
    slot.lock().unwrap().take();
}

/// FORM-039 — a reset that calls `set_model(7)` and then deny queues both.
/// They replay in call order after the subscribers.
#[test]
fn form_039_a_set_model_then_deny_from_the_reset_replay_in_call_order() {
    let slot: Slot = Arc::default();
    let hub = MessageHub::new();
    let form = FormVm::builder()
        .initial(0)
        .persister(|_: &i32| Ok(()))
        .hub(hub.clone())
        .reset_on_approved({
            let slot = Arc::clone(&slot);
            move |_| {
                let form = form_in(&slot);
                form.set_model(7);
                form.revert();
                Ok(0)
            }
        })
        .build()
        .unwrap();
    *slot.lock().unwrap() = Some(form.clone());
    form.set_model(3);
    let recorder = Recorder::new(&form, &hub);

    form.approve().unwrap();

    assert_eq!(
        recorder.entries(),
        vec![
            "can_execute:3",
            "can_execute:0",
            "approved:3:0:true",
            "model:7",
            "reverted:0",
            "model:0",
        ]
    );
    assert_eq!(form.model(), 0);
    assert_eq!(form.snapshot(), 0);
    slot.lock().unwrap().take();
}

/// FORM-039 — when the post-persist commit fails, the calls it queued replay
/// after the failed settlement's eligibility change and before the failure
/// reaches its channel: the `approve()` caller, or `approve_errors` once.
#[test]
fn form_039_updates_queued_by_a_failed_reset_replay_before_the_failure_is_routed() {
    for command_path in [false, true] {
        let slot: Slot = Arc::default();
        let hub = MessageHub::new();
        let form = FormVm::builder()
            .initial(0)
            .persister(|_: &i32| Ok(()))
            .hub(hub.clone())
            .reset_on_approved({
                let slot = Arc::clone(&slot);
                move |_| {
                    form_in(&slot).set_model(7);
                    Err(VmxError::Other("reset failed".to_string()))
                }
            })
            .build()
            .unwrap();
        *slot.lock().unwrap() = Some(form.clone());
        form.set_model(3);
        let recorder = Recorder::new(&form, &hub);
        let routed = Arc::new(Mutex::new(Vec::new()));
        let _errors = form.approve_errors().subscribe({
            let (form, routed) = (form.clone(), Arc::clone(&routed));
            move |_| routed.lock().unwrap().push(form.model())
        });

        if command_path {
            form.approve_command().execute();
            assert_eq!(
                *routed.lock().unwrap(),
                vec![7],
                "approve_errors receives the failure once, after the replay"
            );
        } else {
            let result = form.approve();
            assert_eq!(result, Err(VmxError::Other("reset failed".to_string())));
            assert!(routed.lock().unwrap().is_empty());
        }
        assert_eq!(
            recorder.entries(),
            vec!["can_execute:3", "can_execute:3", "model:7"],
            "the failed settlement notifies before the queued update replays"
        );
        assert_eq!(form.model(), 7);
        assert_eq!(form.snapshot(), 0);
        slot.lock().unwrap().take();
    }
}

/// The #1050 reproduction: a validator that panics for 13, and a settlement
/// eligibility-change observer that tries `set_model(13)` and then
/// `set_model(42)`. Returns the form, whether the first call panicked into
/// the observer, the model the observer saw after each call, and the
/// approvals with the model each subscriber saw.
struct Issue1050 {
    form: FormVm<i32>,
    observed: Arc<Mutex<Vec<(bool, i32, i32)>>>,
    approvals: Arc<Mutex<Vec<(i32, i32)>>>,
    _observer: Subscription,
    _approved: ApprovalSubscription,
}

fn issue_1050() -> Issue1050 {
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .validator("value", |model: &i32| {
            assert_ne!(*model, 13, "the validator rejects 13");
            None
        })
        .build()
        .unwrap();
    form.set_model(2);
    let observed = Arc::new(Mutex::new(Vec::new()));
    let armed = Arc::new(AtomicBool::new(true));
    let observer = form.approve_command().can_execute_changed().subscribe({
        let (form, observed, armed) = (form.clone(), Arc::clone(&observed), Arc::clone(&armed));
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                let failed = catch_unwind(AssertUnwindSafe(|| form.set_model(13))).is_err();
                let after_13 = form.model();
                form.set_model(42);
                observed
                    .lock()
                    .unwrap()
                    .push((failed, after_13, form.model()));
            }
        }
    });
    let approvals = Arc::new(Mutex::new(Vec::new()));
    let approved = form.subscribe_approved({
        let (form, approvals) = (form.clone(), Arc::clone(&approvals));
        move |approved| approvals.lock().unwrap().push((approved, form.model()))
    });
    Issue1050 {
        form,
        observed,
        approvals,
        _observer: observer,
        _approved: approved,
    }
}

/// FORM-040 — the #1050 reproduction: the queued `set_model(13)` prepares at
/// call time, so its validator panic reaches the observer and queues
/// nothing. The approval stays successful, and the queued 42 applies after
/// the subscribers, on the `approve()` and command paths.
#[test]
fn form_040_a_preparation_failure_reaches_the_caller_and_queues_nothing() {
    for command_path in [false, true] {
        let repro = issue_1050();
        let routed = Arc::new(Mutex::new(0usize));
        let _errors = repro.form.approve_errors().subscribe({
            let routed = Arc::clone(&routed);
            move |_| *routed.lock().unwrap() += 1
        });

        let outcome = catch_unwind(AssertUnwindSafe(|| {
            if command_path {
                repro.form.approve_command().execute();
                Ok(())
            } else {
                repro.form.approve()
            }
        }));

        assert!(
            matches!(outcome, Ok(Ok(()))),
            "the settled approval does not fail"
        );
        assert_eq!(*routed.lock().unwrap(), 0, "nothing reaches approve_errors");
        assert_eq!(
            *repro.observed.lock().unwrap(),
            vec![(true, 2, 2)],
            "the panic reaches the caller, and neither call changes the model"
        );
        assert_eq!(*repro.approvals.lock().unwrap(), vec![(2, 2)]);
        assert_eq!(repro.form.model(), 42);
        assert_eq!(repro.form.snapshot(), 2);
    }
}

/// FORM-040 — equality never skips the enqueue. With the live model 2, an
/// observer's `set_model(5)` and `set_model(2)` both prepare at call time,
/// both queue, and both replay, so the model ends at 2.
#[test]
fn form_040_a_candidate_equal_to_the_live_model_is_still_queued() {
    let validated = Arc::new(Mutex::new(Vec::new()));
    let hub = MessageHub::new();
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .hub(hub.clone())
        .validator("value", {
            let validated = Arc::clone(&validated);
            move |model: &i32| {
                validated.lock().unwrap().push(*model);
                None
            }
        })
        .build()
        .unwrap();
    form.set_model(2);
    validated.lock().unwrap().clear();
    let recorder = Recorder::new(&form, &hub);
    let in_observer = Arc::new(Mutex::new(Vec::new()));
    let armed = Arc::new(AtomicBool::new(true));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, validated, in_observer, armed) = (
            form.clone(),
            Arc::clone(&validated),
            Arc::clone(&in_observer),
            Arc::clone(&armed),
        );
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                form.set_model(5);
                form.set_model(2);
                in_observer
                    .lock()
                    .unwrap()
                    .push((validated.lock().unwrap().clone(), form.model()));
            }
        }
    });

    form.approve().unwrap();

    assert_eq!(
        *in_observer.lock().unwrap(),
        vec![(vec![5, 2], 2)],
        "both calls prepare at call time and change nothing"
    );
    assert_eq!(
        *validated.lock().unwrap(),
        vec![5, 2, 5, 2],
        "each queued call prepares again when it replays"
    );
    assert_eq!(
        recorder.entries(),
        vec![
            "can_execute:2",
            "can_execute:2",
            "approved:2:2:true",
            "model:5",
            "model:2",
        ]
    );
    assert_eq!(form.model(), 2);
}

/// A form whose validator panics for 13 and 14 once `armed` is set. A
/// settlement observer queues 13, 14 and 42 while it is clear, and an
/// approval subscriber sets it, so the first two replays panic.
struct FailingReplays {
    form: FormVm<i32>,
    approvals: Arc<Mutex<Vec<i32>>>,
    _observer: Subscription,
    _approved: ApprovalSubscription,
}

fn failing_replays(subscriber_panics: bool) -> FailingReplays {
    let armed = Arc::new(AtomicBool::new(false));
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .validator("value", {
            let armed = Arc::clone(&armed);
            move |model: &i32| {
                if armed.load(Ordering::SeqCst) && matches!(*model, 13 | 14) {
                    panic!("replay rejects {model}");
                }
                None
            }
        })
        .build()
        .unwrap();
    form.set_model(2);
    let queued = Arc::new(AtomicBool::new(false));
    let observer = form.approve_command().can_execute_changed().subscribe({
        let (form, queued) = (form.clone(), Arc::clone(&queued));
        move |_| {
            if form.snapshot() == 2 && !queued.swap(true, Ordering::SeqCst) {
                form.set_model(13);
                form.set_model(14);
                form.set_model(42);
            }
        }
    });
    let approvals = Arc::new(Mutex::new(Vec::new()));
    let approved = form.subscribe_approved({
        let approvals = Arc::clone(&approvals);
        move |approved| {
            approvals.lock().unwrap().push(approved);
            armed.store(true, Ordering::SeqCst);
            if subscriber_panics {
                panic!("subscriber failed");
            }
        }
    });
    FailingReplays {
        form,
        approvals,
        _observer: observer,
        _approved: approved,
    }
}

/// FORM-040 — a replay panic does not stop the later replays or unsettle the
/// approval. After the last replay, the first replay panic reaches the
/// failure route once: it resumes from `approve()`, or from the command's
/// `execute()`, and `approve_errors` stays empty.
#[test]
fn form_040_a_replay_failure_does_not_stop_later_replays_and_surfaces_once() {
    for command_path in [false, true] {
        let replays = failing_replays(false);
        let routed = Arc::new(Mutex::new(0usize));
        let _errors = replays.form.approve_errors().subscribe({
            let routed = Arc::clone(&routed);
            move |_| *routed.lock().unwrap() += 1
        });

        let outcome = catch_unwind(AssertUnwindSafe(|| {
            if command_path {
                replays.form.approve_command().execute();
            } else {
                replays.form.approve().unwrap();
            }
        }));

        let payload = outcome.expect_err("the first replay panic resumes");
        assert_eq!(panic_message(payload.as_ref()), "replay rejects 13");
        assert_eq!(*routed.lock().unwrap(), 0);
        assert_eq!(*replays.approvals.lock().unwrap(), vec![2], "approved once");
        assert_eq!(replays.form.model(), 42, "the last replay still applies");
        assert_eq!(replays.form.snapshot(), 2, "the approval stays settled");
        assert!(replays.form.can_approve());
    }
}

/// FORM-040 — a panicking approval subscriber wins over the replay panics,
/// and every queued update still replays.
#[test]
fn form_040_an_approval_subscriber_failure_wins_over_replay_failures() {
    let replays = failing_replays(true);

    let outcome = catch_unwind(AssertUnwindSafe(|| replays.form.approve()));

    let payload = outcome.expect_err("the subscriber panic resumes");
    assert_eq!(panic_message(payload.as_ref()), "subscriber failed");
    assert_eq!(*replays.approvals.lock().unwrap(), vec![2]);
    assert_eq!(replays.form.model(), 42);
    assert_eq!(replays.form.snapshot(), 2);
}

/// FORM-040 — a failed post-persist commit wins over a replay panic. The
/// reset queues 13 and 42 and then fails; 13 panics when it replays, 42
/// still applies, and `approve()` returns the reset's error.
#[test]
fn form_040_a_failed_commit_wins_over_replay_failures() {
    let slot: Slot = Arc::default();
    let armed = Arc::new(AtomicBool::new(false));
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .validator("value", {
            let armed = Arc::clone(&armed);
            move |model: &i32| {
                if armed.load(Ordering::SeqCst) && *model == 13 {
                    panic!("replay rejects 13");
                }
                None
            }
        })
        .reset_on_approved({
            let slot = Arc::clone(&slot);
            move |_| {
                let form = form_in(&slot);
                form.set_model(13);
                form.set_model(42);
                armed.store(true, Ordering::SeqCst);
                Err(VmxError::Other("reset failed".to_string()))
            }
        })
        .build()
        .unwrap();
    *slot.lock().unwrap() = Some(form.clone());
    form.set_model(2);
    let at_settlement = Arc::new(Mutex::new(Vec::new()));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, at_settlement) = (form.clone(), Arc::clone(&at_settlement));
        move |_| at_settlement.lock().unwrap().push(form.model())
    });

    let outcome = catch_unwind(AssertUnwindSafe(|| form.approve()));

    assert!(
        matches!(&outcome, Ok(Err(VmxError::Other(message))) if message == "reset failed"),
        "the commit failure is returned, not the replay panic"
    );
    assert_eq!(
        *at_settlement.lock().unwrap(),
        vec![2, 2],
        "nothing applies before the failed settlement notifies"
    );
    assert_eq!(form.model(), 42);
    assert_eq!(form.snapshot(), 1);
    slot.lock().unwrap().take();
}

/// FORM-040 — call-time preparation keeps the §5.4 staleness rule. A
/// validator that re-enters with `set_model(4)` while the observer's
/// `set_model(3)` prepares queues 4, and the interrupted 3 is not queued.
#[test]
fn form_040_a_nested_queued_update_makes_the_interrupted_call_stale() {
    let slot: Slot = Arc::default();
    let nested = Arc::new(AtomicBool::new(true));
    let hub = MessageHub::new();
    let form = FormVm::builder()
        .initial(1)
        .persister(|_: &i32| Ok(()))
        .hub(hub.clone())
        .validator("value", {
            let slot = Arc::clone(&slot);
            move |model: &i32| {
                let form = slot.lock().unwrap().clone();
                if let Some(form) = form {
                    if *model == 3 && form.snapshot() == 2 && nested.swap(false, Ordering::SeqCst) {
                        form.set_model(4);
                    }
                }
                None
            }
        })
        .build()
        .unwrap();
    form.set_model(2);
    *slot.lock().unwrap() = Some(form.clone());
    let recorder = Recorder::new(&form, &hub);
    let armed = Arc::new(AtomicBool::new(true));
    let _observer = form.approve_command().can_execute_changed().subscribe({
        let (form, armed) = (form.clone(), Arc::clone(&armed));
        move |_| {
            if form.snapshot() == 2 && armed.swap(false, Ordering::SeqCst) {
                form.set_model(3);
            }
        }
    });

    form.approve().unwrap();

    assert_eq!(
        recorder.entries(),
        vec![
            "can_execute:2",
            "can_execute:2",
            "approved:2:2:true",
            "model:4",
        ],
        "only the nested update replays"
    );
    assert_eq!(form.model(), 4);
    slot.lock().unwrap().take();
}
