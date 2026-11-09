//! Delayed work: the scheduler contract and `DelayedTask`.
//!
//! Spec: `spec/11-threading.md` §6; ADR-0219.

use std::collections::BTreeMap;
use std::fmt;
use std::time::{Duration, Instant};

use super::{catch_unwind, lock, thread, Arc, AssertUnwindSafe, Condvar, Mutex, OnceLock};

type Action = Box<dyn FnOnce() + Send>;

/// The clock for delayed work (spec/11 §6.1).
///
/// A scheduler reports its current time and runs an action once after a
/// delay. [`SystemScheduler`] runs actions in real time, and
/// [`VirtualTimeScheduler`] runs them when a test advances it.
pub trait Scheduler: Send + Sync + 'static {
    /// Returns the current time of the scheduler, measured from its origin.
    fn now(&self) -> Duration;

    /// Runs `action` once after `delay` and returns a handle that cancels it.
    ///
    /// A zero delay runs the action at the scheduler's next opportunity.
    fn schedule(&self, delay: Duration, action: Box<dyn FnOnce() + Send>) -> ScheduledAction;
}

impl<S: Scheduler + ?Sized> Scheduler for Arc<S> {
    fn now(&self) -> Duration {
        (**self).now()
    }

    fn schedule(&self, delay: Duration, action: Box<dyn FnOnce() + Send>) -> ScheduledAction {
        (**self).schedule(delay, action)
    }
}

/// The cancel handle of one scheduled action.
///
/// [`cancel`](Self::cancel) prevents the action if it has not started.
/// Dropping the handle does not cancel the action.
pub struct ScheduledAction {
    cancel: Mutex<Option<Action>>,
}

impl ScheduledAction {
    /// Creates a handle that runs `cancel` at its first
    /// [`cancel`](Self::cancel) call.
    pub fn new(cancel: impl FnOnce() + Send + 'static) -> Self {
        Self {
            cancel: Mutex::new(Some(Box::new(cancel))),
        }
    }

    /// Cancels the action if it has not started. A second call has no effect.
    pub fn cancel(&self) {
        let cancel = lock(&self.cancel).take();
        if let Some(cancel) = cancel {
            cancel();
        }
    }
}

impl fmt::Debug for ScheduledAction {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ScheduledAction")
            .field("cancelled", &lock(&self.cancel).is_none())
            .finish()
    }
}

/// The ordered queue of a scheduler: actions keyed by due time, then by
/// scheduling order.
struct Queue<T: Ord + Copy> {
    next_sequence: u64,
    entries: BTreeMap<(T, u64), Action>,
}

impl<T: Ord + Copy> Default for Queue<T> {
    fn default() -> Self {
        Self {
            next_sequence: 0,
            entries: BTreeMap::new(),
        }
    }
}

impl<T: Ord + Copy> Queue<T> {
    fn push(&mut self, due: T, action: Action) -> (T, u64) {
        let key = (due, self.next_sequence);
        self.next_sequence += 1;
        self.entries.insert(key, action);
        key
    }

    fn earliest_due(&self) -> Option<T> {
        self.entries.first_key_value().map(|(&(due, _), _)| due)
    }
}

/// The real-time scheduler.
///
/// It runs actions in due-time order on one process-wide VMx timer thread,
/// which it starts at its first `schedule`. Its `now` is the time since a
/// fixed process origin. A panicking action does not stop the timer thread.
#[derive(Clone, Copy, Debug, Default)]
pub struct SystemScheduler;

impl SystemScheduler {
    /// Creates a handle to the process-wide real-time scheduler.
    pub fn new() -> Self {
        Self
    }
}

struct Timer {
    state: Mutex<TimerState>,
    wake: Condvar,
}

#[derive(Default)]
struct TimerState {
    queue: Queue<Instant>,
    started: bool,
}

/// A due time far enough away to stand for "never" when a delay overflows
/// `Instant`.
const FAR_FUTURE: Duration = Duration::from_secs(100 * 365 * 24 * 60 * 60);

fn system_origin() -> Instant {
    static ORIGIN: OnceLock<Instant> = OnceLock::new();
    *ORIGIN.get_or_init(Instant::now)
}

fn system_timer() -> &'static Timer {
    static TIMER: OnceLock<Timer> = OnceLock::new();
    TIMER.get_or_init(|| Timer {
        state: Mutex::new(TimerState::default()),
        wake: Condvar::new(),
    })
}

fn run_system_timer(timer: &'static Timer) {
    let mut state = lock(&timer.state);
    loop {
        let now = Instant::now();
        match state.queue.earliest_due() {
            None => {
                state = timer
                    .wake
                    .wait(state)
                    .unwrap_or_else(|poisoned| poisoned.into_inner());
            }
            Some(due) if due > now => {
                state = timer
                    .wake
                    .wait_timeout(state, due - now)
                    .unwrap_or_else(|poisoned| poisoned.into_inner())
                    .0;
            }
            Some(_) => {
                let action = state.queue.entries.pop_first().map(|(_, action)| action);
                drop(state);
                if let Some(action) = action {
                    // A failing action never stops the timer thread.
                    let _ = catch_unwind(AssertUnwindSafe(action));
                }
                state = lock(&timer.state);
            }
        }
    }
}

impl Scheduler for SystemScheduler {
    fn now(&self) -> Duration {
        Instant::now().saturating_duration_since(system_origin())
    }

    fn schedule(&self, delay: Duration, action: Box<dyn FnOnce() + Send>) -> ScheduledAction {
        let origin = system_origin();
        let timer = system_timer();
        let now = Instant::now().max(origin);
        let due = now
            .checked_add(delay)
            .or_else(|| now.checked_add(FAR_FUTURE))
            .unwrap_or(now);
        let (key, start) = {
            let mut state = lock(&timer.state);
            let key = state.queue.push(due, action);
            let start = !state.started;
            state.started = true;
            (key, start)
        };
        if start {
            thread::Builder::new()
                .name("vmx-timer".to_string())
                .spawn(move || run_system_timer(timer))
                .expect("VMx could not start its timer thread");
        } else {
            timer.wake.notify_one();
        }
        ScheduledAction::new(move || {
            // Drop the removed action after the lock is released: it may own
            // a handle whose drop cancels another entry.
            let removed = lock(&timer.state).queue.entries.remove(&key);
            drop(removed);
            timer.wake.notify_one();
        })
    }
}

/// A virtual-time scheduler for tests.
///
/// Its clock starts at [`Duration::ZERO`] and moves only through
/// [`advance_by`](Self::advance_by). Clones share one clock and one queue.
///
/// ```
/// use std::sync::atomic::{AtomicUsize, Ordering};
/// use std::sync::Arc;
/// use std::time::Duration;
/// use vmx::{Scheduler, VirtualTimeScheduler};
///
/// let scheduler = VirtualTimeScheduler::new();
/// let runs = Arc::new(AtomicUsize::new(0));
/// let seen = runs.clone();
/// let _handle = scheduler.schedule(
///     Duration::from_secs(5),
///     Box::new(move || {
///         seen.fetch_add(1, Ordering::SeqCst);
///     }),
/// );
///
/// scheduler.advance_by(Duration::from_secs(4));
/// assert_eq!(runs.load(Ordering::SeqCst), 0);
/// scheduler.advance_by(Duration::from_secs(1));
/// assert_eq!(runs.load(Ordering::SeqCst), 1);
/// assert_eq!(scheduler.now(), Duration::from_secs(5));
/// ```
#[derive(Clone, Default)]
pub struct VirtualTimeScheduler {
    shared: Arc<Mutex<VirtualState>>,
}

#[derive(Default)]
struct VirtualState {
    now: Duration,
    queue: Queue<Duration>,
}

impl VirtualTimeScheduler {
    /// Creates a virtual-time scheduler at time zero with no queued action.
    pub fn new() -> Self {
        Self::default()
    }

    /// Moves the clock forward by `delta` and runs each action that becomes
    /// due, on the calling thread.
    ///
    /// Actions run in due-time order, and actions with the same due time run
    /// in scheduling order. The clock reads each action's due time while it
    /// runs. An action that an action schedules runs in the same call when it
    /// is due by the end of the advance. A panicking action reaches the
    /// caller.
    pub fn advance_by(&self, delta: Duration) {
        let target = lock(&self.shared).now.saturating_add(delta);
        loop {
            let action = {
                let mut state = lock(&self.shared);
                match state.queue.earliest_due() {
                    Some(due) if due <= target => {
                        state.now = state.now.max(due);
                        state.queue.entries.pop_first().map(|(_, action)| action)
                    }
                    _ => {
                        state.now = state.now.max(target);
                        None
                    }
                }
            };
            match action {
                Some(action) => action(),
                None => break,
            }
        }
    }
}

impl Scheduler for VirtualTimeScheduler {
    fn now(&self) -> Duration {
        lock(&self.shared).now
    }

    fn schedule(&self, delay: Duration, action: Box<dyn FnOnce() + Send>) -> ScheduledAction {
        let key = {
            let mut state = lock(&self.shared);
            let due = state.now.saturating_add(delay);
            state.queue.push(due, action)
        };
        let shared = Arc::downgrade(&self.shared);
        ScheduledAction::new(move || {
            if let Some(shared) = shared.upgrade() {
                // Drop the removed action after the lock is released.
                let removed = lock(&shared).queue.entries.remove(&key);
                drop(removed);
            }
        })
    }
}

impl fmt::Debug for VirtualTimeScheduler {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let state = lock(&self.shared);
        formatter
            .debug_struct("VirtualTimeScheduler")
            .field("now", &state.now)
            .field("queued", &state.queue.entries.len())
            .finish()
    }
}

/// A disposable helper that holds at most one delayed action on an injected
/// scheduler (spec/11 §6.3).
///
/// [`schedule`](Self::schedule) replaces a pending action and restarts the
/// delay, [`cancel`](Self::cancel) stops it, [`is_pending`](Self::is_pending)
/// reports it, and [`dispose`](Self::dispose) cancels it and makes later
/// calls inert. Clones share one task. When the last clone is dropped, the
/// pending action is cancelled.
///
/// The task is safe to use from any thread. After `schedule`, `cancel` or
/// `dispose` returns, a replaced or cancelled action never starts. A
/// panicking action is caught and dropped (spec/03 §3.6), and the task stays
/// usable.
///
/// ```
/// use std::sync::atomic::{AtomicUsize, Ordering};
/// use std::sync::Arc;
/// use std::time::Duration;
/// use vmx::{DelayedTask, VirtualTimeScheduler};
///
/// let scheduler = VirtualTimeScheduler::new();
/// let task = DelayedTask::new(scheduler.clone());
/// let saves = Arc::new(AtomicUsize::new(0));
///
/// for _ in 0..3 {
///     let saves = saves.clone();
///     task.schedule(Duration::from_secs(2), move || {
///         saves.fetch_add(1, Ordering::SeqCst);
///     });
/// }
/// assert!(task.is_pending());
///
/// scheduler.advance_by(Duration::from_secs(2));
/// assert_eq!(saves.load(Ordering::SeqCst), 1);
/// assert!(!task.is_pending());
/// ```
#[derive(Clone)]
pub struct DelayedTask {
    inner: Arc<DelayedTaskInner>,
}

struct DelayedTaskInner {
    scheduler: Box<dyn Scheduler>,
    state: Mutex<DelayedTaskState>,
}

#[derive(Default)]
struct DelayedTaskState {
    generation: u64,
    pending: bool,
    disposed: bool,
    handle: Option<ScheduledAction>,
}

impl DelayedTask {
    /// Creates a task with no pending action over `scheduler`.
    pub fn new(scheduler: impl Scheduler) -> Self {
        Self {
            inner: Arc::new(DelayedTaskInner {
                scheduler: Box::new(scheduler),
                state: Mutex::new(DelayedTaskState::default()),
            }),
        }
    }

    /// Cancels the pending action, if any, and schedules `action` after
    /// `delay`.
    ///
    /// A zero delay runs the action at the scheduler's next opportunity, never
    /// inside this call. When the action starts, [`is_pending`](Self::is_pending)
    /// is already `false`, so the action can schedule again. Has no effect
    /// after [`dispose`](Self::dispose).
    pub fn schedule(&self, delay: Duration, action: impl FnOnce() + Send + 'static) {
        let (generation, replaced) = {
            let mut state = lock(&self.inner.state);
            if state.disposed {
                return;
            }
            state.generation += 1;
            state.pending = true;
            (state.generation, state.handle.take())
        };
        if let Some(replaced) = replaced {
            replaced.cancel();
        }
        let task = Arc::downgrade(&self.inner);
        let handle = self.inner.scheduler.schedule(
            delay,
            Box::new(move || {
                if let Some(task) = task.upgrade() {
                    task.run(generation, action);
                }
            }),
        );
        let stale = {
            let mut state = lock(&self.inner.state);
            if state.generation == generation && state.pending && !state.disposed {
                state.handle = Some(handle);
                None
            } else {
                Some(handle)
            }
        };
        if let Some(stale) = stale {
            stale.cancel();
        }
    }

    /// Cancels the pending action. Has no effect when no action is pending.
    ///
    /// An action that already started runs to its end; `cancel` does not
    /// wait for it.
    pub fn cancel(&self) {
        let handle = {
            let mut state = lock(&self.inner.state);
            if !state.pending {
                return;
            }
            state.generation += 1;
            state.pending = false;
            state.handle.take()
        };
        if let Some(handle) = handle {
            handle.cancel();
        }
    }

    /// Reports whether an action is scheduled and has not started.
    pub fn is_pending(&self) -> bool {
        lock(&self.inner.state).pending
    }

    /// Cancels the pending action and makes later calls inert.
    ///
    /// A second call has no effect. Disposal never disposes the scheduler.
    pub fn dispose(&self) {
        let handle = {
            let mut state = lock(&self.inner.state);
            if state.disposed {
                return;
            }
            state.disposed = true;
            state.generation += 1;
            state.pending = false;
            state.handle.take()
        };
        if let Some(handle) = handle {
            handle.cancel();
        }
    }
}

impl DelayedTaskInner {
    fn run(&self, generation: u64, action: impl FnOnce()) {
        let handle = {
            let mut state = lock(&self.state);
            if state.generation != generation || !state.pending || state.disposed {
                return;
            }
            state.pending = false;
            state.handle.take()
        };
        drop(handle);
        // A failing action takes the stream-fed route (spec/03 §3.6): the
        // failure is dropped and never reaches the scheduler.
        let _ = catch_unwind(AssertUnwindSafe(action));
    }
}

impl Drop for DelayedTaskInner {
    fn drop(&mut self) {
        let state = self
            .state
            .get_mut()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if let Some(handle) = state.handle.take() {
            handle.cancel();
        }
    }
}

impl fmt::Debug for DelayedTask {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let state = lock(&self.inner.state);
        formatter
            .debug_struct("DelayedTask")
            .field("pending", &state.pending)
            .field("disposed", &state.disposed)
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::mpsc;

    fn recorder() -> (
        Arc<Mutex<Vec<&'static str>>>,
        impl Fn(&'static str) -> Action,
    ) {
        let log = Arc::new(Mutex::new(Vec::new()));
        let shared = log.clone();
        (log, move |name| {
            let log = shared.clone();
            Box::new(move || lock(&log).push(name))
        })
    }

    #[test]
    fn virtual_actions_run_in_due_order_and_fifo_for_ties() {
        let scheduler = VirtualTimeScheduler::new();
        let (log, entry) = recorder();
        let _c = scheduler.schedule(Duration::from_secs(3), entry("c"));
        let _a = scheduler.schedule(Duration::from_secs(1), entry("a"));
        let _b1 = scheduler.schedule(Duration::from_secs(2), entry("b1"));
        let _b2 = scheduler.schedule(Duration::from_secs(2), entry("b2"));

        scheduler.advance_by(Duration::from_secs(3));

        assert_eq!(*lock(&log), ["a", "b1", "b2", "c"]);
    }

    #[test]
    fn virtual_nested_work_due_in_the_same_advance_runs() {
        let scheduler = VirtualTimeScheduler::new();
        let (log, entry) = recorder();
        let nested_scheduler = scheduler.clone();
        let late = entry("late");
        let nested = entry("nested");
        let _outer = scheduler.schedule(
            Duration::from_secs(1),
            Box::new(move || {
                let _inner = nested_scheduler.schedule(Duration::from_secs(1), nested);
                let _after = nested_scheduler.schedule(Duration::from_secs(5), late);
            }),
        );

        scheduler.advance_by(Duration::from_secs(2));
        assert_eq!(*lock(&log), ["nested"]);
        assert_eq!(scheduler.now(), Duration::from_secs(2));

        scheduler.advance_by(Duration::from_secs(4));
        assert_eq!(*lock(&log), ["nested", "late"]);
    }

    #[test]
    fn virtual_cancel_prevents_the_action_and_drop_does_not() {
        let scheduler = VirtualTimeScheduler::new();
        let (log, entry) = recorder();
        let cancelled = scheduler.schedule(Duration::from_secs(1), entry("cancelled"));
        let dropped = scheduler.schedule(Duration::from_secs(1), entry("dropped"));
        cancelled.cancel();
        cancelled.cancel();
        drop(dropped);

        scheduler.advance_by(Duration::from_secs(1));

        assert_eq!(*lock(&log), ["dropped"]);
    }

    #[test]
    fn virtual_clock_reaches_the_target_with_an_empty_queue() {
        let scheduler = VirtualTimeScheduler::new();
        scheduler.advance_by(Duration::from_millis(1_500));
        assert_eq!(scheduler.now(), Duration::from_millis(1_500));
        scheduler.advance_by(Duration::MAX);
        assert_eq!(scheduler.now(), Duration::MAX);
    }

    #[test]
    fn system_scheduler_runs_an_action_after_its_delay() {
        let (sender, receiver) = mpsc::channel();
        let started = SystemScheduler.now();
        let _handle = SystemScheduler.schedule(
            Duration::from_millis(20),
            Box::new(move || {
                let _ = sender.send(SystemScheduler.now());
            }),
        );

        let ran_at = receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("the action runs within the bounded wait");
        assert!(ran_at >= started + Duration::from_millis(20));
    }

    #[test]
    fn system_scheduler_cancel_prevents_the_action() {
        let runs = Arc::new(AtomicUsize::new(0));
        let seen = runs.clone();
        let handle = SystemScheduler.schedule(
            Duration::from_millis(20),
            Box::new(move || {
                seen.fetch_add(1, Ordering::SeqCst);
            }),
        );
        handle.cancel();

        let (sender, receiver) = mpsc::channel();
        let _marker = SystemScheduler.schedule(
            Duration::from_millis(60),
            Box::new(move || {
                let _ = sender.send(());
            }),
        );
        receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("a later action runs");
        assert_eq!(runs.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn system_scheduler_survives_a_panicking_action() {
        let _failing = SystemScheduler.schedule(
            Duration::ZERO,
            Box::new(|| panic!("system scheduler action failed")),
        );
        let (sender, receiver) = mpsc::channel();
        let _later = SystemScheduler.schedule(
            Duration::from_millis(10),
            Box::new(move || {
                let _ = sender.send(());
            }),
        );

        receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("the timer thread keeps running after a panic");
    }

    #[test]
    fn delayed_task_zero_delay_never_runs_inside_schedule() {
        let scheduler = VirtualTimeScheduler::new();
        let task = DelayedTask::new(scheduler.clone());
        let (log, entry) = recorder();

        task.schedule(Duration::ZERO, entry("zero"));
        assert!(lock(&log).is_empty());
        assert!(task.is_pending());

        scheduler.advance_by(Duration::ZERO);
        assert_eq!(*lock(&log), ["zero"]);
    }

    #[test]
    fn dropping_the_last_delayed_task_clone_cancels_the_pending_action() {
        let scheduler = VirtualTimeScheduler::new();
        let task = DelayedTask::new(scheduler.clone());
        let (log, entry) = recorder();
        task.schedule(Duration::from_secs(1), entry("dropped"));

        drop(task);
        scheduler.advance_by(Duration::from_secs(1));

        assert!(lock(&log).is_empty());
        assert_eq!(lock(&scheduler.shared).queue.entries.len(), 0);
    }
}
