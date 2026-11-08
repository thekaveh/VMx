//! COL-026 — a token-paged load that the command admitted while `has_more`
//! was true fetches nothing when a terminal token lands before its body
//! starts. It is not an operation start, so it supersedes nothing (spec 21
//! §6.2, ADR-0169, #1161).

use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use vmx::{
    CollectionChangeAction, ComponentVm, Message, MessageHub, NullDispatcher, Subscription,
    TokenPagedComposition,
};

const BOUND: Duration = Duration::from_secs(5);

type Page = (Vec<i32>, Option<u8>);
type Vm = ComponentVm<i32, NullDispatcher>;

/// Pages [1] and [101], then terminal. The next first-page fetch can be held.
#[derive(Clone)]
struct Backend {
    calls: Arc<Mutex<Vec<Option<u8>>>>,
    hold_first_page: Arc<AtomicBool>,
    started_tx: Arc<Mutex<mpsc::Sender<()>>>,
    started_rx: Arc<Mutex<mpsc::Receiver<()>>>,
    release_tx: Arc<Mutex<mpsc::Sender<Page>>>,
    release_rx: Arc<Mutex<mpsc::Receiver<Page>>>,
}

impl Backend {
    fn new() -> Self {
        let (started_tx, started_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        Self {
            calls: Arc::new(Mutex::new(Vec::new())),
            hold_first_page: Arc::new(AtomicBool::new(false)),
            started_tx: Arc::new(Mutex::new(started_tx)),
            started_rx: Arc::new(Mutex::new(started_rx)),
            release_tx: Arc::new(Mutex::new(release_tx)),
            release_rx: Arc::new(Mutex::new(release_rx)),
        }
    }

    fn fetch(&self, token: Option<u8>) -> Page {
        self.calls.lock().unwrap().push(token);
        if token.is_none() && self.hold_first_page.swap(false, Ordering::SeqCst) {
            self.started_tx.lock().unwrap().send(()).unwrap();
            return self
                .release_rx
                .lock()
                .unwrap()
                .recv_timeout(BOUND)
                .expect("the held first-page fetch was released");
        }
        match token {
            // Page 1. Before the fix a gated-out load refetched it here.
            None => (vec![1], Some(1)),
            Some(1) => (vec![101], Some(2)),
            Some(_) => (vec![999], None),
        }
    }

    fn calls(&self) -> Vec<Option<u8>> {
        self.calls.lock().unwrap().clone()
    }

    fn plain_pager(&self) -> TokenPagedComposition<i32, u8> {
        let backend = self.clone();
        TokenPagedComposition::with_loader(None, move |token| backend.fetch(token))
    }

    fn auto_construct_pager(&self) -> TokenPagedComposition<Vm, u8> {
        let backend = self.clone();
        TokenPagedComposition::with_auto_construct_loader(None, move |token| {
            let (ids, next) = backend.fetch(token);
            (ids.into_iter().map(vm).collect(), next)
        })
    }
}

fn vm(id: i32) -> Vm {
    ComponentVm::with_model(format!("item-{id}"), id, MessageHub::new(), NullDispatcher)
}

trait Keyed: Clone + PartialEq + Send + 'static {
    fn key(&self) -> i32;
    fn make(id: i32) -> Self;
}

impl Keyed for i32 {
    fn key(&self) -> i32 {
        *self
    }

    fn make(id: i32) -> Self {
        id
    }
}

impl Keyed for Vm {
    fn key(&self) -> i32 {
        self.model()
    }

    fn make(id: i32) -> Self {
        vm(id)
    }
}

fn keys<T: Keyed>(pages: &TokenPagedComposition<T, u8>) -> Vec<i32> {
    pages.items().iter().map(Keyed::key).collect()
}

fn count_resets<T: Keyed>(
    pages: &TokenPagedComposition<T, u8>,
) -> (Arc<AtomicUsize>, Subscription) {
    let resets = Arc::new(AtomicUsize::new(0));
    let counter = resets.clone();
    let subscription = pages.hub().subscribe(move |message| {
        if let Message::CollectionChanged(change) = message {
            if change.action == CollectionChangeAction::Reset {
                counter.fetch_add(1, Ordering::SeqCst);
            }
        }
    });
    (resets, subscription)
}

fn load_two_pages<T: Keyed>(pages: &TokenPagedComposition<T, u8>) {
    pages.load_next();
    pages.load_next();
    assert_eq!(keys(pages), [1, 101]);
    assert_eq!(pages.current_token(), Some(2));
}

/// The load command raises `can_execute_changed` after admission and before
/// it spawns the body, so this hook commits a terminal page in that window.
fn terminal_commit_after_admission<T: Keyed>(
    pages: TokenPagedComposition<T, u8>,
    backend: &Backend,
) {
    load_two_pages(&pages);
    let calls_before = backend.calls().len();
    let (resets, _resets) = count_resets(&pages);
    let armed = Arc::new(AtomicBool::new(true));
    let writer = pages.clone();
    let hook = pages
        .load_more_command()
        .can_execute_changed()
        .subscribe(move |_| {
            if armed.swap(false, Ordering::SeqCst) {
                writer.load_more(|_| (vec![T::make(555)], None));
            }
        });

    pages.load_next();
    drop(hook);

    assert_eq!(keys(&pages), [1, 101, 555]);
    assert_eq!(pages.current_token(), None);
    assert!(!pages.has_more());
    assert!(
        backend.calls()[calls_before..].is_empty(),
        "the gated-out load fetched nothing"
    );
    assert_eq!(
        resets.load(Ordering::SeqCst),
        1,
        "only the terminal commit published"
    );
    assert!(!pages.load_more_command().can_execute());
}

/// COL-026 — a terminal token committed after admission gates out the load.
#[test]
fn load_admitted_before_a_terminal_commit_fetches_nothing() {
    let backend = Backend::new();
    terminal_commit_after_admission(backend.plain_pager(), &backend);
}

/// COL-026 — the same window on the auto-constructing pager.
#[test]
fn auto_construct_load_admitted_before_a_terminal_commit_fetches_nothing() {
    let backend = Backend::new();
    terminal_commit_after_admission(backend.auto_construct_pager(), &backend);
}

fn gated_out_load_keeps_a_later_refresh<T: Keyed>(
    pages: TokenPagedComposition<T, u8>,
    backend: &Backend,
) {
    load_two_pages(&pages);
    let calls_before = backend.calls().len();
    let armed = Arc::new(AtomicBool::new(true));
    let refresh_started = Arc::new(Mutex::new(None));
    let writer = pages.clone();
    let hook = pages.load_more_command().can_execute_changed().subscribe({
        let backend = backend.clone();
        let refresh_started = refresh_started.clone();
        move |_| {
            if !armed.swap(false, Ordering::SeqCst) {
                return;
            }
            writer.load_more(|_| (vec![T::make(555)], None));
            // A later refresh starts and holds its fetch before the load body.
            backend.hold_first_page.store(true, Ordering::SeqCst);
            writer.refresh_command().execute();
            let started = backend.started_rx.lock().unwrap().recv_timeout(BOUND);
            *refresh_started.lock().unwrap() = Some(started.is_ok());
        }
    });

    pages.load_next();
    drop(hook);
    assert_eq!(*refresh_started.lock().unwrap(), Some(true));
    assert_eq!(keys(&pages), [1, 101, 555]);
    assert!(!pages.has_more());

    backend
        .release_tx
        .lock()
        .unwrap()
        .send((vec![7], Some(9)))
        .unwrap();
    let deadline = Instant::now() + BOUND;
    while pages.refresh_command().is_executing() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(1));
    }
    assert!(
        !pages.refresh_command().is_executing(),
        "the refresh finished"
    );

    assert_eq!(
        keys(&pages),
        [7],
        "the gated-out load did not supersede the refresh"
    );
    assert_eq!(pages.current_token(), Some(9));
    assert!(pages.has_more());
    assert_eq!(
        backend.calls()[calls_before..],
        [None],
        "only the refresh fetched"
    );
}

/// COL-026 — a gated-out load does not supersede a refresh still in flight.
#[test]
fn gated_out_load_does_not_supersede_an_in_flight_refresh() {
    let backend = Backend::new();
    gated_out_load_keeps_a_later_refresh(backend.plain_pager(), &backend);
}

/// COL-026 — the same supersession rule on the auto-constructing pager.
#[test]
fn auto_construct_gated_out_load_does_not_supersede_an_in_flight_refresh() {
    let backend = Backend::new();
    gated_out_load_keeps_a_later_refresh(backend.auto_construct_pager(), &backend);
}
