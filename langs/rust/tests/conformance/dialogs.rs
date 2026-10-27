use std::sync::{Arc, Mutex};

use vmx::{
    AsyncValue, Command, DialogService, FileFilter, ModalVm, NotificationSeverity,
    NullDialogService, RelayCommand,
};

/// DIA-001 — PickFileToOpen contract
#[test]
fn pick_file_to_open_contract_allows_optional_arguments() {
    let service = NullDialogService;

    assert_eq!(service.pick_file_to_open(None, None).wait(), None);
    assert_eq!(
        service
            .pick_file_to_open(
                Some(FileFilter {
                    description: "Rust".to_string(),
                    extensions: vec!["rs".to_string()],
                }),
                Some("Open"),
            )
            .wait(),
        None
    );
}

/// DIA-002 — PickFileToSave contract
#[test]
fn pick_file_to_save_contract_allows_optional_arguments() {
    let service = NullDialogService;

    assert_eq!(service.pick_file_to_save(None, None, None).wait(), None);
    assert_eq!(
        service
            .pick_file_to_save(None, Some("Save"), Some("vmx.rs"))
            .wait(),
        None
    );
}

/// DIA-003 — Confirm contract
#[test]
fn confirm_contract_returns_boolean_safe_default() {
    let service = NullDialogService;

    assert!(!service.confirm("Proceed?", None).wait());
}

/// DIA-004 — Notify contract
#[test]
fn notify_contract_accepts_default_and_explicit_severity() {
    let service = NullDialogService;

    service
        .notify("Info", None, NotificationSeverity::Info)
        .wait();
    service
        .notify("Warn", Some("Title"), NotificationSeverity::Warning)
        .wait();
    service
        .notify("Error", Some("Title"), NotificationSeverity::Error)
        .wait();
}

/// DIA-005 — NullDialogService null-object behavior
#[test]
fn null_dialog_service_returns_safe_defaults() {
    let service = NullDialogService;

    assert_eq!(service.pick_file_to_open(None, None).wait(), None);
    assert_eq!(service.pick_file_to_save(None, None, None).wait(), None);
    assert!(!service.confirm("anything", None).wait());
    service
        .notify("anything", None, NotificationSeverity::Info)
        .wait();
}

/// DIA-006 — Reentrancy is implementation-defined
#[test]
fn immediate_rejecting_reentrant_service_returns_safe_default() {
    #[derive(Clone, Default)]
    struct RejectingService;

    impl DialogService for RejectingService {
        fn pick_file_to_open(
            &self,
            _filter: Option<FileFilter>,
            _title: Option<&str>,
        ) -> AsyncValue<Option<String>> {
            AsyncValue::ready(None)
        }

        fn pick_file_to_save(
            &self,
            _filter: Option<FileFilter>,
            _title: Option<&str>,
            _suggested_name: Option<&str>,
        ) -> AsyncValue<Option<String>> {
            AsyncValue::ready(None)
        }

        fn confirm(&self, _message: &str, _title: Option<&str>) -> AsyncValue<bool> {
            AsyncValue::ready(false)
        }

        fn notify(
            &self,
            _message: &str,
            _title: Option<&str>,
            _severity: NotificationSeverity,
        ) -> AsyncValue<()> {
            AsyncValue::ready(())
        }
    }

    let service = RejectingService;

    assert!(!service.confirm("second", None).wait());
}

/// Dialog service whose `confirm` either rejects reentrant calls immediately
/// (`queueing == false`) or serialises them behind the pending one.
#[derive(Clone)]
struct ReentrantConfirmService {
    queueing: bool,
    pending: Arc<Mutex<Vec<AsyncValue<bool>>>>,
}

impl ReentrantConfirmService {
    fn new(queueing: bool) -> Self {
        Self {
            queueing,
            pending: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Host resolves the oldest outstanding dialog.
    fn resolve_next(&self, value: bool) {
        let next = self.pending.lock().unwrap().remove(0);
        assert!(next.resolve(value));
    }
}

impl DialogService for ReentrantConfirmService {
    fn pick_file_to_open(
        &self,
        _filter: Option<FileFilter>,
        _title: Option<&str>,
    ) -> AsyncValue<Option<String>> {
        AsyncValue::ready(None)
    }

    fn pick_file_to_save(
        &self,
        _filter: Option<FileFilter>,
        _title: Option<&str>,
        _suggested_name: Option<&str>,
    ) -> AsyncValue<Option<String>> {
        AsyncValue::ready(None)
    }

    fn confirm(&self, _message: &str, _title: Option<&str>) -> AsyncValue<bool> {
        let mut pending = self.pending.lock().unwrap();
        if !self.queueing && !pending.is_empty() {
            return AsyncValue::ready(false);
        }
        let decision = AsyncValue::pending();
        pending.push(decision.clone());
        decision
    }

    fn notify(
        &self,
        _message: &str,
        _title: Option<&str>,
        _severity: NotificationSeverity,
    ) -> AsyncValue<()> {
        AsyncValue::ready(())
    }
}

/// DIA-006 — an immediate-rejecting service resolves a second `confirm` made
/// while the first is pending with `false` at once, and the first call
/// continues to completion unaffected.
#[test]
fn immediate_rejecting_service_rejects_second_while_first_pending() {
    let service = ReentrantConfirmService::new(false);
    let first = service.confirm("first", None);
    assert_eq!(first.try_get(), None);

    let second = service.confirm("second", None);
    assert_eq!(second.try_get(), Some(false));
    assert_eq!(first.try_get(), None);

    service.resolve_next(true);
    assert!(first.wait());
}

/// DIA-006 — a queueing service serialises concurrent `confirm` calls and
/// both eventually resolve with valid values without raising.
#[test]
fn queueing_service_serialises_concurrent_confirms() {
    let service = ReentrantConfirmService::new(true);
    let callers = (0..2)
        .map(|index| {
            let service = service.clone();
            std::thread::spawn(move || service.confirm(&format!("call-{index}"), None).wait())
        })
        .collect::<Vec<_>>();
    while service.pending.lock().unwrap().len() < 2 {
        std::thread::yield_now();
    }
    service.resolve_next(true);
    service.resolve_next(false);
    let mut results = callers
        .into_iter()
        .map(|caller| caller.join().expect("confirm must not panic"))
        .collect::<Vec<_>>();
    results.sort_unstable();
    assert_eq!(results, vec![false, true]);
}

#[test]
fn dialog_contract_can_remain_pending_until_host_resolution() {
    #[derive(Clone)]
    struct PendingService {
        decision: AsyncValue<bool>,
    }

    impl DialogService for PendingService {
        fn pick_file_to_open(
            &self,
            _filter: Option<FileFilter>,
            _title: Option<&str>,
        ) -> AsyncValue<Option<String>> {
            AsyncValue::ready(None)
        }

        fn pick_file_to_save(
            &self,
            _filter: Option<FileFilter>,
            _title: Option<&str>,
            _suggested_name: Option<&str>,
        ) -> AsyncValue<Option<String>> {
            AsyncValue::ready(None)
        }

        fn confirm(&self, _message: &str, _title: Option<&str>) -> AsyncValue<bool> {
            self.decision.clone()
        }

        fn notify(
            &self,
            _message: &str,
            _title: Option<&str>,
            _severity: NotificationSeverity,
        ) -> AsyncValue<()> {
            AsyncValue::ready(())
        }
    }

    let decision = AsyncValue::pending();
    let service = PendingService {
        decision: decision.clone(),
    };
    let confirmation = service.confirm("Proceed?", None);
    assert_eq!(confirmation.try_get(), None);
    decision.resolve(true);
    assert!(confirmation.wait());
}

/// DIA-007 — Cancellation completes with safe default, does not throw
#[test]
fn cancellation_style_defaults_are_safe() {
    let service = NullDialogService;

    assert_eq!(service.pick_file_to_open(None, None).wait(), None);
    assert!(!service.confirm("cancelled", None).wait());
}

/// DIA-008 — ConfirmationDecoratorCommand integration
///
/// Rust has no `confirm(dialog_service, message)` overload; the delegate form
/// `inner.confirm(|| dialog.confirm("Proceed?", None))` is the integration.
#[test]
fn confirmation_decorator_uses_dialog_confirm_gate() {
    struct ScriptedDialog {
        prompts: Mutex<Vec<String>>,
        decision: Mutex<Option<AsyncValue<bool>>>,
    }

    impl DialogService for ScriptedDialog {
        fn pick_file_to_open(
            &self,
            _filter: Option<FileFilter>,
            _title: Option<&str>,
        ) -> AsyncValue<Option<String>> {
            AsyncValue::ready(None)
        }

        fn pick_file_to_save(
            &self,
            _filter: Option<FileFilter>,
            _title: Option<&str>,
            _suggested_name: Option<&str>,
        ) -> AsyncValue<Option<String>> {
            AsyncValue::ready(None)
        }

        fn confirm(&self, message: &str, _title: Option<&str>) -> AsyncValue<bool> {
            self.prompts.lock().unwrap().push(message.to_string());
            let decision = AsyncValue::pending();
            *self.decision.lock().unwrap() = Some(decision.clone());
            decision
        }

        fn notify(
            &self,
            _message: &str,
            _title: Option<&str>,
            _severity: NotificationSeverity,
        ) -> AsyncValue<()> {
            AsyncValue::ready(())
        }
    }

    let called = Arc::new(Mutex::new(0));
    let called_inner = called.clone();
    let enabled = Arc::new(Mutex::new(true));
    let enabled_inner = enabled.clone();
    let inner = RelayCommand::new(move || *called_inner.lock().unwrap() += 1)
        .with_can_execute(move || *enabled_inner.lock().unwrap());
    let dialog = Arc::new(ScriptedDialog {
        prompts: Mutex::new(Vec::new()),
        decision: Mutex::new(None),
    });
    let service = dialog.clone();
    let confirmed = inner.confirm(move || service.confirm("Proceed?", None));

    // CanExecute delegates to the inner command.
    assert!(confirmed.can_execute());
    *enabled.lock().unwrap() = false;
    assert!(!confirmed.can_execute());
    *enabled.lock().unwrap() = true;
    assert!(confirmed.can_execute());

    for (answer, expected_calls) in [(true, 1), (false, 1), (true, 2)] {
        let execution = confirmed.execute_async();
        // Execute first awaits the dialog's Confirm result.
        assert_eq!(
            *called.lock().unwrap(),
            expected_calls - usize::from(answer)
        );
        let decision = dialog
            .decision
            .lock()
            .unwrap()
            .take()
            .expect("dialog asked");
        decision.resolve(answer);
        execution.join().unwrap();
        assert_eq!(*called.lock().unwrap(), expected_calls, "answer = {answer}");
    }
    assert_eq!(
        *dialog.prompts.lock().unwrap(),
        vec!["Proceed?", "Proceed?", "Proceed?"]
    );

    // The null dialog's safe `false` never runs the inner command.
    let blocked_calls = Arc::new(Mutex::new(0));
    let blocked_inner = blocked_calls.clone();
    let blocked = RelayCommand::new(move || *blocked_inner.lock().unwrap() += 1)
        .confirm(|| NullDialogService.confirm("Proceed?", None));
    blocked.execute();
    assert_eq!(*blocked_calls.lock().unwrap(), 0);
}

/// DIA-009 — VM-backed modal presentation returns the modal result
#[test]
fn modal_presentation_returns_host_result() {
    let modal = ModalVm::new("cancel");
    let completion = modal.completion();

    assert_eq!(completion.try_get(), None);

    modal.dismiss("accepted");

    assert_eq!(completion.wait(), "accepted");
    assert_eq!(modal.result(), Some("accepted"));
}

/// DIA-010 — Null modal presentation resolves with cancellation result
#[test]
fn null_modal_presentation_uses_cancellation_result() {
    let service = NullDialogService;
    let modal = ModalVm::new("cancel");

    let result = service.present(&modal);

    assert_eq!(result.wait(), "cancel");
    assert!(modal.is_dismissed());
}

/// DIA-010 — Null modal presentation keeps an already-dismissed modal's result
#[test]
fn null_modal_presentation_keeps_an_earlier_result() {
    let service = NullDialogService;
    let modal = ModalVm::new("cancel");
    modal.dismiss("chosen");

    let result = service.present(&modal);

    assert_eq!(result.wait(), "chosen");
    assert_eq!(modal.result(), Some("chosen"));
}

/// DIA-011 — Modal disposal completes with cancellation result
#[test]
fn modal_disposal_completes_with_cancellation_result() {
    let modal = ModalVm::new("cancel");

    modal.dispose();

    assert_eq!(modal.completion().wait(), "cancel");
    assert!(modal.is_dismissed());
}

/// DIA-012 — Modal dismissal is idempotent
#[test]
fn modal_dismissal_is_idempotent() {
    let modal = ModalVm::new("cancel");

    modal.dismiss("first");
    modal.dismiss("second");

    assert_eq!(modal.completion().wait(), "first");
    assert_eq!(modal.result(), Some("first"));
}

/// DIA-012 — Reopening a dismissed modal cannot replace its first result
#[test]
fn reopening_a_dismissed_modal_keeps_the_first_result() {
    let modal = ModalVm::new("cancel");

    modal.dismiss("first");
    modal.open();
    modal.dismiss("second");

    assert!(modal.is_dismissed());
    assert_eq!(modal.completion().wait(), "first");
    assert_eq!(modal.result(), Some("first"));
}

/// DIA-012 — A dismissed modal always reports its stored result
#[test]
fn a_dismissed_modal_always_reports_its_result() {
    for _ in 0..200 {
        let modal = ModalVm::new("cancel");
        let dismisser = {
            let modal = modal.clone();
            std::thread::spawn(move || modal.dismiss("done"))
        };
        loop {
            if modal.is_dismissed() {
                assert_eq!(modal.result(), Some("done"));
                break;
            }
            std::hint::spin_loop();
        }
        dismisser.join().unwrap();
    }
}

/// DIA-013 — Existing dialog methods remain source-compatible
#[test]
fn null_dialog_service_exposes_existing_method_names() {
    let service = NullDialogService;

    drop(service.pick_file_to_open(None, None));
    drop(service.pick_file_to_save(None, None, None));
    drop(service.confirm("Proceed?", None));
    service
        .notify("Done", None, NotificationSeverity::Info)
        .wait();
}
