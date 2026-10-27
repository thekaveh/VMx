//! `FormVm` readers on other threads never pair one commit's model with
//! another commit's errors (#770).
//!
//! A writer thread commits unique models whose validity alternates. A reader
//! thread reads `model()`, `is_valid()`, then `model()`. When both models are
//! the same value, no commit installed a model between the reads, so
//! `is_valid()` must match that model. Each run is bounded by time and by
//! iterations, so it finishes under load.
//!
//! A commit must not hold the error mutex while it takes the model mutex: a
//! user `Clone` runs under the model mutex and may read the errors. The last
//! test reads the errors from such a `Clone` while another thread commits,
//! and fails instead of hanging when the two deadlock.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use vmx::FormVm;

/// The longest a writer runs.
const DURATION: Duration = Duration::from_millis(1500);

/// Even models are valid and odd models are invalid.
fn odd(model: &u64) -> Option<String> {
    (model % 2 == 1).then(|| "odd".to_string())
}

/// Runs `write` until it returns `false` or [`DURATION`] passes, while
/// another thread reads the form. Returns the number of torn reads and the
/// number of reads that saw a model change between `model()` calls.
fn torn_reads(form: &FormVm<u64>, mut write: impl FnMut() -> bool) -> (usize, usize) {
    let done = Arc::new(AtomicBool::new(false));
    let reader = {
        let form = form.clone();
        let done = Arc::clone(&done);
        thread::spawn(move || {
            let (mut torn, mut moved) = (0, 0);
            while !done.load(Ordering::SeqCst) {
                let before = form.model();
                let valid = form.is_valid();
                let after = form.model();
                if before != after {
                    moved += 1;
                } else if valid != odd(&before).is_none() {
                    torn += 1;
                }
            }
            (torn, moved)
        })
    };
    let started = Instant::now();
    while started.elapsed() < DURATION && write() {}
    done.store(true, Ordering::SeqCst);
    reader.join().expect("the reader does not panic")
}

#[test]
fn readers_never_pair_a_model_with_another_models_errors() {
    let form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .validator("value", odd)
        .build()
        .unwrap();
    let mut next = 0;
    let (torn, moved) = torn_reads(&form, || {
        next += 1;
        form.set_model(next);
        next < 200_000
    });
    assert_eq!(torn, 0, "torn reads ({moved} reads saw a commit)");
}

#[test]
fn readers_never_pair_an_approval_reset_with_the_other_states_errors() {
    // Each round sets a valid model, then approves it. The reset installs
    // the next, invalid, model with its errors.
    let form = FormVm::builder()
        .initial(0)
        .persister(|_| Ok(()))
        .reset_on_approved(|model: &u64| Ok(model + 1))
        .validator("value", odd)
        .build()
        .unwrap();
    let mut round = 0;
    let (torn, moved) = torn_reads(&form, || {
        round += 1;
        form.set_model(round * 4);
        form.approve().unwrap();
        assert_eq!(form.model(), round * 4 + 1, "the approval reset the model");
        round < 50_000
    });
    assert_eq!(torn, 0, "torn reads ({moved} reads saw a commit)");
}

/// A model whose `Clone` reads the validity of the form that holds it.
struct Reentrant {
    value: u64,
    form: Arc<Mutex<Option<FormVm<Reentrant>>>>,
}

impl Clone for Reentrant {
    fn clone(&self) -> Self {
        // Release the slot before reading, so the slot adds no lock order.
        let form = self.form.lock().unwrap().clone();
        if let Some(form) = form {
            let _ = form.is_valid();
        }
        Self {
            value: self.value,
            form: Arc::clone(&self.form),
        }
    }
}

impl PartialEq for Reentrant {
    fn eq(&self, other: &Self) -> bool {
        self.value == other.value
    }
}

#[test]
fn a_clone_that_reads_the_errors_does_not_deadlock_a_commit() {
    let slot = Arc::new(Mutex::new(None));
    let form = FormVm::builder()
        .initial(Reentrant {
            value: 0,
            form: Arc::clone(&slot),
        })
        .persister(|_| Ok(()))
        .validator("value", |model: &Reentrant| odd(&model.value))
        .build()
        .unwrap();
    *slot.lock().unwrap() = Some(form.clone());
    let done = Arc::new(AtomicBool::new(false));
    let reader = {
        let form = form.clone();
        let done = Arc::clone(&done);
        thread::spawn(move || {
            while !done.load(Ordering::SeqCst) {
                let _ = form.model();
            }
        })
    };
    let (finished, result) = mpsc::channel();
    let writer = {
        let form = form.clone();
        let slot = Arc::clone(&slot);
        thread::spawn(move || {
            let started = Instant::now();
            for value in 1..20_000 {
                if started.elapsed() >= DURATION {
                    break;
                }
                form.set_model(Reentrant {
                    value,
                    form: Arc::clone(&slot),
                });
            }
            let _ = finished.send(());
        })
    };
    let outcome = result.recv_timeout(Duration::from_secs(30));
    done.store(true, Ordering::SeqCst);
    assert!(outcome.is_ok(), "a commit and a reentrant clone deadlocked");
    writer.join().expect("the writer does not panic");
    reader.join().expect("the reader does not panic");
    // Break the cycle between the form and its models.
    slot.lock().unwrap().take();
}
