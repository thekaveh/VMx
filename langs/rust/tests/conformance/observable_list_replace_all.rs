use std::panic::{catch_unwind, AssertUnwindSafe};

use vmx::{CollectionChangeAction, Message, MessageHub, ObservableList};

fn changes_since(hub: &MessageHub, start: usize) -> Vec<&'static str> {
    hub.history()[start..]
        .iter()
        .filter_map(|message| match message {
            Message::CollectionChanged(change) => Some(match change.action {
                CollectionChangeAction::Reset => "reset",
                CollectionChangeAction::Add => "add",
                CollectionChangeAction::Remove => "remove",
                CollectionChangeAction::Replace => "replace",
                CollectionChangeAction::Move => "move",
            }),
            Message::PropertyChanged(change) if change.property_name == "Count" => Some("Count"),
            _ => None,
        })
        .collect()
}

fn populated(items: &[i32]) -> (ObservableList<i32>, MessageHub, usize) {
    let hub = MessageHub::new();
    let list = ObservableList::new(1, hub.clone());
    for item in items {
        list.push(*item);
    }
    let start = hub.history().len();
    (list, hub, start)
}

/// COL-040 — replace_all growth emits one Reset and Count.
#[test]
fn replace_all_growth_emits_reset_and_count() {
    let (list, hub, start) = populated(&[1]);
    list.replace_all([2, 3, 4]);
    assert_eq!(list.to_vec(), vec![2, 3, 4]);
    assert_eq!(changes_since(&hub, start), vec!["reset", "Count"]);
}

/// COL-041 — replace_all shrink emits one Reset and Count.
#[test]
fn replace_all_shrink_emits_reset_and_count() {
    let (list, hub, start) = populated(&[1, 2, 3]);
    list.replace_all([9]);
    assert_eq!(changes_since(&hub, start), vec!["reset", "Count"]);
}

/// COL-042 — equal count and identical contents emit Reset without Count.
#[test]
fn replace_all_equal_count_and_identical_emit_reset() {
    let (list, hub, start) = populated(&[1, 2]);
    list.replace_all([3, 4]);
    list.replace_all([3, 4]);
    assert_eq!(changes_since(&hub, start), vec!["reset", "reset"]);

    #[derive(Clone)]
    struct NonEquatable;
    let unconstrained = ObservableList::new(2, MessageHub::new());
    unconstrained.push(NonEquatable);
    unconstrained.replace_all([NonEquatable]);
}

/// COL-043 — empty-to-empty is silent; non-empty-to-empty is effective.
#[test]
fn replace_all_empty_cases() {
    let (empty, empty_hub, empty_start) = populated(&[]);
    empty.replace_all(Vec::<i32>::new());
    assert!(changes_since(&empty_hub, empty_start).is_empty());
    let (list, hub, start) = populated(&[1]);
    list.replace_all(Vec::<i32>::new());
    assert_eq!(changes_since(&hub, start), vec!["reset", "Count"]);
}

/// COL-044 — replace_all materializes input before mutation.
#[test]
fn replace_all_snapshots_input() {
    let (list, hub, start) = populated(&[1, 2, 3]);
    list.replace_all(list.to_vec());
    assert_eq!(list.to_vec(), vec![1, 2, 3]);
    assert_eq!(changes_since(&hub, start), vec!["reset"]);
}

/// COL-045 — nested replacement emits only the outermost Reset.
#[test]
fn replace_all_nested_batch_coalesces() {
    let (list, hub, start) = populated(&[1]);
    list.batch_update(|| {
        list.replace_all([2, 3]);
        assert!(changes_since(&hub, start).is_empty());
    });
    assert_eq!(changes_since(&hub, start), vec!["reset", "Count"]);
}

/// COL-046 — panic exit restores batch depth and publishes the mutation.
#[test]
fn replace_all_panic_exit_restores_batch() {
    let (list, hub, start) = populated(&[1]);
    let result = catch_unwind(AssertUnwindSafe(|| {
        list.batch_update(|| {
            list.replace_all([2, 3]);
            panic!("boom");
        });
    }));
    assert!(result.is_err());
    assert_eq!(changes_since(&hub, start), vec!["reset", "Count"]);
    list.replace_all([4, 5]);
    assert_eq!(changes_since(&hub, start), vec!["reset", "Count", "reset"]);
}

/// COL-047 — Reset precedes Count and both observe final state.
#[test]
fn replace_all_ordering_and_final_state() {
    let (list, hub, start) = populated(&[1]);
    list.replace_all([7, 8]);
    assert_eq!(list.to_vec(), vec![7, 8]);
    assert_eq!(changes_since(&hub, start), vec!["reset", "Count"]);
}

#[test]
fn replace_all_panicking_iterator_is_atomic() {
    struct FailingIterator(bool);

    impl Iterator for FailingIterator {
        type Item = i32;

        fn next(&mut self) -> Option<Self::Item> {
            if self.0 {
                panic!("iteration failed");
            }
            self.0 = true;
            Some(9)
        }
    }

    let (list, hub, start) = populated(&[1, 2]);
    let result = catch_unwind(AssertUnwindSafe(|| {
        list.replace_all(FailingIterator(false));
    }));

    assert!(result.is_err());
    assert_eq!(list.to_vec(), vec![1, 2]);
    assert!(changes_since(&hub, start).is_empty());
}
