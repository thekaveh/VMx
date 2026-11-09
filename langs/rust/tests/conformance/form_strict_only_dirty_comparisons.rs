//! A `FormVm` update runs its dirty comparisons only in strict mode (spec/20
//! §5.2, ADR-0216, #1355).
//!
//! A strict `set_model` compares the candidate with the live model, the live
//! model with the snapshot, and the candidate with the snapshot. A strict
//! revert runs the last two. A non-strict `set_model` runs only the first, and
//! a non-strict revert runs none. A strict update runs both dirty comparisons
//! also while the form is invalid.

use std::cell::Cell;
use std::panic::{catch_unwind, AssertUnwindSafe};

use vmx::FormVm;

thread_local! {
    /// The `PartialEq` calls made on this thread. Each test runs on its own
    /// thread, and the form compares on the calling thread.
    static COMPARISONS: Cell<usize> = const { Cell::new(0) };
}

/// Returns the comparisons made since the last call, and resets the count.
fn take_comparisons() -> usize {
    COMPARISONS.with(|count| count.replace(0))
}

/// A model whose equality counts each call, and panics on a marked value when
/// the form compares with the snapshot.
#[derive(Clone, Debug)]
struct Counted {
    value: i32,
    /// Set on the snapshotter's copies.
    marked: bool,
    /// Whether a comparison with a marked value panics.
    refuse_marked: bool,
}

impl Counted {
    fn new(value: i32) -> Self {
        Self {
            value,
            marked: false,
            refuse_marked: false,
        }
    }
}

impl PartialEq for Counted {
    fn eq(&self, other: &Self) -> bool {
        COMPARISONS.with(|count| count.set(count.get() + 1));
        assert!(
            !(self.refuse_marked || other.refuse_marked) || !(self.marked || other.marked),
            "compared with the snapshot"
        );
        self.value == other.value
    }
}

/// A form over [`Counted`] whose validator rejects negative values. The
/// snapshotter marks its copies.
fn form(strict: bool, initial: Counted) -> FormVm<Counted> {
    FormVm::builder()
        .initial(initial)
        .persister(|_| Ok(()))
        .strict(strict)
        .snapshotter(|model: &Counted| Counted {
            marked: true,
            ..model.clone()
        })
        .validator("value", |model: &Counted| {
            (model.value < 0).then(|| "negative".to_string())
        })
        .build()
        .unwrap()
}

/// FORM-045 — a strict set_model runs three equality comparisons and a strict revert two
#[test]
fn a_strict_update_runs_both_dirty_comparisons() {
    let form = form(true, Counted::new(0));
    take_comparisons();

    form.set_model(Counted::new(1));
    assert_eq!(take_comparisons(), 3, "strict set_model");
    assert_eq!(form.model().value, 1);

    form.revert();
    assert_eq!(take_comparisons(), 2, "strict revert");
    assert_eq!(form.model().value, 0);
}

/// FORM-045 — a strict update runs both dirty comparisons also while the form is invalid
#[test]
fn a_strict_update_of_an_invalid_form_runs_both_dirty_comparisons() {
    let form = form(true, Counted::new(0));
    form.set_model(Counted::new(-1));
    assert!(!form.is_valid());
    take_comparisons();

    form.set_model(Counted::new(-2));
    assert_eq!(take_comparisons(), 3, "strict set_model of an invalid form");
    assert_eq!(form.model().value, -2);

    form.revert();
    assert_eq!(take_comparisons(), 2, "strict revert of an invalid form");
    assert!(form.is_valid());
}

/// FORM-045 — a non-strict set_model runs one equality comparison and a non-strict revert none
#[test]
fn a_non_strict_update_runs_no_dirty_comparison() {
    let form = form(false, Counted::new(0));
    take_comparisons();

    form.set_model(Counted::new(1));
    assert_eq!(take_comparisons(), 1, "non-strict set_model");
    assert_eq!(form.model().value, 1);

    form.revert();
    assert_eq!(take_comparisons(), 0, "non-strict revert");
    assert_eq!(form.model().value, 0);
}

/// FORM-045 — a non-strict update commits when the comparison with the snapshot would fail
#[test]
fn a_non_strict_update_commits_when_the_snapshot_comparison_would_fail() {
    let initial = Counted {
        refuse_marked: true,
        ..Counted::new(0)
    };
    let form = form(false, initial);
    let candidate = Counted {
        refuse_marked: true,
        ..Counted::new(1)
    };

    let outcome = catch_unwind(AssertUnwindSafe(|| form.set_model(candidate)));

    assert!(
        outcome.is_ok(),
        "a non-strict update compared with the snapshot"
    );
    assert_eq!(form.model().value, 1);
    let reverted = catch_unwind(AssertUnwindSafe(|| form.revert()));
    assert!(
        reverted.is_ok(),
        "a non-strict revert compared with the snapshot"
    );
    assert_eq!(form.model().value, 0);
}
