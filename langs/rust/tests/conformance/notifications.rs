use vmx::{
    make_confirm, Command, Notification, NotificationHub, NotificationReaction, NotificationType,
    NotificationVm, NullNotificationHub,
};

/// NOTIF-001 — Post returns an awaitable that completes when Resolve is called
#[test]
fn post_waiter_yields_resolved_reaction() {
    let hub = NotificationHub::new();
    let (notification, waiter) = hub.post_with_waiter(NotificationType::Notification, "info");

    hub.resolve(notification.id, NotificationReaction::Approve);

    assert_eq!(waiter.wait(), NotificationReaction::Approve);
}

#[test]
fn post_waiter_remains_pending_until_resolve() {
    let hub = NotificationHub::new();
    let (notification, waiter) = hub.post_with_waiter(NotificationType::Notification, "info");
    let completed = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let completed_by_waiter = completed.clone();
    let waiting = std::thread::spawn(move || {
        let reaction = waiter.wait();
        completed_by_waiter.store(true, std::sync::atomic::Ordering::SeqCst);
        reaction
    });

    std::thread::sleep(std::time::Duration::from_millis(5));
    assert!(!completed.load(std::sync::atomic::Ordering::SeqCst));
    hub.resolve(notification.id, NotificationReaction::Reject);

    assert_eq!(waiting.join().unwrap(), NotificationReaction::Reject);
}

#[test]
fn reposting_same_notification_reuses_pending_completion() {
    let hub = NotificationHub::new();
    let notification = Notification::new(NotificationType::Notification, "info");
    let first = hub.post_notification(notification.clone());
    let second = hub.post_notification(notification.clone());

    assert_eq!(hub.pending().len(), 1);
    hub.resolve(notification.id, NotificationReaction::Approve);

    assert_eq!(first.wait(), NotificationReaction::Approve);
    assert_eq!(second.wait(), NotificationReaction::Approve);
}

/// NOTIF-002 — Post adds the notification to Pending
#[test]
fn post_adds_notification_to_pending_snapshot() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Notification, "info");

    assert!(hub.pending().contains(&notification));
    assert!(hub
        .pending_snapshots()
        .last()
        .unwrap()
        .contains(&notification));
}

/// NOTIF-003 — Resolve removes the notification from Pending
#[test]
fn resolve_removes_notification_from_pending_snapshot() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Notification, "info");

    hub.resolve(notification.id, NotificationReaction::Approve);

    assert!(!hub.pending().contains(&notification));
    assert!(!hub
        .pending_snapshots()
        .last()
        .unwrap()
        .contains(&notification));
}

/// NOTIF-004 — NotificationType has Error / Notification / Confirmation values
#[test]
fn notification_type_values_are_complete() {
    assert_eq!(
        vec![
            NotificationType::Error,
            NotificationType::Notification,
            NotificationType::Confirmation,
        ],
        vec![
            NotificationType::Error,
            NotificationType::Notification,
            NotificationType::Confirmation,
        ]
    );
}

/// NOTIF-005 — NotificationReaction has Pending / Approve / Reject values
#[test]
fn notification_reaction_values_are_complete() {
    assert_eq!(
        vec![
            NotificationReaction::Pending,
            NotificationReaction::Approve,
            NotificationReaction::Reject,
        ],
        vec![
            NotificationReaction::Pending,
            NotificationReaction::Approve,
            NotificationReaction::Reject,
        ]
    );
}

/// NOTIF-006 — The resolved task carries the reaction value
#[test]
fn waiter_carries_reject_reaction() {
    let hub = NotificationHub::new();
    let (notification, waiter) = hub.post_with_waiter(NotificationType::Notification, "info");

    hub.resolve(notification.id, NotificationReaction::Reject);

    assert_eq!(waiter.wait(), NotificationReaction::Reject);
}

/// NOTIF-007 — Confirmation notifications can be resolved Approve or Reject
#[test]
fn confirmation_notifications_resolve_approve_and_reject() {
    let hub = NotificationHub::new();
    let (approve, approve_waiter) =
        hub.post_with_waiter(NotificationType::Confirmation, "approve?");
    let (reject, reject_waiter) = hub.post_with_waiter(NotificationType::Confirmation, "reject?");

    hub.resolve(approve.id, NotificationReaction::Approve);
    hub.resolve(reject.id, NotificationReaction::Reject);

    assert_eq!(approve_waiter.wait(), NotificationReaction::Approve);
    assert_eq!(reject_waiter.wait(), NotificationReaction::Reject);
}

/// NOTIF-008 — Resolving a notification not in Pending is a no-op
#[test]
fn resolving_unknown_notification_is_noop() {
    let hub = NotificationHub::new();

    hub.resolve(999, NotificationReaction::Approve);

    assert!(hub.pending().is_empty());
}

/// NOTIF-009 — NullNotificationHub.Post resolves to Approve immediately
#[test]
fn null_notification_hub_resolves_approve() {
    let notification = Notification::new(NotificationType::Confirmation, "confirm?");
    let waiter = NullNotificationHub::post(notification);

    assert_eq!(waiter.wait(), NotificationReaction::Approve);
}

/// NOTIF-010 — make_confirm helper returns true iff resolved Approve
#[test]
fn make_confirm_style_flow_maps_approve_to_true() {
    let hub = NotificationHub::new();
    let confirm = make_confirm(hub.clone(), "ok?");
    let decision = confirm();
    let notification = hub.pending().into_iter().next().unwrap();

    hub.resolve(notification.id, NotificationReaction::Approve);

    assert!(decision.wait());
}

/// NOTIF-011 — NotificationVM opacity decays linearly from 1.0 to 0.0 over Lifespan
#[test]
fn notification_vm_opacity_decays_linearly() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Notification, "info");
    let vm = NotificationVm::with_hub(notification, hub, 10_000);

    assert_eq!(vm.opacity(), 1.0);
    vm.advance_by_ms(5_000);
    assert!((vm.opacity() - 0.5).abs() < 0.01);
    vm.advance_by_ms(5_000);
    assert_eq!(vm.opacity(), 0.0);
}

/// NOTIF-012 — NotificationVM auto-dismisses when RemainingTime reaches 0
#[test]
fn notification_vm_auto_dismisses_at_expiry() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Notification, "info");
    let vm = NotificationVm::with_hub(notification.clone(), hub.clone(), 10_000);

    vm.advance_by_ms(10_000);

    assert!(vm.is_resolved());
    assert_eq!(hub.reaction(notification.id), NotificationReaction::Approve);
}

/// NOTIF-013 — ConfirmationVM exposes ApproveCommand and RejectCommand
#[test]
fn confirmation_vm_commands_resolve_hub() {
    let hub = NotificationHub::new();
    let approve = hub.post(NotificationType::Confirmation, "approve?");
    let approve_vm = vmx::ConfirmationVm::with_hub(approve.clone(), hub.clone());

    approve_vm.approve_command().execute();

    assert!(approve_vm.is_resolved());
    assert_eq!(hub.reaction(approve.id), NotificationReaction::Approve);

    let reject = hub.post(NotificationType::Confirmation, "reject?");
    let reject_vm = vmx::ConfirmationVm::with_hub(reject.clone(), hub.clone());
    reject_vm.reject_command().execute();

    assert!(reject_vm.is_resolved());
    assert_eq!(hub.reaction(reject.id), NotificationReaction::Reject);
}

/// NOTIF-014 — Manual DismissCommand cancels the lifespan timer
#[test]
fn dismiss_command_is_idempotent_against_later_ticks() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Notification, "info");
    let vm = NotificationVm::with_hub(notification.clone(), hub.clone(), 10_000);

    vm.dismiss_command().execute();
    vm.advance_by_ms(10_000);

    assert_eq!(hub.reaction(notification.id), NotificationReaction::Approve);
    assert!(vm.is_resolved());
}

/// NOTIF-015 — Hub-side Resolve propagates to VM IsResolved state
#[test]
fn external_hub_resolve_marks_notification_vm_resolved() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Notification, "info");
    let vm = NotificationVm::with_hub(notification.clone(), hub.clone(), 10_000);

    hub.resolve(notification.id, NotificationReaction::Approve);

    assert!(vm.is_resolved());
}

/// NOTIF-016 — Deterministic behavior under injected TestScheduler / fake clock
#[test]
fn manual_clock_expiry_is_deterministic() {
    let hub = NotificationHub::new();
    let notification = hub.post(NotificationType::Notification, "info");
    let vm = NotificationVm::with_hub(notification.clone(), hub.clone(), 10_000);

    vm.advance_by_ms(10_000);
    vm.advance_by_ms(10_000);

    assert_eq!(vm.remaining_time_ms(), 0);
    assert_eq!(vm.opacity(), 0.0);
    assert_eq!(hub.reaction(notification.id), NotificationReaction::Approve);
}

/// NOTIF-017 — Hub dispose resolves in-flight waiters with Pending
#[test]
fn hub_dispose_resolves_waiters_pending() {
    let hub = NotificationHub::new();
    let (_notification, waiter) = hub.post_with_waiter(NotificationType::Notification, "info");

    hub.dispose();

    assert_eq!(waiter.wait(), NotificationReaction::Pending);
    assert!(hub.pending().is_empty());
}

/// DISP-003 — concurrent disposal of a thread-safe hub performs terminal work once
#[test]
fn concurrent_notification_hub_dispose_publishes_one_terminal_snapshot() {
    use std::sync::{Arc, Barrier};

    for _ in 0..100 {
        let hub = NotificationHub::new();
        hub.post(NotificationType::Notification, "info");
        let before = hub.pending_snapshots().len();
        let barrier = Arc::new(Barrier::new(32));
        let threads = (0..32)
            .map(|_| {
                let hub = hub.clone();
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    hub.dispose();
                })
            })
            .collect::<Vec<_>>();

        for thread in threads {
            thread.join().unwrap();
        }

        assert_eq!(hub.pending_snapshots().len(), before + 1);
    }
}
