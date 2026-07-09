use std::sync::{Arc, Mutex};

use vmx::{
    Command, DialogService, FileFilter, ModalVm, NotificationSeverity, NullDialogService,
    RelayCommand,
};

/// DIA-001 — PickFileToOpen contract
#[test]
fn pick_file_to_open_contract_allows_optional_arguments() {
    let service = NullDialogService;

    assert_eq!(service.pick_file_to_open(None, None), None);
    assert_eq!(
        service.pick_file_to_open(
            Some(FileFilter {
                description: "Rust".to_string(),
                extensions: vec!["rs".to_string()],
            }),
            Some("Open"),
        ),
        None
    );
}

/// DIA-002 — PickFileToSave contract
#[test]
fn pick_file_to_save_contract_allows_optional_arguments() {
    let service = NullDialogService;

    assert_eq!(service.pick_file_to_save(None, None, None), None);
    assert_eq!(
        service.pick_file_to_save(None, Some("Save"), Some("vmx.rs")),
        None
    );
}

/// DIA-003 — Confirm contract
#[test]
fn confirm_contract_returns_boolean_safe_default() {
    let service = NullDialogService;

    assert!(!service.confirm("Proceed?", None));
}

/// DIA-004 — Notify contract
#[test]
fn notify_contract_accepts_default_and_explicit_severity() {
    let service = NullDialogService;

    service.notify("Info", None, NotificationSeverity::Info);
    service.notify("Warn", Some("Title"), NotificationSeverity::Warning);
    service.notify("Error", Some("Title"), NotificationSeverity::Error);
}

/// DIA-005 — NullDialogService null-object behavior
#[test]
fn null_dialog_service_returns_safe_defaults() {
    let service = NullDialogService;

    assert_eq!(service.pick_file_to_open(None, None), None);
    assert_eq!(service.pick_file_to_save(None, None, None), None);
    assert!(!service.confirm("anything", None));
    service.notify("anything", None, NotificationSeverity::Info);
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
        ) -> Option<String> {
            None
        }

        fn pick_file_to_save(
            &self,
            _filter: Option<FileFilter>,
            _title: Option<&str>,
            _suggested_name: Option<&str>,
        ) -> Option<String> {
            None
        }

        fn confirm(&self, _message: &str, _title: Option<&str>) -> bool {
            false
        }

        fn notify(&self, _message: &str, _title: Option<&str>, _severity: NotificationSeverity) {}
    }

    let service = RejectingService;

    assert!(!service.confirm("second", None));
}

/// DIA-007 — Cancellation completes with safe default, does not throw
#[test]
fn cancellation_style_defaults_are_safe() {
    let service = NullDialogService;

    assert_eq!(service.pick_file_to_open(None, None), None);
    assert!(!service.confirm("cancelled", None));
}

/// DIA-008 — ConfirmationDecoratorCommand integration
#[test]
fn confirmation_decorator_uses_dialog_confirm_gate() {
    let called = Arc::new(Mutex::new(0));
    let called_inner = called.clone();
    let inner = RelayCommand::new(move || *called_inner.lock().unwrap() += 1);

    let blocked = inner
        .clone()
        .confirm(|| NullDialogService.confirm("Proceed?", None));
    blocked.execute();
    assert_eq!(*called.lock().unwrap(), 0);

    let allowed = inner.confirm(|| true);
    allowed.execute();
    assert_eq!(*called.lock().unwrap(), 1);
}

/// DIA-009 — VM-backed modal presentation returns the modal result
#[test]
fn modal_presentation_returns_host_result() {
    let modal = ModalVm::new("cancel");

    modal.dismiss("accepted");

    assert_eq!(modal.completion(), "accepted");
    assert_eq!(modal.result(), Some("accepted"));
}

/// DIA-010 — Null modal presentation resolves with cancellation result
#[test]
fn null_modal_presentation_uses_cancellation_result() {
    let service = NullDialogService;
    let modal = ModalVm::new("cancel");

    let result = service.present(&modal);

    assert_eq!(result, "cancel");
    assert!(modal.is_dismissed());
}

/// DIA-011 — Modal disposal completes with cancellation result
#[test]
fn modal_disposal_completes_with_cancellation_result() {
    let modal = ModalVm::new("cancel");

    modal.dispose();

    assert_eq!(modal.completion(), "cancel");
    assert!(modal.is_dismissed());
}

/// DIA-012 — Modal dismissal is idempotent
#[test]
fn modal_dismissal_is_idempotent() {
    let modal = ModalVm::new("cancel");

    modal.dismiss("first");
    modal.dismiss("second");

    assert_eq!(modal.completion(), "first");
    assert_eq!(modal.result(), Some("first"));
}

/// DIA-013 — Existing dialog methods remain source-compatible
#[test]
fn null_dialog_service_exposes_existing_method_names() {
    let service = NullDialogService;

    let _ = service.pick_file_to_open(None, None);
    let _ = service.pick_file_to_save(None, None, None);
    let _ = service.confirm("Proceed?", None);
    service.notify("Done", None, NotificationSeverity::Info);
}
