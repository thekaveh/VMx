use std::sync::{Arc, Mutex};

use vmx::{Command, FormVm, Message, MessageHub};

/// FORM-030 — unequal assignment publishes one settled model hub message.
#[test]
fn set_model_publishes_one_settled_hub_message() {
    let trace = Arc::new(Mutex::new(Vec::<String>::new()));
    let validator_trace = trace.clone();
    let hub = MessageHub::new();
    let form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .hub(hub.clone())
        .strict(true)
        .validator("value", move |model| {
            validator_trace.lock().unwrap().push("validate".to_string());
            (*model == 0).then(|| "required".to_string())
        })
        .build()
        .unwrap();
    trace.lock().unwrap().clear();

    let errors_trace = trace.clone();
    let _errors_subscription = form.errors_changed().subscribe(move |_| {
        errors_trace.lock().unwrap().push("errors".to_string());
    });
    let approve_command = form.approve_command();
    let command_trace = trace.clone();
    let _command_subscription = approve_command.can_execute_changed().subscribe(move |_| {
        command_trace
            .lock()
            .unwrap()
            .push("can_execute".to_string());
    });

    let observed = Arc::new(Mutex::new(Vec::<(i32, bool, bool)>::new()));
    let observed_from_hub = observed.clone();
    let hub_trace = trace.clone();
    let observed_form = form.clone();
    let reentered = Arc::new(Mutex::new(false));
    let reentered_from_hub = reentered.clone();
    let _hub_subscription = hub.subscribe(move |message| {
        if !matches!(
            message,
            Message::PropertyChanged(change) if change.property_name == "model"
        ) {
            return;
        }
        observed_from_hub.lock().unwrap().push((
            observed_form.model(),
            observed_form.is_valid(),
            observed_form.can_approve(),
        ));
        hub_trace.lock().unwrap().push("model".to_string());
        let mut reentered = reentered_from_hub.lock().unwrap();
        if !*reentered {
            *reentered = true;
            drop(reentered);
            observed_form.set_model(2);
        }
    });

    form.set_model(1);

    assert_eq!(
        *observed.lock().unwrap(),
        vec![(1, true, true), (2, true, true)]
    );
    assert_eq!(
        *trace.lock().unwrap(),
        vec![
            "validate",
            "errors",
            "can_execute",
            "model",
            "validate",
            "model"
        ]
    );

    let trace_before_equal = trace.lock().unwrap().len();
    form.set_model(2);
    assert_eq!(form.model(), 2);
    assert_eq!(trace.lock().unwrap().len(), trace_before_equal);

    form.dispose();
    let trace_after_dispose = trace.lock().unwrap().len();
    form.set_model(3);
    assert_eq!(form.model(), 2);
    assert_eq!(trace.lock().unwrap().len(), trace_after_dispose);

    let null_hub_form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .build()
        .unwrap();
    null_hub_form.set_model(1);
    assert_eq!(null_hub_form.model(), 1);

    let deny_hub = MessageHub::new();
    let deny_form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .hub(deny_hub.clone())
        .build()
        .unwrap();
    deny_form.set_model(1);
    let deny_start = deny_hub.history().len();
    deny_form.deny_command().execute();
    let deny_history = deny_hub.history();
    let deny_messages = &deny_history[deny_start..];
    assert_eq!(deny_messages.len(), 2);
    assert!(matches!(deny_messages[0], Message::FormReverted(_)));
    assert!(matches!(
        deny_messages[1],
        Message::PropertyChanged(ref change) if change.property_name == "model"
    ));

    let reset_hub = MessageHub::new();
    let reset_form = FormVm::builder()
        .initial("initial".to_string())
        .persister(|_| Ok(()))
        .hub(reset_hub.clone())
        .reset_on_approved(|_| Ok("reset".to_string()))
        .build()
        .unwrap();
    reset_form.set_model("saved".to_string());
    let reset_start = reset_hub.history().len();
    reset_form.approve().unwrap();
    assert_eq!(reset_form.model(), "reset");
    assert!(!reset_hub.history()[reset_start..].iter().any(|message| {
        matches!(
            message,
            Message::PropertyChanged(change) if change.property_name == "model"
        )
    }));
}
