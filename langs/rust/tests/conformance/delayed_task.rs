//! `DelayedTask` over a virtual-time scheduler (spec/11 §6.3, ADR-0219).

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use vmx::{DelayedTask, Scheduler, VirtualTimeScheduler};

fn secs(seconds: u64) -> Duration {
    Duration::from_secs(seconds)
}

fn counter() -> (Arc<AtomicUsize>, impl Fn() + Send + Sync + Clone + 'static) {
    let count = Arc::new(AtomicUsize::new(0));
    let seen = count.clone();
    (count, move || {
        seen.fetch_add(1, Ordering::SeqCst);
    })
}

/// DLY-001 — a scheduled action runs once at its due time
#[test]
fn scheduled_action_runs_once_at_its_due_time() {
    let scheduler = VirtualTimeScheduler::new();
    let task = DelayedTask::new(scheduler.clone());
    let runs = Arc::new(AtomicUsize::new(0));
    let pending_when_started = Arc::new(Mutex::new(None));
    let (seen, observed, probe) = (runs.clone(), pending_when_started.clone(), task.clone());

    task.schedule(secs(10), move || {
        *observed.lock().unwrap() = Some(probe.is_pending());
        seen.fetch_add(1, Ordering::SeqCst);
    });
    assert!(task.is_pending());

    scheduler.advance_by(secs(9));
    assert_eq!(runs.load(Ordering::SeqCst), 0);
    assert!(task.is_pending());

    scheduler.advance_by(secs(1));
    assert_eq!(runs.load(Ordering::SeqCst), 1);
    assert_eq!(*pending_when_started.lock().unwrap(), Some(false));
    assert!(!task.is_pending());

    scheduler.advance_by(secs(10));
    assert_eq!(runs.load(Ordering::SeqCst), 1);
}

/// DLY-001 — an action that schedules itself again repeats as a polling loop
#[test]
fn self_rescheduling_action_polls_until_it_stops() {
    let scheduler = VirtualTimeScheduler::new();
    let task = DelayedTask::new(scheduler.clone());
    let run_times = Arc::new(Mutex::new(Vec::new()));

    fn poll(task: DelayedTask, scheduler: VirtualTimeScheduler, times: Arc<Mutex<Vec<Duration>>>) {
        let (next_task, next_scheduler, next_times) = (task.clone(), scheduler.clone(), times);
        task.schedule(secs(5), move || {
            let runs = {
                let mut times = next_times.lock().unwrap();
                times.push(next_scheduler.now());
                times.len()
            };
            if runs < 3 {
                poll(next_task, next_scheduler, next_times);
            }
        });
    }

    poll(task.clone(), scheduler.clone(), run_times.clone());
    scheduler.advance_by(secs(30));

    assert_eq!(
        *run_times.lock().unwrap(),
        vec![secs(5), secs(10), secs(15)]
    );
    assert!(!task.is_pending());
}

/// DLY-002 — a second schedule replaces the pending action and restarts the delay
#[test]
fn second_schedule_replaces_the_pending_action_and_restarts_the_delay() {
    let scheduler = VirtualTimeScheduler::new();
    let task = DelayedTask::new(scheduler.clone());
    let (a_runs, a) = counter();
    let (b_runs, b) = counter();

    task.schedule(secs(10), a);
    scheduler.advance_by(secs(6));
    task.schedule(secs(10), b);
    scheduler.advance_by(secs(9));
    assert_eq!(a_runs.load(Ordering::SeqCst), 0);
    assert_eq!(b_runs.load(Ordering::SeqCst), 0);
    assert!(task.is_pending());

    scheduler.advance_by(secs(1));
    assert_eq!(b_runs.load(Ordering::SeqCst), 1);

    scheduler.advance_by(secs(10));
    assert_eq!(a_runs.load(Ordering::SeqCst), 0);
    assert_eq!(b_runs.load(Ordering::SeqCst), 1);
}

/// DLY-003 — cancel prevents the pending action
#[test]
fn cancel_prevents_the_pending_action() {
    let scheduler = VirtualTimeScheduler::new();
    let task = DelayedTask::new(scheduler.clone());
    task.cancel();
    assert!(!task.is_pending());

    let (cancelled_runs, cancelled) = counter();
    task.schedule(secs(10), cancelled);
    scheduler.advance_by(secs(4));
    task.cancel();
    assert!(!task.is_pending());
    scheduler.advance_by(secs(10));
    assert_eq!(cancelled_runs.load(Ordering::SeqCst), 0);

    let (next_runs, next) = counter();
    task.schedule(secs(10), next);
    scheduler.advance_by(secs(9));
    assert_eq!(next_runs.load(Ordering::SeqCst), 0);
    scheduler.advance_by(secs(1));
    assert_eq!(next_runs.load(Ordering::SeqCst), 1);
    assert_eq!(cancelled_runs.load(Ordering::SeqCst), 0);
}

/// DLY-004 — disposal cancels the pending action, and later calls have no effect
#[test]
fn dispose_cancels_and_later_calls_have_no_effect() {
    let scheduler = VirtualTimeScheduler::new();
    let task = DelayedTask::new(scheduler.clone());
    let (pending_runs, pending) = counter();
    task.schedule(secs(10), pending);

    task.dispose();
    task.dispose();
    assert!(!task.is_pending());
    scheduler.advance_by(secs(11));
    assert_eq!(pending_runs.load(Ordering::SeqCst), 0);

    let (late_runs, late) = counter();
    task.schedule(secs(1), late);
    assert!(!task.is_pending());
    task.cancel();
    assert!(!task.is_pending());
    scheduler.advance_by(secs(5));
    assert_eq!(late_runs.load(Ordering::SeqCst), 0);

    let other = Arc::new(AtomicBool::new(false));
    let ran = other.clone();
    let _handle = scheduler.schedule(
        secs(1),
        Box::new(move || {
            ran.store(true, Ordering::SeqCst);
        }),
    );
    scheduler.advance_by(secs(1));
    assert!(
        other.load(Ordering::SeqCst),
        "disposal never disposes the scheduler"
    );
}

/// DLY-005 — a failing action stays isolated, and the task stays usable
#[test]
fn failing_action_is_isolated_and_the_task_stays_usable() {
    let scheduler = VirtualTimeScheduler::new();
    let task = DelayedTask::new(scheduler.clone());
    task.schedule(secs(1), || panic!("delayed action failed"));

    let advanced = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        scheduler.advance_by(secs(2))
    }));
    assert!(
        advanced.is_ok(),
        "the failure does not reach the code that advances the scheduler"
    );
    assert!(!task.is_pending());

    let (runs, action) = counter();
    task.schedule(secs(1), action);
    scheduler.advance_by(secs(2));
    assert_eq!(runs.load(Ordering::SeqCst), 1);
}
