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
    let deny_recorder = deny_hub.record(1024);
    let deny_form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .hub(deny_hub.clone())
        .build()
        .unwrap();
    deny_form.set_model(1);
    let deny_start = deny_recorder.messages().len();
    deny_form.deny_command().execute();
    let deny_history = deny_recorder.messages();
    let deny_messages = &deny_history[deny_start..];
    assert_eq!(deny_messages.len(), 2);
    assert!(matches!(deny_messages[0], Message::FormReverted(_)));
    assert!(matches!(
        deny_messages[1],
        Message::PropertyChanged(ref change) if change.property_name == "model"
    ));

    let reset_hub = MessageHub::new();
    let reset_recorder = reset_hub.record(1024);
    let reset_form = FormVm::builder()
        .initial("initial".to_string())
        .persister(|_| Ok(()))
        .hub(reset_hub.clone())
        .reset_on_approved(|_| Ok("reset".to_string()))
        .build()
        .unwrap();
    reset_form.set_model("saved".to_string());
    let reset_start = reset_recorder.messages().len();
    reset_form.approve().unwrap();
    assert_eq!(reset_form.model(), "reset");
    assert!(!reset_recorder.messages()[reset_start..]
        .iter()
        .any(|message| {
            matches!(
                message,
                Message::PropertyChanged(change) if change.property_name == "model"
            )
        }));
}

/// FORM-030 — disposing a form publishes nothing on its hub. The hub carries
/// only the spec/20 §8 messages (model `PropertyChanged` and `FormReverted`),
/// so the wrapped component's `ConstructionStatusChanged(Disposed)` stays off
/// it, as in C#, Python, TypeScript, and Swift.
#[test]
fn dispose_publishes_no_lifecycle_message_on_form_hub() {
    for with_builder in [true, false] {
        let hub = MessageHub::new();
        let form = if with_builder {
            FormVm::builder()
                .initial(0)
                .persister(|_| Ok(()))
                .hub(hub.clone())
                .build()
                .unwrap()
        } else {
            FormVm::with_options("Form", 0, |_| Ok(()), false, hub.clone())
        };
        let messages = Arc::new(Mutex::new(Vec::<Message>::new()));
        let recorded = messages.clone();
        let _subscription = hub.subscribe(move |message| {
            recorded.lock().unwrap().push(message.clone());
        });

        form.set_model(1);
        form.deny_command().execute();
        form.dispose();
        form.set_model(2);

        let messages = messages.lock().unwrap();
        assert!(
            messages.iter().all(|message| matches!(
                message,
                Message::PropertyChanged(change) if change.property_name == "model"
            ) || matches!(message, Message::FormReverted(_))),
            "form hub carried a non-§8 message: {messages:?}"
        );
        assert!(
            !messages
                .iter()
                .any(|message| matches!(message, Message::ConstructionStatusChanged(_))),
            "dispose published a lifecycle message on the form hub"
        );
        assert_eq!(messages.len(), 3, "{messages:?}");
    }
}
