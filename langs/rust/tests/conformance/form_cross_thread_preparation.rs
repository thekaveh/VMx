//! A `FormVm` holds no lock while a consumer callback runs (spec/20 §5.1,
//! §5.3, §5.4 and §5.5, ADR-0215, #1427, #1452, #1426).
//!
//! Another thread's call proceeds while a preparation runs, and the overtaken
//! update runs again as a new call. A `dispose()` from another thread during
//! a preparation defers its teardown until the preparing call returns.
//! Another thread's edit during the post-persist commit commits at once, and
//! the reset overwrites it. A call in its own pre-publication window does not
//! wait for another thread's scope. Every cross-thread wait is bounded, so a
//! regression fails instead of hanging.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::Duration;

use vmx::FormVm;

/// How long a test waits for a call that must not block.
const BOUND: Duration = Duration::from_secs(5);

/// The model an approval's reset installs.
const RESET: i32 = 100;

/// Lets a callback registered at build time reach the form built from it.
#[derive(Clone, Default)]
struct Slot(Arc<OnceLock<FormVm<i32>>>);

impl Slot {
    fn form(&self) -> FormVm<i32> {
        self.0.get().expect("the form is built").clone()
    }

    fn fill(&self, form: &FormVm<i32>) {
        assert!(self.0.set(form.clone()).is_ok());
    }
}

/// Runs `nested` only the first time it is called.
fn once(nested: impl Fn() + Send + Sync + 'static) -> impl Fn() + Send + Sync + 'static {
    let armed = AtomicBool::new(true);
    move || {
        if armed.swap(false, Ordering::SeqCst) {
            nested();
        }
    }
}

/// A one-shot signal between threads.
struct Signal {
    sender: Mutex<Sender<()>>,
    receiver: Mutex<Receiver<()>>,
}

impl Signal {
    fn new() -> Arc<Self> {
        let (sender, receiver) = mpsc::channel();
        Arc::new(Self {
            sender: Mutex::new(sender),
            receiver: Mutex::new(receiver),
        })
    }

    fn raise(&self) {
        let _ = self.sender.lock().unwrap().send(());
    }

    /// Waits for the signal for at most [`BOUND`], and reports whether it
    /// came.
    fn wait(&self) -> bool {
        self.receiver.lock().unwrap().recv_timeout(BOUND).is_ok()
    }

    /// Waits for a release that the test sends after a [`wait`](Self::wait)
    /// timed out, so a gate never opens before that check ends.
    fn wait_for_release(&self) -> bool {
        self.receiver
            .lock()
            .unwrap()
            .recv_timeout(4 * BOUND)
            .is_ok()
    }
}

/// Runs `call` on a new thread from a validator of `form`, and reports
/// whether it returned within [`BOUND`] while the validator waited.
fn from_another_thread(
    form: &Slot,
    call: impl Fn(&FormVm<i32>) + Send + Sync + 'static,
) -> impl Fn() -> bool {
    let call = Arc::new(call);
    let form = form.clone();
    move || {
        let done = Signal::new();
        let (form, call, signal) = (form.form(), Arc::clone(&call), Arc::clone(&done));
        thread::spawn(move || {
            call(&form);
            signal.raise();
        });
        done.wait()
    }
}

/// #1427 — another thread's set_model from a validator's join commits, and the overtaken update runs again
#[test]
fn another_threads_update_during_a_preparation_commits_and_the_update_runs_again() {
    let slot = Slot::default();
    let read = Arc::new(Mutex::new(None));
    let joined = Arc::new(Mutex::new(None));
    let run = from_another_thread(&slot, {
        let read = read.clone();
        move |form| {
            *read.lock().unwrap() = Some(form.model());
            form.set_model(2);
        }
    });
    let hook = once({
        let joined = joined.clone();
        move || *joined.lock().unwrap() = Some(run())
    });
    let validations = Arc::new(Mutex::new(Vec::new()));
    let form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .validator("value", {
            let validations = validations.clone();
            move |model: &i32| {
                validations.lock().unwrap().push(*model);
                if *model == 1 {
                    hook();
                }
                None
            }
        })
        .build()
        .unwrap();
    slot.fill(&form);
    validations.lock().unwrap().clear();

    form.set_model(1);

    assert_eq!(
        *joined.lock().unwrap(),
        Some(true),
        "the other thread blocked"
    );
    assert_eq!(*read.lock().unwrap(), Some(0));
    assert_eq!(form.model(), 1);
    // The overtaken update validated `1` again, against the new state.
    assert_eq!(*validations.lock().unwrap(), [1, 2, 1]);
}

/// #1427 — another thread's set_model during a revert's preparation commits, and the revert runs again
#[test]
fn another_threads_update_during_a_revert_commits_and_the_revert_runs_again() {
    let slot = Slot::default();
    let joined = Arc::new(Mutex::new(None));
    let armed = Arc::new(AtomicBool::new(false));
    let run = from_another_thread(&slot, |form| form.set_model(2));
    let hook = once({
        let joined = joined.clone();
        move || *joined.lock().unwrap() = Some(run())
    });
    let form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .validator("value", {
            let armed = armed.clone();
            move |model: &i32| {
                if *model == 0 && armed.load(Ordering::SeqCst) {
                    hook();
                }
                None
            }
        })
        .build()
        .unwrap();
    slot.fill(&form);
    form.set_model(5);
    armed.store(true, Ordering::SeqCst);

    form.revert();

    assert_eq!(
        *joined.lock().unwrap(),
        Some(true),
        "the other thread blocked"
    );
    assert_eq!(form.model(), 0);
    assert!(!form.is_dirty());
}

/// #1427 — another thread's dispose() during a preparation returns; the teardown runs when the update returns
#[test]
fn another_threads_dispose_during_a_preparation_defers_the_teardown() {
    let slot = Slot::default();
    let joined = Arc::new(Mutex::new(None));
    let completed = Arc::new(AtomicBool::new(false));
    let completed_in_validator = Arc::new(Mutex::new(None));
    let run = from_another_thread(&slot, |form| form.dispose());
    let hook = once({
        let (joined, completed, completed_in_validator) = (
            joined.clone(),
            completed.clone(),
            completed_in_validator.clone(),
        );
        move || {
            *joined.lock().unwrap() = Some(run());
            *completed_in_validator.lock().unwrap() = Some(completed.load(Ordering::SeqCst));
        }
    });
    let form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .validator("value", move |model: &i32| {
            if *model == 1 {
                hook();
            }
            (*model == 1).then(|| "one".to_string())
        })
        .build()
        .unwrap();
    slot.fill(&form);
    let _completion = form.errors_changed().subscribe_with_completion(|_| {}, {
        let completed = completed.clone();
        move || completed.store(true, Ordering::SeqCst)
    });

    form.set_model(1);

    assert_eq!(*joined.lock().unwrap(), Some(true), "dispose() blocked");
    assert_eq!(*completed_in_validator.lock().unwrap(), Some(false));
    assert!(completed.load(Ordering::SeqCst), "the teardown did not run");
    assert_eq!(form.model(), 0, "the disposed form committed");
    assert!(form.is_valid());
}

/// Which call the other thread makes during the post-persist commit.
#[derive(Clone, Copy)]
enum Edit {
    SetModel,
    Revert,
}

/// Which post-persist callback blocks while the other thread calls.
#[derive(Clone, Copy)]
enum Blocked {
    Reset,
    Validator,
}

/// Approves on thread A while `blocked` waits, and makes `edit` on thread B.
/// Returns whether B's call returned while A's callback was blocked.
fn edit_during_the_post_persist_commit(edit: Edit, blocked: Blocked) -> (bool, FormVm<i32>) {
    let entered = Signal::new();
    let release = Signal::new();
    let gate = {
        let (entered, release) = (entered.clone(), release.clone());
        once(move || {
            entered.raise();
            assert!(
                release.wait_for_release(),
                "the test never released the callback"
            );
        })
    };
    let gate = Arc::new(gate);
    let form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .reset_on_approved({
            let gate = Arc::clone(&gate);
            move |_| {
                if matches!(blocked, Blocked::Reset) {
                    gate();
                }
                Ok(RESET)
            }
        })
        .validator("value", {
            let gate = Arc::clone(&gate);
            move |model: &i32| {
                if *model == RESET && matches!(blocked, Blocked::Validator) {
                    gate();
                }
                None
            }
        })
        .build()
        .unwrap();
    form.set_model(5);
    let approving = thread::spawn({
        let form = form.clone();
        move || form.approve()
    });
    assert!(entered.wait(), "the post-persist callback never ran");
    let returned = Signal::new();
    thread::spawn({
        let (form, returned) = (form.clone(), returned.clone());
        move || {
            match edit {
                Edit::SetModel => form.set_model(7),
                Edit::Revert => form.revert(),
            }
            returned.raise();
        }
    });
    let edit_returned = returned.wait();
    release.raise();
    assert_eq!(approving.join().unwrap(), Ok(()));
    assert!(edit_returned || returned.wait(), "the edit never returned");
    (edit_returned, form)
}

fn check_post_persist_edit(edit: Edit, blocked: Blocked) {
    let (edit_returned, form) = edit_during_the_post_persist_commit(edit, blocked);
    assert!(edit_returned, "the edit waited for the post-persist commit");
    assert_eq!(form.model(), RESET, "the reset did not overwrite the edit");
    assert_eq!(form.snapshot(), RESET);
    assert!(!form.is_dirty());
}

/// #1452 — another thread's set_model while the reset callback runs commits at once, and the reset overwrites it
#[test]
fn a_set_model_during_the_reset_callback_is_overwritten_by_the_reset() {
    check_post_persist_edit(Edit::SetModel, Blocked::Reset);
}

/// #1452 — another thread's revert while the reset callback runs commits at once, and the reset overwrites it
#[test]
fn a_revert_during_the_reset_callback_is_overwritten_by_the_reset() {
    check_post_persist_edit(Edit::Revert, Blocked::Reset);
}

/// #1452 — another thread's set_model while the reset model's validator runs commits at once, and the reset overwrites it
#[test]
fn a_set_model_during_the_reset_validation_is_overwritten_by_the_reset() {
    check_post_persist_edit(Edit::SetModel, Blocked::Validator);
}

/// #1452 — another thread's revert while the reset model's validator runs commits at once, and the reset overwrites it
#[test]
fn a_revert_during_the_reset_validation_is_overwritten_by_the_reset() {
    check_post_persist_edit(Edit::Revert, Blocked::Validator);
}

/// Thread B holds an update scope while its `errors_changed` observer waits.
/// Thread A's approval reset callback makes `edit`, in A's own
/// pre-publication window. Returns whether the edit returned while B's scope
/// was open, and the form after both threads finished.
fn edit_in_the_own_window_while_another_thread_publishes(edit: Edit) -> (bool, FormVm<i32>) {
    let slot = Slot::default();
    let persisting = Signal::new();
    let persist = Signal::new();
    let in_scope = Signal::new();
    let close_scope = Signal::new();
    let edit_returned = Signal::new();
    let form = FormVm::builder()
        .initial(0)
        .persister({
            let (persisting, persist) = (persisting.clone(), persist.clone());
            move |_: &i32| {
                persisting.raise();
                assert!(
                    persist.wait_for_release(),
                    "the test never released the persister"
                );
                Ok(())
            }
        })
        .reset_on_approved({
            let (slot, edit_returned) = (slot.clone(), edit_returned.clone());
            move |_| {
                let form = slot.form();
                match edit {
                    Edit::SetModel => form.set_model(9),
                    Edit::Revert => form.revert(),
                }
                edit_returned.raise();
                Ok(RESET)
            }
        })
        .validator("value", |model: &i32| {
            (*model < 0).then(|| "negative".to_string())
        })
        .build()
        .unwrap();
    slot.fill(&form);
    form.set_model(5);
    let hold = once({
        let (in_scope, close_scope) = (in_scope.clone(), close_scope.clone());
        move || {
            in_scope.raise();
            assert!(
                close_scope.wait_for_release(),
                "the test never closed the scope"
            );
        }
    });
    let _observer = form.errors_changed().subscribe(move |_| hold());

    let approving = thread::spawn({
        let form = form.clone();
        move || form.approve()
    });
    assert!(persisting.wait(), "the persister never ran");
    let publishing = thread::spawn({
        let form = form.clone();
        move || form.set_model(-1)
    });
    assert!(in_scope.wait(), "thread B never opened its scope");
    persist.raise();
    let returned = edit_returned.wait();
    close_scope.raise();
    publishing.join().unwrap();
    assert_eq!(approving.join().unwrap(), Ok(()));
    (returned, form)
}

/// #1426 — a set_model in the caller's own pre-publication window does not wait for another thread's scope
#[test]
fn a_set_model_in_the_own_window_does_not_wait_for_another_threads_scope() {
    let (returned, form) = edit_in_the_own_window_while_another_thread_publishes(Edit::SetModel);
    assert!(returned, "the queued set_model waited for the other scope");
    // The queued call replays after the approval subscribers.
    assert_eq!(form.model(), 9);
    assert_eq!(form.snapshot(), RESET);
}

/// #1426 — a revert in the caller's own pre-publication window does not wait for another thread's scope
#[test]
fn a_revert_in_the_own_window_does_not_wait_for_another_threads_scope() {
    let (returned, form) = edit_in_the_own_window_while_another_thread_publishes(Edit::Revert);
    assert!(returned, "the queued revert waited for the other scope");
    assert_eq!(form.model(), RESET);
    assert_eq!(form.snapshot(), RESET);
}
