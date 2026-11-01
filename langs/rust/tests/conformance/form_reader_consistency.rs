//! `FormVm` readers on other threads never pair one commit's model with
//! another commit's errors (#770). They also never pair a model with a
//! snapshot it never coexisted with (#1073).
//!
//! A writer thread commits unique models whose validity alternates. A reader
//! thread reads `model()`, `is_valid()`, then `model()`. When both models are
//! the same value, no commit installed a model between the reads, so
//! `is_valid()` must match that model. Each run is bounded by time and by
//! iterations, so it finishes under load.
//!
//! A commit must not hold the error mutex while it takes the model mutex. A
//! user `Clone` runs under the model mutex and may read the errors.
//! `a_clone_that_reads_the_errors_does_not_deadlock_a_commit` reads the errors
//! from such a `Clone` while another thread commits, and fails instead of
//! hanging when the two deadlock.

use std::cell::Cell;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
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

/// #1073 — a reset approval replaces the snapshot and the model together. A
/// form whose approvals only reset it is always clean, so no `is_dirty()` read
/// on another thread may return `true`.
#[test]
fn readers_never_see_a_clean_reset_approval_as_dirty() {
    let form = FormVm::builder()
        .initial(2)
        .persister(|_| Ok(()))
        .reset_on_approved(|model: &u64| Ok(model + 1))
        .build()
        .unwrap();
    let done = Arc::new(AtomicBool::new(false));
    let reader = {
        let form = form.clone();
        let done = Arc::clone(&done);
        thread::spawn(move || {
            let (mut reads, mut dirty) = (0_usize, 0_usize);
            while !done.load(Ordering::SeqCst) {
                reads += 1;
                if form.is_dirty() {
                    dirty += 1;
                }
            }
            (reads, dirty)
        })
    };
    let started = Instant::now();
    let mut approvals = 0;
    while started.elapsed() < DURATION && approvals < 50_000 {
        form.approve().unwrap();
        approvals += 1;
    }
    done.store(true, Ordering::SeqCst);
    let (reads, dirty) = reader.join().expect("the reader does not panic");

    assert!(!form.is_dirty());
    assert_eq!(
        dirty, 0,
        "{dirty} of {reads} reads during {approvals} approvals saw a dirty form"
    );
}

/// #1073 review — an approval only advances the snapshot, while its
/// persister edits the model. Every committed state is dirty, so no
/// `is_dirty()` read on another thread may return `false`.
#[test]
fn readers_never_see_an_edited_form_as_clean_while_approvals_advance_the_snapshot() {
    let slot: Arc<Mutex<Option<FormVm<u64>>>> = Arc::new(Mutex::new(None));
    let form = FormVm::builder()
        .initial(1)
        .persister({
            let slot = Arc::clone(&slot);
            move |model: &u64| {
                let form = slot.lock().unwrap().clone();
                if let Some(form) = form {
                    // The model stays one ahead of the snapshot.
                    form.set_model(model + 1);
                }
                Ok(())
            }
        })
        .build()
        .unwrap();
    form.set_model(2);
    *slot.lock().unwrap() = Some(form.clone());
    let done = Arc::new(AtomicBool::new(false));
    let reader = {
        let form = form.clone();
        let done = Arc::clone(&done);
        thread::spawn(move || {
            let (mut reads, mut clean) = (0_usize, 0_usize);
            while !done.load(Ordering::SeqCst) {
                reads += 1;
                if !form.is_dirty() {
                    clean += 1;
                }
            }
            (reads, clean)
        })
    };
    let started = Instant::now();
    let mut approvals = 0;
    while started.elapsed() < DURATION && approvals < 200_000 {
        form.approve().unwrap();
        approvals += 1;
        assert_eq!(
            form.model(),
            form.snapshot() + 1,
            "every committed state is dirty"
        );
    }
    done.store(true, Ordering::SeqCst);
    let (reads, clean) = reader.join().expect("the reader does not panic");
    slot.lock().unwrap().take();

    assert_eq!(
        clean, 0,
        "{clean} of {reads} reads during {approvals} approvals saw a clean form"
    );
}

thread_local! {
    static IN_EQ: Cell<bool> = const { Cell::new(false) };
}

/// A model whose `PartialEq` reads the model, the snapshot and the dirty
/// state of the form that holds it. Its `Clone` reads the form's validity.
/// `model()` and `snapshot()` clone under their own mutex, so a `Clone` that
/// read either of them would block on itself.
struct Probing {
    value: u64,
    form: Arc<Mutex<Option<FormVm<Probing>>>>,
    reads: Arc<AtomicUsize>,
}

impl Probing {
    fn new(
        value: u64,
        form: &Arc<Mutex<Option<FormVm<Probing>>>>,
        reads: &Arc<AtomicUsize>,
    ) -> Self {
        Self {
            value,
            form: Arc::clone(form),
            reads: Arc::clone(reads),
        }
    }

    fn form(&self) -> Option<FormVm<Probing>> {
        // Release the slot before reading, so the slot adds no lock order.
        self.form.lock().unwrap().clone()
    }
}

impl Clone for Probing {
    fn clone(&self) -> Self {
        if let Some(form) = self.form() {
            let _ = form.is_valid();
        }
        Self::new(self.value, &self.form, &self.reads)
    }
}

impl PartialEq for Probing {
    fn eq(&self, other: &Self) -> bool {
        // The nested `is_dirty` runs `eq` again; read the form only once.
        if !IN_EQ.with(Cell::get) {
            if let Some(form) = self.form() {
                IN_EQ.with(|flag| flag.set(true));
                let _ = form.model();
                let _ = form.snapshot();
                let _ = form.is_dirty();
                IN_EQ.with(|flag| flag.set(false));
                self.reads.fetch_add(1, Ordering::SeqCst);
            }
        }
        self.value == other.value
    }
}

/// #1073 — `is_dirty()` holds no lock while `PartialEq` runs. A `PartialEq`
/// that reads the form gets a result, also while reset approvals commit on
/// another thread.
#[test]
fn is_dirty_returns_while_partial_eq_reads_the_form() {
    let slot = Arc::new(Mutex::new(None));
    let reads = Arc::new(AtomicUsize::new(0));
    let form = FormVm::builder()
        .initial(Probing::new(2, &slot, &reads))
        .persister(|_| Ok(()))
        .reset_on_approved({
            let (slot, reads) = (Arc::clone(&slot), Arc::clone(&reads));
            move |model: &Probing| Ok(Probing::new(model.value + 1, &slot, &reads))
        })
        .build()
        .unwrap();
    *slot.lock().unwrap() = Some(form.clone());
    let done = Arc::new(AtomicBool::new(false));
    let writer = {
        let (form, done) = (form.clone(), Arc::clone(&done));
        thread::spawn(move || {
            while !done.load(Ordering::SeqCst) {
                form.approve().unwrap();
            }
        })
    };
    let (finished, result) = mpsc::channel();
    let reader = {
        let form = form.clone();
        thread::spawn(move || {
            let started = Instant::now();
            let mut dirty = 0;
            while started.elapsed() < DURATION {
                if form.is_dirty() {
                    dirty += 1;
                }
            }
            let _ = finished.send(dirty);
        })
    };
    let outcome = result.recv_timeout(Duration::from_secs(30));
    done.store(true, Ordering::SeqCst);

    assert_eq!(
        outcome,
        Ok(0),
        "is_dirty returns and never sees a dirty form"
    );
    assert!(reads.load(Ordering::SeqCst) > 0, "PartialEq read the form");
    reader.join().expect("the reader does not panic");
    writer.join().expect("the writer does not panic");
    // Break the cycle between the form and its models.
    slot.lock().unwrap().take();
}
