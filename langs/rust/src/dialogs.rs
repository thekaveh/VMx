//! Localization and host dialog-service contracts.
//!
//! Spec: `spec/16-localization.md` and `spec/17-dialogs.md`.

use super::*;

/// Resolves localization keys to user-facing strings.
pub trait Localizer: Send + Sync {
    /// Returns the localized value for `key`.
    fn localize(&self, key: &str) -> String;
}

#[derive(Debug, Clone, Copy, Default)]
/// Null localizer that returns each key unchanged.
pub struct NullLocalizer;

impl Localizer for NullLocalizer {
    fn localize(&self, key: &str) -> String {
        key.to_string()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// A display label and extension list for file-picker filtering.
pub struct FileFilter {
    /// User-facing filter description.
    pub description: String,
    /// Accepted filename extensions without host-specific wildcard syntax.
    pub extensions: Vec<String>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
/// Severity used by host notification dialogs.
pub enum NotificationSeverity {
    #[default]
    /// Informational severity.
    Info,
    /// Warning severity.
    Warning,
    /// Error severity.
    Error,
}

/// Asynchronous host boundary for files, confirmation, and notifications.
pub trait DialogService: Send + Sync {
    /// Requests a file to open, returning `None` on cancellation.
    fn pick_file_to_open(
        &self,
        filter: Option<FileFilter>,
        title: Option<&str>,
    ) -> AsyncValue<Option<String>>;
    /// Requests a file destination, returning `None` on cancellation.
    fn pick_file_to_save(
        &self,
        filter: Option<FileFilter>,
        title: Option<&str>,
        suggested_name: Option<&str>,
    ) -> AsyncValue<Option<String>>;
    /// Requests a boolean confirmation with a safe `false` cancellation value.
    fn confirm(&self, message: &str, title: Option<&str>) -> AsyncValue<bool>;
    /// Presents a host notification and completes when accepted by the host.
    fn notify(
        &self,
        message: &str,
        title: Option<&str>,
        severity: NotificationSeverity,
    ) -> AsyncValue<()>;
}

#[derive(Debug, Clone, Copy, Default)]
/// Null dialog service that returns safe completed defaults.
pub struct NullDialogService;

impl DialogService for NullDialogService {
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

impl NullDialogService {
    /// Cancels `modal` and returns its completion handle.
    pub fn present<T: Clone + Send + 'static>(&self, modal: &ModalVm<T>) -> AsyncValue<T> {
        modal.dispose();
        modal.completion()
    }
}
