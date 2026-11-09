//! Localization and host dialog-service contracts.
//!
//! Spec: `spec/17-localization.md` and `spec/19-dialogs.md`.

use super::{AsyncValue, ModalVm};
use std::fmt::Display;

/// Resolves localization keys to user-facing strings.
///
/// ```
/// use std::fmt::Display;
/// use vmx::Localizer;
///
/// struct Greeting;
///
/// impl Localizer for Greeting {
///     fn localize(&self, key: &str) -> String {
///         key.to_string()
///     }
///
///     fn localize_with_args(&self, key: &str, args: &[&dyn Display]) -> String {
///         let mut text = self.localize(key);
///         for (index, arg) in args.iter().enumerate() {
///             text = text.replace(&format!("{{{index}}}"), &arg.to_string());
///         }
///         text
///     }
/// }
///
/// assert_eq!(Greeting.localize_with_args("Hello, {0}!", &[&"Ada"]), "Hello, Ada!");
/// ```
pub trait Localizer: Send + Sync {
    /// Returns the localized value for `key`.
    fn localize(&self, key: &str) -> String;

    /// Returns the localized value for `key`, formatted with the positional
    /// `args` (spec/17 §1 `Localize(key, args)`).
    ///
    /// The default implementation ignores `args` and returns
    /// [`localize(key)`](Self::localize), so [`NullLocalizer`] returns `key`
    /// unchanged. An implementation that formats overrides this method.
    fn localize_with_args(&self, key: &str, args: &[&dyn Display]) -> String {
        let _ = args;
        self.localize(key)
    }
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

/// Asynchronous host boundary for files, confirmation, notifications, and
/// VM-backed modals.
///
/// [`present`](Self::present) is a provided generic method with a
/// `where Self: Sized` bound (ADR-0210). An implementation that presents no
/// modals needs no `present` of its own, and the trait stays dyn-compatible:
/// `Box<dyn DialogService>` and `Arc<dyn DialogService>` keep working for the
/// other four methods. `present` cannot be called through `dyn DialogService`;
/// code that presents modals holds a concrete or generic service type.
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

    /// Presents a VM-backed modal and returns its typed result (spec/19
    /// §2.1 and §3).
    ///
    /// A host service overrides this method to show `modal` and dismiss it
    /// with the user's choice. The default keeps null-object safety, as in
    /// Python and Swift: it dismisses `modal` with its cancellation result.
    /// The first result wins, so an already-dismissed modal keeps its result.
    ///
    /// ```
    /// use vmx::{
    ///     AsyncValue, DialogService, FileFilter, ModalVm, NotificationSeverity,
    /// };
    ///
    /// struct Host;
    ///
    /// impl DialogService for Host {
    ///     fn pick_file_to_open(&self, _: Option<FileFilter>, _: Option<&str>) -> AsyncValue<Option<String>> {
    ///         AsyncValue::ready(None)
    ///     }
    ///     fn pick_file_to_save(
    ///         &self,
    ///         _: Option<FileFilter>,
    ///         _: Option<&str>,
    ///         _: Option<&str>,
    ///     ) -> AsyncValue<Option<String>> {
    ///         AsyncValue::ready(None)
    ///     }
    ///     fn confirm(&self, _: &str, _: Option<&str>) -> AsyncValue<bool> {
    ///         AsyncValue::ready(false)
    ///     }
    ///     fn notify(&self, _: &str, _: Option<&str>, _: NotificationSeverity) -> AsyncValue<()> {
    ///         AsyncValue::ready(())
    ///     }
    /// }
    ///
    /// // `Host` does not override `present`, so it cancels the modal.
    /// let modal = ModalVm::new("cancel");
    /// assert_eq!(Host.present(&modal).wait(), "cancel");
    /// ```
    fn present<T: Clone + Send + 'static>(&self, modal: &ModalVm<T>) -> AsyncValue<T>
    where
        Self: Sized,
    {
        // First result wins: an already-dismissed modal keeps its result.
        modal.dispose();
        modal.completion()
    }
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
    ///
    /// Kept so a call without the [`DialogService`] trait in scope still
    /// compiles; it runs the trait's default
    /// [`present`](DialogService::present).
    pub fn present<T: Clone + Send + 'static>(&self, modal: &ModalVm<T>) -> AsyncValue<T> {
        <Self as DialogService>::present(self, modal)
    }
}
