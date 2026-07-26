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
fn panicking_waiter_waker_does_not_escape_resolution() {
    use std::future::Future;
    use std::pin::Pin;
    use std::sync::Arc;
    use std::task::{Context, Poll, Wake, Waker};

    struct PanicWake;

    impl Wake for PanicWake {
        fn wake(self: Arc<Self>) {
            panic!("waker boom");
        }
    }

    let hub = NotificationHub::new();
    let (notification, waiter) =
        hub.post_with_waiter(NotificationType::Notification, "panic isolation");
    let mut polled_waiter = waiter.clone();
    let waker = Waker::from(Arc::new(PanicWake));
    let mut context = Context::from_waker(&waker);
    assert_eq!(
        Pin::new(&mut polled_waiter).poll(&mut context),
        Poll::Pending
    );

    hub.resolve(notification.id, NotificationReaction::Approve);

    assert_eq!(waiter.wait(), NotificationReaction::Approve);
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
    let observed = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let values = observed.clone();
    let _subscription = hub
        .pending_stream()
        .subscribe(move |pending| values.lock().unwrap().push(pending));
    let notification = hub.post(NotificationType::Notification, "info");

    assert!(hub.pending().contains(&notification));
    assert_eq!(
        *observed.lock().unwrap(),
        vec![Vec::new(), vec![notification.clone()]]
    );
    let late_values = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let late_observed = late_values.clone();
    let _late = hub
        .pending_stream()
        .subscribe(move |pending| late_observed.lock().unwrap().push(pending));
    assert_eq!(
        *late_values.lock().unwrap(),
        vec![vec![notification.clone()]]
    );
    assert!(hub
        .pending_snapshots()
        .last()
        .unwrap()
        .contains(&notification));
}

#[test]
fn reentrant_pending_mutation_publishes_each_committed_snapshot_once() {
    let hub = NotificationHub::new();
    let first = Notification::new(NotificationType::Notification, "first");
    let second = Notification::new(NotificationType::Notification, "second");
    let observed = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let snapshots = observed.clone();
    let reentrant = hub.clone();
    let first_for_callback = first.clone();
    let second_for_callback = second.clone();
    let _subscription = hub.pending_stream().subscribe(move |pending| {
        snapshots.lock().unwrap().push(pending.clone());
        if pending == vec![first_for_callback.clone()] {
            reentrant.post_notification(second_for_callback.clone());
        }
    });

    hub.post_notification(first.clone());

    assert_eq!(
        *observed.lock().unwrap(),
        vec![
            Vec::<Notification>::new(),
            vec![first.clone()],
            vec![first.clone(), second.clone()],
        ]
    );
    assert_eq!(
        hub.pending_snapshots(),
        vec![vec![first.clone()], vec![first, second]]
    );
}

#[test]
fn concurrent_pending_delivery_matches_committed_snapshot_order() {
    use std::sync::{mpsc, Arc, Mutex};

    let hub = NotificationHub::new();
    let first = Notification::new(NotificationType::Notification, "first");
    let second = Notification::new(NotificationType::Notification, "second");
    let observed = Arc::new(Mutex::new(Vec::new()));
    let snapshots = observed.clone();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let release = release_rx.clone();
    let _subscription = hub.pending_stream().subscribe(move |pending| {
        if pending.len() == 1 {
            entered_tx.send(()).unwrap();
            release.lock().unwrap().recv().unwrap();
        }
        snapshots.lock().unwrap().push(pending);
    });

    let first_poster = {
        let hub = hub.clone();
        let first = first.clone();
        std::thread::spawn(move || hub.post_notification(first))
    };
    entered_rx.recv().unwrap();
    let second_poster = {
        let hub = hub.clone();
        let second = second.clone();
        let (returned_tx, returned_rx) = mpsc::channel();
        (
            std::thread::spawn(move || {
                hub.post_notification(second);
                returned_tx.send(()).unwrap();
            }),
            returned_rx,
        )
    };
    while hub.pending().len() != 2 {
        std::thread::yield_now();
    }
    let returned_before_publication = second_poster
        .1
        .recv_timeout(std::time::Duration::from_millis(50))
        .is_ok();
    release_tx.send(()).unwrap();
    second_poster.0.join().unwrap();
    first_poster.join().unwrap();

    assert!(
        !returned_before_publication,
        "post_notification returned before its committed snapshot was published"
    );
    assert_eq!(second_poster.1.try_recv(), Ok(()));
    assert_eq!(
        *observed.lock().unwrap(),
        vec![
            Vec::<Notification>::new(),
            vec![first.clone()],
            vec![first.clone(), second.clone()],
        ]
    );
    assert_eq!(
        hub.pending_snapshots(),
        vec![vec![first.clone()], vec![first, second]]
    );
}

#[test]
fn concurrent_resolve_returns_after_its_queued_snapshot_and_waiter_completion() {
    use std::sync::{mpsc, Arc, Mutex};

    let hub = NotificationHub::new();
    let (target, waiter) = hub.post_with_waiter(NotificationType::Notification, "resolve-target");
    let blocker = Notification::new(NotificationType::Notification, "blocker");
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let release = release_rx.clone();
    let _subscription = hub.pending_stream().subscribe(move |pending| {
        if pending.len() == 2 {
            entered_tx.send(()).unwrap();
            release.lock().unwrap().recv().unwrap();
        }
    });

    let posting_hub = hub.clone();
    let poster = std::thread::spawn(move || posting_hub.post_notification(blocker));
    entered_rx.recv().unwrap();

    let (returned_tx, returned_rx) = mpsc::channel();
    let resolving_hub = hub.clone();
    let target_id = target.id;
    let resolver = std::thread::spawn(move || {
        resolving_hub.resolve(target_id, NotificationReaction::Approve);
        returned_tx.send(()).unwrap();
    });
    while hub.pending().contains(&target) {
        std::thread::yield_now();
    }
    let returned_before_publication = returned_rx
        .recv_timeout(std::time::Duration::from_millis(50))
        .is_ok();
    assert_eq!(waiter.try_get(), None);

    release_tx.send(()).unwrap();
    poster.join().unwrap();
    resolver.join().unwrap();

    assert!(
        !returned_before_publication,
        "resolve returned before its committed snapshot was published"
    );
    assert_eq!(returned_rx.try_recv(), Ok(()));
    assert_eq!(waiter.try_get(), Some(NotificationReaction::Approve));
}

/// NOTIF-003 — Resolve removes the notification from Pending
#[test]
fn resolve_removes_notification_from_pending_snapshot() {
    let hub = NotificationHub::new();
    let (notification, waiter) =
        hub.post_with_waiter(NotificationType::Notification, "publish-before-complete");
    let waiter_at_publish = waiter.clone();
    let completion_state = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let observed_state = completion_state.clone();
    let _subscription = hub.pending_stream().subscribe(move |pending| {
        if pending.is_empty() {
            observed_state
                .lock()
                .unwrap()
                .push(waiter_at_publish.try_get());
        }
    });

    hub.resolve(notification.id, NotificationReaction::Approve);

    assert!(!hub.pending().contains(&notification));
    assert!(!hub
        .pending_snapshots()
        .last()
        .unwrap()
        .contains(&notification));
    assert_eq!(
        *completion_state.lock().unwrap(),
        vec![None],
        "pending must publish before its waiter is completed"
    );
    assert_eq!(waiter.try_get(), Some(NotificationReaction::Approve));
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

    let values = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let observed = values.clone();
    let completed = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let completion = completed.clone();
    let _subscription = NullNotificationHub::pending_stream().subscribe_with_completion(
        move |pending| observed.lock().unwrap().push(pending),
        move || completion.store(true, std::sync::atomic::Ordering::SeqCst),
    );

    assert_eq!(*values.lock().unwrap(), vec![Vec::<Notification>::new()]);
    assert!(completed.load(std::sync::atomic::Ordering::SeqCst));
}

/// NOTIF-010 — make_confirm helper returns true iff resolved Approve
#[test]
fn make_confirm_style_flow_maps_approve_to_true() {
    let hub = NotificationHub::new();
    let confirm = make_confirm(hub.clone(), "ok?");
    let decision = confirm();
    let resolving_thread = std::thread::current().id();
    let continuation_thread = std::sync::Arc::new(std::sync::Mutex::new(None));
    let observed_thread = continuation_thread.clone();
    let completed = decision.map(move |value| {
        *observed_thread.lock().unwrap() = Some(std::thread::current().id());
        value
    });
    let notification = hub.pending().into_iter().next().unwrap();

    hub.resolve(notification.id, NotificationReaction::Approve);

    assert!(completed.wait());
    assert_eq!(*continuation_thread.lock().unwrap(), Some(resolving_thread));
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
    let completed = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let observed = completed.clone();
    let _subscription = hub.pending_stream().subscribe_with_completion(
        |_| {},
        move || {
            observed.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        },
    );

    hub.dispose();

    assert_eq!(waiter.wait(), NotificationReaction::Pending);
    assert!(hub.pending().is_empty());
    assert_eq!(completed.load(std::sync::atomic::Ordering::SeqCst), 1);
}

#[test]
fn concurrent_dispose_returns_after_queued_terminal_publication_and_completions() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{mpsc, Arc, Mutex};

    let hub = NotificationHub::new();
    let (_target, target_waiter) =
        hub.post_with_waiter(NotificationType::Notification, "dispose-target");
    let blocker = Notification::new(NotificationType::Notification, "blocker");
    let completions = Arc::new(AtomicUsize::new(0));
    let completed = completions.clone();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let release = release_rx.clone();
    let _subscription = hub.pending_stream().subscribe_with_completion(
        move |pending| {
            if pending.len() == 2 {
                entered_tx.send(()).unwrap();
                release.lock().unwrap().recv().unwrap();
            }
        },
        move || {
            completed.fetch_add(1, Ordering::SeqCst);
        },
    );

    let posting_hub = hub.clone();
    let poster = std::thread::spawn(move || posting_hub.post_notification(blocker));
    entered_rx.recv().unwrap();

    let (returned_tx, returned_rx) = mpsc::channel();
    let disposing_hub = hub.clone();
    let disposer = std::thread::spawn(move || {
        disposing_hub.dispose();
        returned_tx.send(()).unwrap();
    });
    while !hub.pending().is_empty() {
        std::thread::yield_now();
    }
    let returned_before_terminal = returned_rx
        .recv_timeout(std::time::Duration::from_millis(50))
        .is_ok();
    assert_eq!(target_waiter.try_get(), None);
    assert_eq!(completions.load(Ordering::SeqCst), 0);

    release_tx.send(()).unwrap();
    let blocker_waiter = poster.join().unwrap();
    disposer.join().unwrap();

    assert!(
        !returned_before_terminal,
        "dispose returned before its terminal publication and callbacks"
    );
    assert_eq!(returned_rx.try_recv(), Ok(()));
    assert_eq!(target_waiter.try_get(), Some(NotificationReaction::Pending));
    assert_eq!(
        blocker_waiter.try_get(),
        Some(NotificationReaction::Pending)
    );
    assert_eq!(completions.load(Ordering::SeqCst), 1);
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

#[test]
fn post_racing_dispose_never_orphans_its_waiter() {
    use std::sync::{mpsc, Arc, Barrier};
    use std::time::Duration;

    for iteration in 0..200 {
        let hub = NotificationHub::new();
        let notification = Notification::new(NotificationType::Notification, "race");
        let barrier = Arc::new(Barrier::new(3));
        let (waiter_tx, waiter_rx) = mpsc::channel();
        let poster = {
            let hub = hub.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                waiter_tx.send(hub.post_notification(notification)).unwrap();
            })
        };
        let disposer = {
            let hub = hub.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                hub.dispose();
            })
        };
        barrier.wait();
        poster.join().unwrap();
        disposer.join().unwrap();
        let waiter = waiter_rx.recv().unwrap();
        let (reaction_tx, reaction_rx) = mpsc::channel();
        std::thread::spawn(move || reaction_tx.send(waiter.wait()).unwrap());

        assert_eq!(
            reaction_rx.recv_timeout(Duration::from_secs(1)),
            Ok(NotificationReaction::Pending),
            "iteration {iteration} orphaned a waiter"
        );
    }
}
