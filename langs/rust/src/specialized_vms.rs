//! Modal and notification presentation view models.
//!
//! Spec: `spec/17-dialogs.md` and `spec/18-notifications.md`.

use super::{
    lock, Arc, AsyncValue, Mutex, Notification, NotificationHub, NotificationReaction, RelayCommand,
};

#[derive(Clone)]
/// A modal interaction with one first-wins result and a cancellation fallback.
pub struct ModalVm<T: Clone + Send + 'static> {
    cancellation_result: T,
    result: Arc<Mutex<Option<T>>>,
    dismissed: Arc<Mutex<bool>>,
    completion: AsyncValue<T>,
}

impl<T: Clone + Send + 'static> ModalVm<T> {
    /// Creates a closed modal with the result used by cancellation and disposal.
    pub fn new(cancellation_result: T) -> Self {
        Self {
            cancellation_result,
            result: Arc::new(Mutex::new(None)),
            dismissed: Arc::new(Mutex::new(false)),
            completion: AsyncValue::pending(),
        }
    }

    /// Marks the modal as open for presentation.
    pub fn open(&self) {
        *lock(&self.dismissed) = false;
    }

    /// Closes the modal with `result` or the configured cancellation result.
    pub fn close(&self, result: Option<T>) {
        self.dismiss(result.unwrap_or_else(|| self.cancellation_result.clone()));
    }

    /// Returns the first accepted dismissal result, when available.
    pub fn result(&self) -> Option<T> {
        lock(&self.result).clone()
    }

    /// Returns the result used for cancellation-style dismissal.
    pub fn cancellation_result(&self) -> T {
        self.cancellation_result.clone()
    }

    /// Reports whether a result has been accepted.
    pub fn is_dismissed(&self) -> bool {
        *lock(&self.dismissed)
    }

    /// Accepts the first dismissal result and resolves all completion waiters.
    pub fn dismiss(&self, result: T) {
        let should_set = {
            let mut dismissed = lock(&self.dismissed);
            if *dismissed {
                false
            } else {
                *dismissed = true;
                true
            }
        };
        if should_set {
            *lock(&self.result) = Some(result.clone());
            self.completion.resolve(result);
        }
    }

    /// Dismisses with the cancellation result if still pending.
    pub fn dispose(&self) {
        self.dismiss(self.cancellation_result.clone());
    }

    /// Returns a cloneable completion handle for the modal result.
    pub fn completion(&self) -> AsyncValue<T> {
        self.completion.clone()
    }
}

#[derive(Clone)]
/// Presentation state and deterministic lifespan behavior for one notification.
pub struct NotificationVm {
    notification: Notification,
    hub: NotificationHub,
    resolved: Arc<Mutex<bool>>,
    elapsed_ms: Arc<Mutex<u64>>,
    lifespan_ms: u64,
}

impl NotificationVm {
    /// Creates a notification VM with a private hub and 60-second lifespan.
    pub fn new(notification: Notification) -> Self {
        Self::with_hub(notification, NotificationHub::new(), 60_000)
    }

    /// Creates a notification VM with an explicit hub and lifespan in milliseconds.
    pub fn with_hub(notification: Notification, hub: NotificationHub, lifespan_ms: u64) -> Self {
        Self {
            notification,
            hub,
            resolved: Arc::new(Mutex::new(false)),
            elapsed_ms: Arc::new(Mutex::new(0)),
            lifespan_ms,
        }
    }

    /// Returns the notification being presented.
    pub fn notification(&self) -> Notification {
        self.notification.clone()
    }

    /// Resolves the notification as approved if it is still pending.
    pub fn dismiss(&self) {
        let should_resolve = {
            let mut resolved = lock(&self.resolved);
            if *resolved {
                false
            } else {
                *resolved = true;
                true
            }
        };
        if should_resolve {
            self.hub
                .resolve(self.notification.id, NotificationReaction::Approve);
        }
    }

    /// Reports whether local or hub state has resolved the notification.
    pub fn is_resolved(&self) -> bool {
        *lock(&self.resolved)
            || self.hub.reaction(self.notification.id) != NotificationReaction::Pending
    }

    /// Returns the remaining lifespan in milliseconds.
    pub fn remaining_time_ms(&self) -> u64 {
        self.lifespan_ms.saturating_sub(*lock(&self.elapsed_ms))
    }

    /// Returns the linear remaining-lifetime opacity in the range `0.0..=1.0`.
    pub fn opacity(&self) -> f64 {
        if self.lifespan_ms == 0 {
            return 0.0;
        }
        self.remaining_time_ms() as f64 / self.lifespan_ms as f64
    }

    /// Advances the deterministic clock and dismisses at expiration.
    pub fn advance_by_ms(&self, millis: u64) {
        if self.is_resolved() {
            return;
        }
        let remaining = {
            let mut elapsed = lock(&self.elapsed_ms);
            *elapsed = (*elapsed + millis).min(self.lifespan_ms);
            self.lifespan_ms.saturating_sub(*elapsed)
        };
        if remaining == 0 {
            self.dismiss();
        }
    }

    /// Creates a command that dismisses this notification.
    pub fn dismiss_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new(move || vm.dismiss())
    }
}

#[derive(Clone)]
/// A confirmation notification with approve and reject reactions.
pub struct ConfirmationVm {
    notification_vm: NotificationVm,
}

impl ConfirmationVm {
    /// Creates a confirmation with a private hub.
    pub fn new(notification: Notification) -> Self {
        Self::with_hub(notification, NotificationHub::new())
    }

    /// Creates a confirmation that resolves through `hub`.
    pub fn with_hub(notification: Notification, hub: NotificationHub) -> Self {
        Self {
            notification_vm: NotificationVm::with_hub(notification, hub, 300_000),
        }
    }

    /// Resolves the confirmation with [`NotificationReaction::Approve`].
    pub fn approve(&self) {
        self.resolve(NotificationReaction::Approve);
    }

    /// Resolves the confirmation with [`NotificationReaction::Reject`].
    pub fn reject(&self) {
        self.resolve(NotificationReaction::Reject);
    }

    /// Returns the hub's current reaction for this confirmation.
    pub fn reaction(&self) -> NotificationReaction {
        self.notification_vm
            .hub
            .reaction(self.notification_vm.notification.id)
    }

    /// Reports whether this confirmation has resolved.
    pub fn is_resolved(&self) -> bool {
        self.notification_vm.is_resolved()
    }

    /// Creates a command that approves this confirmation.
    pub fn approve_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new(move || vm.approve())
    }

    /// Creates a command that rejects this confirmation.
    pub fn reject_command(&self) -> RelayCommand {
        let vm = self.clone();
        RelayCommand::new(move || vm.reject())
    }

    fn resolve(&self, reaction: NotificationReaction) {
        let should_resolve = {
            let mut resolved = lock(&self.notification_vm.resolved);
            if *resolved {
                false
            } else {
                *resolved = true;
                true
            }
        };
        if should_resolve {
            self.notification_vm
                .hub
                .resolve(self.notification_vm.notification.id, reaction);
        }
    }
}
