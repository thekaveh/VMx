//! COL-065 — a token-paged refresh keeps `items` and `current_token`
//! describing one loaded prefix (spec 21 §6.2, ADR-0136).

use std::sync::{
    atomic::{AtomicBool, Ordering},
    mpsc, Arc, Mutex,
};
use vmx::{
    CollectionChangeAction, ComponentVm, ConstructionStatus, Message, MessageHub, Subscription,
    TokenPagedComposition,
};

type Page = (Vec<i32>, Option<&'static str>);

/// First page can change between calls; later pages are keyed by token.
#[derive(Clone)]
struct Backend {
    requested: Arc<Mutex<Vec<Option<&'static str>>>>,
    first_page: Arc<Mutex<Page>>,
}

impl Backend {
    fn new() -> Self {
        Self {
            requested: Arc::new(Mutex::new(Vec::new())),
            first_page: Arc::new(Mutex::new((vec![1, 2], Some("t2")))),
        }
    }

    fn set_first_page(&self, page: Page) {
        *self.first_page.lock().unwrap() = page;
    }

    fn requested(&self) -> Vec<Option<&'static str>> {
        self.requested.lock().unwrap().clone()
    }

    fn fetch(&self, token: Option<&'static str>) -> Page {
        self.requested.lock().unwrap().push(token);
        match token {
            None => self.first_page.lock().unwrap().clone(),
            Some("t2") => (vec![3, 4], Some("t3")),
            Some("t3") => (vec![5, 6], Some("t4")),
            Some("t4") => (vec![7], None),
            Some(other) => panic!("unexpected token {other}"),
        }
    }

    fn pager(&self) -> TokenPagedComposition<i32, &'static str> {
        let backend = self.clone();
        TokenPagedComposition::with_loader(None, move |token| backend.fetch(token))
    }
}

fn load(pages: &TokenPagedComposition<i32, &'static str>, count: usize) {
    for _ in 0..count {
        pages.load_next();
    }
}

struct Trace {
    entries: Arc<Mutex<Vec<String>>>,
    _hub: Subscription,
    _command: Subscription,
}

impl Trace {
    fn entries(&self) -> Vec<String> {
        self.entries.lock().unwrap().clone()
    }

    fn resets(&self) -> usize {
        self.entries()
            .iter()
            .filter(|entry| entry.as_str() == "collection:Reset")
            .count()
    }
}

fn trace(pages: &TokenPagedComposition<i32, &'static str>) -> Trace {
    let entries = Arc::new(Mutex::new(Vec::new()));
    let hub_entries = entries.clone();
    let hub = pages.hub().subscribe(move |message| match message {
        Message::CollectionChanged(change) if change.action == CollectionChangeAction::Reset => {
            hub_entries
                .lock()
                .unwrap()
                .push("collection:Reset".to_string());
        }
        Message::PropertyChanged(change) => {
            hub_entries
                .lock()
                .unwrap()
                .push(format!("property:{}", change.property_name));
        }
        _ => {}
    });
    let command_entries = entries.clone();
    let command = pages
        .load_more_command()
        .can_execute_changed()
        .subscribe(move |_| {
            command_entries
                .lock()
                .unwrap()
                .push("load_more:can_execute_changed".to_string());
        });
    Trace {
        entries,
        _hub: hub,
        _command: command,
    }
}

/// COL-065 — token-paged refresh keeps the cursor aligned with the retained accumulator
#[test]
fn unchanged_head_refresh_keeps_cursor_so_load_more_never_refetches_page_two() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 3);

    pages.refresh();

    assert_eq!(pages.items(), vec![1, 2, 3, 4, 5, 6]);
    assert_eq!(pages.current_token(), Some("t4"));
    assert!(pages.has_more());

    pages.load_next();

    assert_eq!(pages.items(), vec![1, 2, 3, 4, 5, 6, 7]);
    assert_eq!(
        backend.requested(),
        vec![None, Some("t2"), Some("t3"), None, Some("t4")]
    );
    assert_eq!(pages.current_token(), None);
    assert!(!pages.has_more());
}

/// COL-065 — a shorter matching non-terminal head keeps the accumulator and cursor
#[test]
fn shorter_matching_non_terminal_head_keeps_accumulator_and_cursor() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 2);
    backend.set_first_page((vec![1], Some("u1")));

    pages.refresh();

    assert_eq!(pages.items(), vec![1, 2, 3, 4]);
    assert_eq!(pages.current_token(), Some("t3"));
}

/// COL-065 — an unchanged single page adopts a changed opaque token
#[test]
fn unchanged_single_page_adopts_changed_opaque_token_without_reset() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 1);
    backend.set_first_page((vec![1, 2], Some("fresh-t2")));
    let trace = trace(&pages);

    pages.refresh();

    assert_eq!(pages.items(), vec![1, 2]);
    assert_eq!(pages.current_token(), Some("fresh-t2"));
    assert_eq!(trace.resets(), 0);
}

/// COL-065 — an unchanged single page adopts a newly terminal token
#[test]
fn unchanged_single_page_adopts_newly_terminal_token() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 1);
    backend.set_first_page((vec![1, 2], None));

    pages.refresh();

    assert_eq!(pages.items(), vec![1, 2]);
    assert_eq!(pages.current_token(), None);
    assert!(!pages.has_more());
    assert!(!pages.load_more_command().can_execute());
}

/// COL-065 — a changed head replaces the accumulator and adopts the refreshed token
#[test]
fn changed_head_replaces_accumulator_and_adopts_refreshed_token() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 2);
    backend.set_first_page((vec![9, 2], Some("u2")));
    let trace = trace(&pages);

    pages.refresh();

    assert_eq!(pages.items(), vec![9, 2]);
    assert_eq!(pages.current_token(), Some("u2"));
    assert_eq!(trace.resets(), 1);
}

/// COL-065 — a terminal first page shorter than the accumulator replaces it
#[test]
fn terminal_first_page_shorter_than_accumulator_replaces_it() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 2);
    backend.set_first_page((vec![1, 2], None));

    pages.refresh();

    assert_eq!(pages.items(), vec![1, 2]);
    assert_eq!(pages.current_token(), None);
    assert!(!pages.has_more());
}

/// COL-065 — an empty terminal first page clears a non-empty accumulator
#[test]
fn empty_terminal_first_page_clears_non_empty_accumulator() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 2);
    backend.set_first_page((Vec::new(), None));
    let trace = trace(&pages);

    pages.refresh();

    assert!(pages.items().is_empty());
    assert_eq!(pages.current_token(), None);
    assert!(!pages.has_more());
    assert_eq!(trace.resets(), 1);
}

/// COL-065 — an empty first page with a continuation replaces and adopts the token
#[test]
fn empty_first_page_with_continuation_replaces_and_adopts_token() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 2);
    backend.set_first_page((Vec::new(), Some("u1")));

    pages.refresh();

    assert!(pages.items().is_empty());
    assert_eq!(pages.current_token(), Some("u1"));
    assert!(pages.has_more());
}

/// COL-065 — a refresh after reaching the end keeps the terminal cursor
#[test]
fn refresh_after_reaching_the_end_keeps_terminal_cursor() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 4);
    let trace = trace(&pages);

    pages.refresh();

    assert_eq!(pages.items(), vec![1, 2, 3, 4, 5, 6, 7]);
    assert_eq!(pages.current_token(), None);
    assert!(!pages.has_more());
    assert!(!pages.load_more_command().can_execute());
    assert_eq!(trace.resets(), 0);
}

/// COL-065 — the no-mutation branch publishes properties, then the command signal
#[test]
fn no_mutation_branch_publishes_properties_then_command_signal() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 3);
    let trace = trace(&pages);

    pages.refresh();

    assert_eq!(
        trace.entries(),
        vec![
            "property:items",
            "property:current_token",
            "property:has_more",
            "load_more:can_execute_changed",
        ]
    );
}

/// COL-065 — the replacement branch publishes one reset, properties, then the command signal
#[test]
fn replacement_branch_publishes_reset_properties_then_command_signal() {
    let backend = Backend::new();
    let pages = backend.pager();
    load(&pages, 3);
    backend.set_first_page((vec![8, 9], Some("u2")));
    let trace = trace(&pages);

    pages.refresh();

    assert_eq!(
        trace.entries(),
        vec![
            "collection:Reset",
            "property:items",
            "property:current_token",
            "property:has_more",
            "load_more:can_execute_changed",
        ]
    );
}

/// Builds a pager whose `blocked` call (0-based) waits for `release` after
/// signalling `started`; every other call goes straight to `backend`.
fn pager_with_blocked_call(
    backend: &Backend,
    blocked: usize,
    result: Page,
) -> (
    TokenPagedComposition<i32, &'static str>,
    mpsc::Receiver<()>,
    mpsc::Sender<()>,
) {
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel::<()>();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let calls = Arc::new(Mutex::new(0usize));
    let backend = backend.clone();
    let pages = TokenPagedComposition::with_loader(None, move |token| {
        let call = {
            let mut calls = calls.lock().unwrap();
            *calls += 1;
            *calls - 1
        };
        if call == blocked {
            backend.requested.lock().unwrap().push(token);
            started_tx.send(()).unwrap();
            release_rx.lock().unwrap().recv().unwrap();
            return result.clone();
        }
        backend.fetch(token)
    });
    (pages, started_rx, release_tx)
}

#[test]
fn load_started_during_refresh_makes_the_refresh_result_stale() {
    let backend = Backend::new();
    let (pages, started, release) = pager_with_blocked_call(&backend, 1, (vec![9], Some("stale")));
    pages.load_next();
    let refreshing = pages.clone();
    let refresh = std::thread::spawn(move || refreshing.refresh());
    started.recv().unwrap();

    pages.load_next();
    release.send(()).unwrap();
    refresh.join().unwrap();

    assert_eq!(backend.requested(), vec![None, None, Some("t2")]);
    assert_eq!(pages.items(), vec![1, 2, 3, 4]);
    assert_eq!(pages.current_token(), Some("t3"));
}

#[test]
fn load_finishing_after_a_later_refresh_is_stale() {
    let backend = Backend::new();
    let (pages, started, release) = pager_with_blocked_call(&backend, 1, (vec![3, 4], Some("t3")));
    pages.load_next();
    let loading = pages.clone();
    let load = std::thread::spawn(move || loading.load_next());
    started.recv().unwrap();
    backend.set_first_page((vec![8, 9], Some("u2")));

    pages.refresh();
    release.send(()).unwrap();
    load.join().unwrap();

    assert_eq!(pages.items(), vec![8, 9]);
    assert_eq!(pages.current_token(), Some("u2"));
}

#[test]
fn panicking_refresh_loader_leaves_items_cursor_and_notifications_untouched() {
    let backend = Backend::new();
    let fail = Arc::new(AtomicBool::new(false));
    let pages = TokenPagedComposition::with_loader(None, {
        let backend = backend.clone();
        let fail = fail.clone();
        move |token| {
            assert!(!fail.load(Ordering::SeqCst), "offline");
            backend.fetch(token)
        }
    });
    load(&pages, 2);
    fail.store(true, Ordering::SeqCst);
    let trace = trace(&pages);

    let outcome = pages.refresh_command().execute_async().join();

    assert!(outcome.is_err());
    assert_eq!(pages.items(), vec![1, 2, 3, 4]);
    assert_eq!(pages.current_token(), Some("t3"));
    assert!(trace.entries().is_empty());
    assert!(!pages.refresh_command().is_executing());
}

#[derive(Clone, Debug)]
struct Fragile {
    value: i32,
    fail: Arc<AtomicBool>,
}

impl PartialEq for Fragile {
    fn eq(&self, other: &Self) -> bool {
        assert!(!self.fail.load(Ordering::SeqCst), "comparer failed");
        self.value == other.value
    }
}

#[test]
fn panicking_item_equality_leaves_items_cursor_and_notifications_untouched() {
    let fail = Arc::new(AtomicBool::new(false));
    let item = {
        let fail = fail.clone();
        move |value| Fragile {
            value,
            fail: fail.clone(),
        }
    };
    let pages = TokenPagedComposition::with_loader(None, move |token| match token {
        None => (vec![item(1), item(2)], Some("t2")),
        Some(_) => (vec![item(3), item(4)], Some("t3")),
    });
    pages.load_next();
    pages.load_next();
    fail.store(true, Ordering::SeqCst);
    let resets = Arc::new(Mutex::new(0usize));
    let _subscription = pages.hub().subscribe({
        let resets = resets.clone();
        move |message| {
            if matches!(
                message,
                Message::CollectionChanged(_) | Message::PropertyChanged(_)
            ) {
                *resets.lock().unwrap() += 1;
            }
        }
    });

    let outcome = pages.refresh_command().execute_async().join();
    fail.store(false, Ordering::SeqCst);

    assert!(outcome.is_err());
    assert_eq!(
        pages
            .items()
            .iter()
            .map(|item| item.value)
            .collect::<Vec<_>>(),
        vec![1, 2, 3, 4]
    );
    assert_eq!(pages.current_token(), Some("t3"));
    assert_eq!(*resets.lock().unwrap(), 0);
}

#[test]
fn disposal_before_retained_prefix_refresh_completes_leaves_state_untouched() {
    let backend = Backend::new();
    let (pages, started, release) = pager_with_blocked_call(&backend, 2, (vec![1, 2], Some("t2")));
    load(&pages, 2);
    let trace = trace(&pages);
    let refreshing = pages.clone();
    let refresh = std::thread::spawn(move || refreshing.refresh());
    started.recv().unwrap();

    pages.dispose();
    release.send(()).unwrap();
    refresh.join().unwrap();

    assert_eq!(pages.items(), vec![1, 2, 3, 4]);
    assert_eq!(pages.current_token(), Some("t3"));
    assert!(trace.entries().is_empty());
}

#[test]
fn retained_and_replaced_item_vms_are_never_disposed_by_the_composition() {
    let vm = |name: &'static str| {
        ComponentVm::with_model(name, name, MessageHub::new(), vmx::NullDispatcher)
    };
    let loaded = vec![vm("a"), vm("b"), vm("c"), vm("d")];
    let changed_head = vec![vm("x"), vm("y")];
    let replace_head = Arc::new(AtomicBool::new(false));
    let pages = TokenPagedComposition::with_auto_construct_loader(None, {
        let loaded = loaded.clone();
        let changed_head = changed_head.clone();
        let replace_head = replace_head.clone();
        move |token| match token {
            None if replace_head.load(Ordering::SeqCst) => (changed_head.clone(), Some("t2")),
            None => (loaded[..2].to_vec(), Some("t2")),
            Some(_) => (loaded[2..].to_vec(), Some("t3")),
        }
    });
    pages.load_next();
    pages.load_next();

    pages.refresh();

    assert_eq!(pages.items(), loaded);
    assert_eq!(pages.current_token(), Some("t3"));
    assert!(changed_head
        .iter()
        .all(|item| item.status() == ConstructionStatus::Destructed));

    replace_head.store(true, Ordering::SeqCst);
    pages.refresh();

    assert_eq!(pages.items(), changed_head);
    assert!(changed_head
        .iter()
        .all(|item| item.status() == ConstructionStatus::Constructed));
    assert!(loaded
        .iter()
        .all(|item| item.status() == ConstructionStatus::Constructed));
}

#[test]
fn auto_construct_pager_drops_a_load_that_finishes_after_a_later_refresh() {
    let vm = |name: &'static str| {
        ComponentVm::with_model(name, name, MessageHub::new(), vmx::NullDispatcher)
    };
    let first = vec![vm("a")];
    let stale = vec![vm("stale")];
    let fresh = vec![vm("fresh")];
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel::<()>();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let refreshed = Arc::new(AtomicBool::new(false));
    let pages = TokenPagedComposition::with_auto_construct_loader(None, {
        let (first, stale, fresh) = (first.clone(), stale.clone(), fresh.clone());
        let refreshed = refreshed.clone();
        move |token| match token {
            None if refreshed.load(Ordering::SeqCst) => (fresh.clone(), Some("u2")),
            None => (first.clone(), Some("t2")),
            Some(_) => {
                started_tx.send(()).unwrap();
                release_rx.lock().unwrap().recv().unwrap();
                (stale.clone(), Some("t3"))
            }
        }
    });
    pages.load_next();
    let loading = pages.clone();
    let load = std::thread::spawn(move || loading.load_next());
    started_rx.recv().unwrap();
    refreshed.store(true, Ordering::SeqCst);

    pages.refresh();
    release_tx.send(()).unwrap();
    load.join().unwrap();

    assert_eq!(pages.items(), fresh);
    assert_eq!(pages.current_token(), Some("u2"));
    assert_eq!(stale[0].status(), ConstructionStatus::Destructed);
}
