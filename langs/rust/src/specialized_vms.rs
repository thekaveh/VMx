//! Modal and notification presentation view models.
//!
//! Spec: `spec/19-dialogs.md` and `spec/16-notifications.md`. The
//! notification VMs need the `notifications` feature (ADR-0211).

use super::{lock, Arc, AsyncValue, Mutex};
#[cfg(feature = "notifications")]
use super::{Notification, NotificationHub, NotificationReaction, RelayCommand};

#[derive(Clone)]
/// A modal interaction with one first-wins result and a cancellation fallback.
pub struct ModalVm<T: Clone + Send + 'static> {
    cancellation_result: T,
    // One lock owns the first-wins claim and the stored result, so a reader
    // never sees a dismissed modal without its result.
    result: Arc<Mutex<Option<T>>>,
    completion: AsyncValue<T>,
}

impl<T: Clone + Send + 'static> ModalVm<T> {
    /// Creates an open, unresolved modal with the result used by cancellation and disposal.
    pub fn new(cancellation_result: T) -> Self {
        Self {
            cancellation_result,
            result: Arc::new(Mutex::new(None)),
            completion: AsyncValue::pending(),
        }
    }

    /// Has no effect, and does not reopen a dismissed modal.
    ///
    /// A modal is open from construction until its first dismissal, so there
    /// is nothing to open: a dismissed modal is never reopened and its first
    /// result stays authoritative (spec/19 §3).
    pub fn open(&self) {}

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
        lock(&self.result).is_some()
    }

    /// Accepts the first dismissal result and resolves all completion waiters.
    pub fn dismiss(&self, result: T) {
        let accepted = {
            let mut stored = lock(&self.result);
            if stored.is_some() {
                false
            } else {
                *stored = Some(result.clone());
                true
            }
        };
        if accepted {
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

/// Shared resolution and disposal state of one rendered notification.
///
/// The VM and its commands hold clones of this state. The state never holds a
/// command, so a kept command does not keep a reference cycle alive.
///
/// Lock order: the flags lock, then the hub state lock. The hub never calls
/// out while it holds its state lock, so no path takes them the other way.
#[cfg(feature = "notifications")]
#[derive(Clone)]
struct NotificationState {
    notification: Notification,
    hub: NotificationHub,
    flags: Arc<Mutex<NotificationFlags>>,
    elapsed_ms: Arc<Mutex<u64>>,
    lifespan_ms: u64,
}

#[cfg(feature = "notifications")]
#[derive(Default)]
struct NotificationFlags {
    resolved: bool,
    disposed: bool,
}

#[cfg(feature = "notifications")]
impl NotificationState {
    fn new(notification: Notification, hub: NotificationHub, lifespan_ms: u64) -> Self {
        Self {
            notification,
            hub,
            flags: Arc::new(Mutex::new(NotificationFlags::default())),
            elapsed_ms: Arc::new(Mutex::new(0)),
            lifespan_ms,
        }
    }

    /// Resolves the hub notification once with `reaction`, unless this VM
    /// already resolved it or is disposed.
    fn resolve(&self, reaction: NotificationReaction) {
        let should_resolve = {
            let mut flags = lock(&self.flags);
            if flags.resolved || flags.disposed {
                false
            } else {
                flags.resolved = true;
                true
            }
        };
        if should_resolve {
            self.hub.resolve(self.notification.id, reaction);
        }
    }

    fn is_resolved(&self) -> bool {
        // The flags lock stays held across the hub read, so no disposal can
        // complete between the `disposed` check and that read (#1293).
        let flags = lock(&self.flags);
        if flags.resolved {
            return true;
        }
        // A disposed VM no longer follows the hub, as in the other
        // flavors, where disposal releases the pending subscription.
        if flags.disposed {
            return false;
        }
        // Removal from the pending list, not the reaction, marks an external
        // resolution: a hub may resolve with `Pending` (NOTIF-015).
        self.hub.was_resolved(self.notification.id)
    }

    /// Reports whether the lifespan clock must stop: the VM is resolved or
    /// disposed.
    fn is_inert(&self) -> bool {
        // Release the flags lock before is_resolved() takes it again.
        let disposed = lock(&self.flags).disposed;
        disposed || self.is_resolved()
    }

    /// Advances the clock and returns the remaining lifespan.
    fn advance(&self, millis: u64) -> u64 {
        let mut elapsed = lock(&self.elapsed_ms);
        *elapsed = elapsed.saturating_add(millis).min(self.lifespan_ms);
        self.lifespan_ms.saturating_sub(*elapsed)
    }

    fn remaining_time_ms(&self) -> u64 {
        self.lifespan_ms.saturating_sub(*lock(&self.elapsed_ms))
    }

    /// Claims disposal once. The first claim keeps the current resolved
    /// state and returns `true`; every later claim returns `false`.
    fn claim_dispose(&self) -> bool {
        let mut flags = lock(&self.flags);
        if flags.disposed {
            return false;
        }
        // The hub read and the `disposed` write share one flags critical
        // section. A reader that saw a hub resolution therefore either ran
        // before this claim, which keeps that resolution, or it is ordered
        // after the claim and returns the kept value (#1293).
        flags.resolved |= self.hub.was_resolved(self.notification.id);
        flags.disposed = true;
        true
    }
}

#[cfg(feature = "notifications")]
#[derive(Clone)]
/// Presentation state and deterministic lifespan behavior for one notification.
///
/// Clones share one state and one dismiss command. [`dispose`](Self::dispose)
/// makes the VM and every clone of its command inert.
pub struct NotificationVm {
    state: NotificationState,
    dismiss_command: RelayCommand,
}

#[cfg(feature = "notifications")]
impl NotificationVm {
    /// Creates a notification VM with a private hub and 60-second lifespan.
    pub fn new(notification: Notification) -> Self {
        Self::with_hub(notification, NotificationHub::new(), 60_000)
    }

    /// Creates a notification VM with an explicit hub and lifespan in milliseconds.
    pub fn with_hub(notification: Notification, hub: NotificationHub, lifespan_ms: u64) -> Self {
        let state = NotificationState::new(notification, hub, lifespan_ms);
        let dismiss_command = {
            let state = state.clone();
            RelayCommand::new_shared(move || state.resolve(NotificationReaction::Approve))
        };
        Self {
            state,
            dismiss_command,
        }
    }

    /// Returns the notification being presented.
    pub fn notification(&self) -> Notification {
        self.state.notification.clone()
    }

    /// Resolves the notification as approved if it is still pending.
    ///
    /// Has no effect after [`dispose`](Self::dispose).
    pub fn dismiss(&self) {
        self.state.resolve(NotificationReaction::Approve);
    }

    /// Reports whether local or hub state has resolved the notification.
    ///
    /// After [`dispose`](Self::dispose), the VM no longer follows the hub and
    /// keeps the value it had when it was disposed.
    pub fn is_resolved(&self) -> bool {
        self.state.is_resolved()
    }

    /// Returns the remaining lifespan in milliseconds.
    pub fn remaining_time_ms(&self) -> u64 {
        self.state.remaining_time_ms()
    }

    /// Returns the linear remaining-lifetime opacity in the range `0.0..=1.0`.
    pub fn opacity(&self) -> f64 {
        if self.state.lifespan_ms == 0 {
            return 0.0;
        }
        self.remaining_time_ms() as f64 / self.state.lifespan_ms as f64
    }

    /// Advances the deterministic clock and dismisses at expiration.
    ///
    /// Has no effect once the notification is resolved or the VM is disposed.
    pub fn advance_by_ms(&self, millis: u64) {
        if self.state.is_inert() {
            return;
        }
        if self.state.advance(millis) == 0 {
            self.dismiss();
        }
    }

    /// Returns the command that dismisses this notification.
    ///
    /// Every call returns a clone of the same command, which
    /// [`dispose`](Self::dispose) disposes.
    pub fn dismiss_command(&self) -> RelayCommand {
        self.dismiss_command.clone()
    }

    /// Disposes the VM once and does not resolve the notification.
    ///
    /// The dismiss command, and every clone of it, becomes inert: its
    /// `can_execute` is `false` and `execute` no longer resolves the hub. The
    /// lifespan clock stops, and a pending notification stays pending. A
    /// first resolution stays authoritative, and a second call has no effect
    /// (`DISP-004`). Disposal never disposes the hub.
    pub fn dispose(&self) {
        if self.state.claim_dispose() {
            self.dismiss_command.dispose();
        }
    }
}

#[cfg(feature = "notifications")]
#[derive(Clone)]
/// A confirmation notification with approve and reject reactions.
///
/// Clones share one state and one set of commands.
/// [`dispose`](Self::dispose) makes the VM and every clone of its commands
/// inert.
pub struct ConfirmationVm {
    notification_vm: NotificationVm,
    approve_command: RelayCommand,
    reject_command: RelayCommand,
}

#[cfg(feature = "notifications")]
impl ConfirmationVm {
    /// Creates a confirmation with a private hub.
    pub fn new(notification: Notification) -> Self {
        Self::with_hub(notification, NotificationHub::new())
    }

    /// Creates a confirmation that resolves through `hub`.
    pub fn with_hub(notification: Notification, hub: NotificationHub) -> Self {
        let notification_vm = NotificationVm::with_hub(notification, hub, 300_000);
        let command = |reaction| {
            let state = notification_vm.state.clone();
            RelayCommand::new_shared(move || state.resolve(reaction))
        };
        let approve_command = command(NotificationReaction::Approve);
        let reject_command = command(NotificationReaction::Reject);
        Self {
            notification_vm,
            approve_command,
            reject_command,
        }
    }

    /// Resolves the confirmation with [`NotificationReaction::Approve`].
    ///
    /// Has no effect after [`dispose`](Self::dispose).
    pub fn approve(&self) {
        self.notification_vm
            .state
            .resolve(NotificationReaction::Approve);
    }

    /// Resolves the confirmation with [`NotificationReaction::Reject`].
    ///
    /// Has no effect after [`dispose`](Self::dispose).
    pub fn reject(&self) {
        self.notification_vm
            .state
            .resolve(NotificationReaction::Reject);
    }

    /// Returns the hub's current reaction for this confirmation.
    ///
    /// This reads the hub even after [`Self::dispose`], so it can report a
    /// reaction that arrived after disposal while `is_resolved()` stays frozen.
    pub fn reaction(&self) -> NotificationReaction {
        let state = &self.notification_vm.state;
        state.hub.reaction(state.notification.id)
    }

    /// Reports whether this confirmation has resolved.
    ///
    /// After [`dispose`](Self::dispose), the VM no longer follows the hub and
    /// keeps the value it had when it was disposed.
    pub fn is_resolved(&self) -> bool {
        self.notification_vm.is_resolved()
    }

    /// Returns the command that approves this confirmation.
    ///
    /// Every call returns a clone of the same command, which
    /// [`dispose`](Self::dispose) disposes.
    pub fn approve_command(&self) -> RelayCommand {
        self.approve_command.clone()
    }

    /// Returns the command that rejects this confirmation.
    ///
    /// Every call returns a clone of the same command, which
    /// [`dispose`](Self::dispose) disposes.
    pub fn reject_command(&self) -> RelayCommand {
        self.reject_command.clone()
    }

    /// Returns the confirmation being presented.
    pub fn notification(&self) -> Notification {
        self.notification_vm.notification()
    }

    /// Dismisses the confirmation, which resolves it with
    /// [`NotificationReaction::Approve`] (spec/16 §7).
    ///
    /// Has no effect after [`dispose`](Self::dispose).
    pub fn dismiss(&self) {
        self.approve();
    }

    /// Returns the inherited command that dismisses this confirmation with
    /// [`NotificationReaction::Approve`].
    ///
    /// Every call returns a clone of the same command, which
    /// [`dispose`](Self::dispose) disposes.
    pub fn dismiss_command(&self) -> RelayCommand {
        self.notification_vm.dismiss_command()
    }

    /// Returns the remaining lifespan in milliseconds.
    pub fn remaining_time_ms(&self) -> u64 {
        self.notification_vm.remaining_time_ms()
    }

    /// Returns the linear remaining-lifetime opacity in the range `0.0..=1.0`.
    pub fn opacity(&self) -> f64 {
        self.notification_vm.opacity()
    }

    /// Advances the deterministic clock. Unlike a plain notification, a
    /// confirmation stays pending when its lifespan expires (spec/16 §7).
    ///
    /// Has no effect once the confirmation is resolved or the VM is disposed.
    pub fn advance_by_ms(&self, millis: u64) {
        let state = &self.notification_vm.state;
        if state.is_inert() {
            return;
        }
        state.advance(millis);
    }

    /// Disposes the confirmation once and does not resolve it.
    ///
    /// The approve, reject and dismiss commands, and every clone of them,
    /// become inert: `can_execute` is `false` and `execute` no longer
    /// resolves the hub. A pending confirmation stays pending. A first
    /// resolution stays authoritative, and a second call has no effect
    /// (`DISP-004`). Disposal never disposes the hub.
    pub fn dispose(&self) {
        if self.notification_vm.state.claim_dispose() {
            self.notification_vm.dismiss_command.dispose();
            self.approve_command.dispose();
            self.reject_command.dispose();
        }
    }
}

#[cfg(all(test, feature = "notifications"))]
mod tests {
    use super::*;
    use crate::{Command, NotificationType};
    use std::sync::atomic::{AtomicUsize, Ordering};

    fn posted(kind: NotificationType) -> (NotificationHub, Notification) {
        let hub = NotificationHub::new();
        let notification = hub.post(kind, "message");
        (hub, notification)
    }

    #[test]
    fn notification_dispose_makes_a_kept_dismiss_command_inert() {
        let (hub, notification) = posted(NotificationType::Notification);
        let vm = NotificationVm::with_hub(notification.clone(), hub.clone(), 10_000);
        let kept = vm.dismiss_command();
        let changes = Arc::new(AtomicUsize::new(0));
        let observed = changes.clone();
        let _subscription = kept.can_execute_changed().subscribe(move |_| {
            observed.fetch_add(1, Ordering::SeqCst);
        });

        vm.dispose();
        drop(vm);
        kept.execute();

        assert!(!kept.can_execute());
        assert_eq!(changes.load(Ordering::SeqCst), 1);
        assert_eq!(hub.pending(), vec![notification.clone()]);
        assert_eq!(hub.reaction(notification.id), NotificationReaction::Pending);
    }

    #[test]
    fn notification_dispose_stops_the_clock_and_the_hub_tracking() {
        let (hub, notification) = posted(NotificationType::Notification);
        let vm = NotificationVm::with_hub(notification.clone(), hub.clone(), 10_000);
        vm.advance_by_ms(4_000);

        vm.dispose();
        vm.advance_by_ms(10_000);
        vm.dismiss();

        assert_eq!(vm.remaining_time_ms(), 6_000);
        assert!(!vm.is_resolved());
        assert_eq!(hub.reaction(notification.id), NotificationReaction::Pending);

        hub.resolve(notification.id, NotificationReaction::Reject);
        assert!(!vm.is_resolved(), "a disposed VM no longer follows the hub");
    }

    #[test]
    fn dispose_keeps_an_external_resolution_seen_before_it() {
        let (hub, notification) = posted(NotificationType::Confirmation);
        let vm = ConfirmationVm::with_hub(notification.clone(), hub.clone());
        hub.resolve(notification.id, NotificationReaction::Reject);

        vm.dispose();
        vm.dispose();

        assert!(vm.is_resolved());
        assert_eq!(vm.reaction(), NotificationReaction::Reject);
    }

    #[test]
    fn confirmation_commands_are_stable_and_clones_share_disposal() {
        let (hub, notification) = posted(NotificationType::Confirmation);
        let vm = ConfirmationVm::with_hub(notification.clone(), hub.clone());
        let commands = [
            vm.approve_command(),
            vm.reject_command(),
            vm.dismiss_command(),
            vm.clone().approve_command(),
        ];

        vm.clone().dispose();
        vm.approve();
        vm.reject();
        vm.advance_by_ms(1_000);
        for command in &commands {
            command.execute();
            assert!(!command.can_execute());
        }

        assert!(!vm.approve_command().can_execute());
        assert_eq!(vm.remaining_time_ms(), 300_000);
        assert_eq!(vm.reaction(), NotificationReaction::Pending);
        assert_eq!(hub.pending(), vec![notification]);
    }

    /// Races `dispose()`, `hub.resolve(id)` and `is_resolved()` on three
    /// threads. A passing run does not prove that the race is absent (#1293).
    fn assert_a_seen_resolution_survives_a_racing_dispose<V>(
        make: impl Fn(Notification, NotificationHub) -> V,
        dispose: fn(&V),
        is_resolved: fn(&V) -> bool,
    ) where
        V: Clone + Send + 'static,
    {
        use std::sync::Barrier;

        for iteration in 0..1_000 {
            let (hub, notification) = posted(NotificationType::Confirmation);
            let vm = make(notification.clone(), hub.clone());
            let barrier = Arc::new(Barrier::new(3));
            let disposer = {
                let (vm, barrier) = (vm.clone(), barrier.clone());
                std::thread::spawn(move || {
                    barrier.wait();
                    dispose(&vm);
                })
            };
            let resolver = {
                let barrier = barrier.clone();
                let hub = hub.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    hub.resolve(notification.id, NotificationReaction::Reject);
                })
            };
            let reader = {
                let vm = vm.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    (0..8).any(|_| is_resolved(&vm))
                })
            };
            disposer.join().unwrap();
            resolver.join().unwrap();
            let seen_resolved = reader.join().unwrap();

            if seen_resolved {
                assert!(
                    is_resolved(&vm),
                    "iteration {iteration}: is_resolved() returned true, then false"
                );
            }
        }
    }

    #[test]
    fn notification_is_resolved_never_reverts_when_dispose_races_a_hub_resolution() {
        assert_a_seen_resolution_survives_a_racing_dispose(
            |notification, hub| NotificationVm::with_hub(notification, hub, 10_000),
            NotificationVm::dispose,
            NotificationVm::is_resolved,
        );
    }

    #[test]
    fn confirmation_is_resolved_never_reverts_when_dispose_races_a_hub_resolution() {
        assert_a_seen_resolution_survives_a_racing_dispose(
            ConfirmationVm::with_hub,
            ConfirmationVm::dispose,
            ConfirmationVm::is_resolved,
        );
    }

    #[test]
    fn kept_commands_do_not_keep_the_state_in_a_cycle() {
        let (hub, notification) = posted(NotificationType::Confirmation);
        let vm = ConfirmationVm::with_hub(notification, hub);
        let flags = Arc::downgrade(&vm.notification_vm.state.flags);
        let kept = vm.reject_command();

        drop(vm);
        assert!(flags.upgrade().is_some(), "a kept command holds the state");

        drop(kept);
        assert!(
            flags.upgrade().is_none(),
            "dropping the VM and its commands releases the state"
        );
    }
}
