//! Regression tests: `TokenPagedComposition` runs `Token::clone` with no pager
//! lock held (spec 21 §6.1 and §6.2, #1162, #1278, ADR-0202). A clone that
//! waits for another load, refresh or cursor read of the same pager returns
//! instead of deadlocking, and so does a clone that reads the cursor again on
//! its own thread.
//!
//! The token runs a one-shot hook in `Clone`. Each hook waits at most
//! [`HOOK_BOUND`] and records whether the operation it waited for finished, so
//! a regression fails an assertion and does not hang the suite.

use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc, Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
use vmx::{ComponentVm, MessageHub, NullDispatcher, TokenPagedComposition};

/// How long a hook waits inside `Token::clone`.
const HOOK_BOUND: Duration = Duration::from_secs(2);
/// How long the test waits for a thread or a state outside the hook.
const BOUND: Duration = Duration::from_secs(10);

type Hook = Box<dyn FnOnce() + Send>;
/// The thread a hook spawned, which the test joins after the clone returns.
type Spawned = Arc<Mutex<Option<JoinHandle<()>>>>;
type Vm = ComponentVm<i32, NullDispatcher>;

/// A continuation token whose next clone runs the armed hook.
struct HookToken {
    n: u8,
    hook: Arc<Mutex<Option<Hook>>>,
}

impl Clone for HookToken {
    fn clone(&self) -> Self {
        let hook = self.hook.lock().unwrap().take();
        if let Some(hook) = hook {
            hook();
        }
        Self {
            n: self.n,
            hook: self.hook.clone(),
        }
    }
}

/// The backend: the first page is `[900]` with token 9, and token 1 leads to
/// `[2]` with token 2. Every token shares one hook slot.
#[derive(Clone)]
struct Backend {
    hook: Arc<Mutex<Option<Hook>>>,
    first_page_fetched: Arc<Mutex<Option<mpsc::Sender<()>>>>,
}

impl Backend {
    fn new() -> Self {
        Self {
            hook: Arc::new(Mutex::new(None)),
            first_page_fetched: Arc::new(Mutex::new(None)),
        }
    }

    fn token(&self, n: u8) -> HookToken {
        HookToken {
            n,
            hook: self.hook.clone(),
        }
    }

    fn fetch(&self, token: Option<HookToken>) -> (Vec<i32>, Option<HookToken>) {
        match token.map(|token| token.n) {
            None => {
                if let Some(fetched) = self.first_page_fetched.lock().unwrap().as_ref() {
                    let _ = fetched.send(());
                }
                (vec![900], Some(self.token(9)))
            }
            Some(1) => (vec![2], Some(self.token(2))),
            Some(_) => (Vec::new(), None),
        }
    }

    /// Reports each first-page fetch, which only a refresh makes here.
    fn watch_first_page(&self) -> mpsc::Receiver<()> {
        let (sender, receiver) = mpsc::channel();
        *self.first_page_fetched.lock().unwrap() = Some(sender);
        receiver
    }

    fn arm(&self, hook: impl FnOnce() + Send + 'static) {
        *self.hook.lock().unwrap() = Some(Box::new(hook));
    }

    fn plain_pager(&self) -> TokenPagedComposition<i32, HookToken> {
        let backend = self.clone();
        TokenPagedComposition::with_loader(None, move |token| backend.fetch(token))
    }

    fn auto_construct_pager(&self) -> TokenPagedComposition<Vm, HookToken> {
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

fn keys<T: Keyed>(pages: &TokenPagedComposition<T, HookToken>) -> Vec<i32> {
    pages.items().iter().map(Keyed::key).collect()
}

fn token_number<T: Keyed>(pages: &TokenPagedComposition<T, HookToken>) -> Option<u8> {
    pages.current_token().map(|token| token.n)
}

/// Loads `[1]` with token 1 through an ad hoc load.
fn load_first_page<T: Keyed>(pages: &TokenPagedComposition<T, HookToken>, backend: &Backend) {
    pages.load_more(|_| (vec![T::make(1)], Some(backend.token(1))));
    assert_eq!(keys(pages), [1]);
    assert_eq!(token_number(pages), Some(1));
}

fn join_bounded<R>(handle: JoinHandle<R>, what: &str) -> R {
    let deadline = Instant::now() + BOUND;
    while !handle.is_finished() {
        assert!(Instant::now() < deadline, "{what} did not finish");
        thread::sleep(Duration::from_millis(1));
    }
    handle.join().unwrap_or_else(|_| panic!("{what} panicked"))
}

fn wait_until(what: &str, done: impl Fn() -> bool) -> bool {
    let deadline = Instant::now() + HOOK_BOUND;
    while !done() {
        if Instant::now() >= deadline {
            eprintln!("timed out waiting until {what}");
            return false;
        }
        thread::sleep(Duration::from_millis(1));
    }
    true
}

/// Arms a hook that runs `refresh()` on a new thread and waits for it to
/// finish. The returned flag reports whether it finished within the wait.
fn arm_refresh_and_wait<T: Keyed>(
    pages: &TokenPagedComposition<T, HookToken>,
    backend: &Backend,
) -> (Arc<AtomicBool>, Spawned) {
    let finished = Arc::new(AtomicBool::new(false));
    let refresher: Spawned = Arc::new(Mutex::new(None));
    let (hook_finished, hook_refresher, hook_pages) =
        (finished.clone(), refresher.clone(), pages.clone());
    backend.arm(move || {
        let (done_tx, done_rx) = mpsc::channel();
        let refresh = thread::spawn(move || {
            hook_pages.refresh();
            let _ = done_tx.send(());
        });
        *hook_refresher.lock().unwrap() = Some(refresh);
        let done = done_rx.recv_timeout(HOOK_BOUND).is_ok();
        hook_finished.store(done, Ordering::SeqCst);
    });
    (finished, refresher)
}

fn join_refresher(refresher: &Mutex<Option<JoinHandle<()>>>) {
    let refresh = refresher.lock().unwrap().take().expect("the hook ran");
    join_bounded(refresh, "the refresh");
}

#[test]
fn a_refresh_started_inside_current_token_clone_finishes() {
    let backend = Backend::new();
    let pages = backend.plain_pager();
    load_first_page(&pages, &backend);
    let (finished, refresher) = arm_refresh_and_wait(&pages, &backend);

    let returned = token_number(&pages);
    join_refresher(&refresher);

    assert!(
        finished.load(Ordering::SeqCst),
        "the refresh finished while Token::clone waited"
    );
    assert_eq!(returned, Some(1));
    assert_eq!(keys(&pages), [900]);
    assert_eq!(token_number(&pages), Some(9));
}

#[test]
fn a_refresh_started_inside_current_token_clone_runs_after_another_load_commits() {
    let backend = Backend::new();
    let pages = backend.plain_pager();
    load_first_page(&pages, &backend);
    let first_page = backend.watch_first_page();

    // Thread B holds its ad hoc load in the loader, after its cursor read.
    let (b_started_tx, b_started_rx) = mpsc::channel();
    let (b_release_tx, b_release_rx) = mpsc::channel::<()>();
    let b_pages = pages.clone();
    let b_backend = backend.clone();
    let loader_b = thread::spawn(move || {
        b_pages.load_more(|token| {
            assert_eq!(token.map(|token| token.n), Some(1));
            b_started_tx.send(()).unwrap();
            b_release_rx
                .recv_timeout(BOUND)
                .expect("the hook released B");
            (vec![2], Some(b_backend.token(2)))
        });
    });
    b_started_rx
        .recv_timeout(BOUND)
        .expect("B's loader started");

    let ran = Arc::new(AtomicBool::new(false));
    let refresher: Spawned = Arc::new(Mutex::new(None));
    let (hook_ran, hook_refresher, hook_pages) = (ran.clone(), refresher.clone(), pages.clone());
    backend.arm(move || {
        b_release_tx.send(()).unwrap();
        // B has written the items, so its commit is past its items write.
        if !wait_until("B committed [1, 2]", || hook_pages.items() == [1, 2]) {
            return;
        }
        let refresh_pages = hook_pages.clone();
        *hook_refresher.lock().unwrap() = Some(thread::spawn(move || refresh_pages.refresh()));
        let loader_ran = first_page.recv_timeout(HOOK_BOUND).is_ok();
        hook_ran.store(loader_ran, Ordering::SeqCst);
    });

    let returned = token_number(&pages);
    join_bounded(loader_b, "thread B");
    join_refresher(&refresher);

    assert!(
        ran.load(Ordering::SeqCst),
        "the refresh loader ran while Token::clone waited"
    );
    assert_eq!(returned, Some(1));
    assert_eq!(keys(&pages), [900]);
    assert_eq!(token_number(&pages), Some(9));
}

/// Case 3: the load's cursor read runs the hook, which refreshes on another
/// thread. The refresh finishes, and the superseded load commits nothing.
fn refresh_inside_load_cursor_read<T: Keyed>(
    pages: TokenPagedComposition<T, HookToken>,
    backend: &Backend,
    start_load: impl FnOnce(TokenPagedComposition<T, HookToken>) + Send + 'static,
) {
    load_first_page(&pages, backend);
    let (finished, refresher) = arm_refresh_and_wait(&pages, backend);

    let load_pages = pages.clone();
    let load = thread::spawn(move || start_load(load_pages));
    join_bounded(load, "the load");
    join_refresher(&refresher);

    assert!(
        finished.load(Ordering::SeqCst),
        "the refresh finished while Token::clone waited"
    );
    assert_eq!(keys(&pages), [900], "the superseded load committed nothing");
    assert_eq!(token_number(&pages), Some(9));
}

#[test]
fn a_refresh_started_inside_a_load_next_cursor_read_finishes() {
    let backend = Backend::new();
    refresh_inside_load_cursor_read(backend.plain_pager(), &backend, |pages| {
        pages.load_next();
    });
}

#[test]
fn a_refresh_started_inside_an_auto_construct_load_next_cursor_read_finishes() {
    let backend = Backend::new();
    refresh_inside_load_cursor_read(backend.auto_construct_pager(), &backend, |pages| {
        pages.load_next();
    });
}

#[test]
fn a_refresh_started_inside_an_ad_hoc_load_cursor_read_finishes() {
    let backend = Backend::new();
    let fetch = backend.clone();
    refresh_inside_load_cursor_read(backend.plain_pager(), &backend, move |pages| {
        pages.load_more(|token| fetch.fetch(token));
    });
}

/// Case 1: the clone waits for another thread's `current_token()`, which
/// clones the same stored token. That read returns while the first clone waits.
#[test]
fn a_clone_that_waits_for_another_threads_current_token_sees_it_return() {
    let backend = Backend::new();
    let pages = backend.plain_pager();
    load_first_page(&pages, &backend);
    let returned_in_time = Arc::new(AtomicBool::new(false));
    let reader: Arc<Mutex<Option<JoinHandle<Option<u8>>>>> = Arc::new(Mutex::new(None));
    let (hook_returned, hook_reader, hook_pages) =
        (returned_in_time.clone(), reader.clone(), pages.clone());
    backend.arm(move || {
        let (done_tx, done_rx) = mpsc::channel();
        let read = thread::spawn(move || {
            let token = token_number(&hook_pages);
            let _ = done_tx.send(());
            token
        });
        *hook_reader.lock().unwrap() = Some(read);
        let done = done_rx.recv_timeout(HOOK_BOUND).is_ok();
        hook_returned.store(done, Ordering::SeqCst);
    });

    let returned = token_number(&pages);
    let read = reader.lock().unwrap().take().expect("the hook ran");
    let other = join_bounded(read, "the other thread's read");

    assert!(
        returned_in_time.load(Ordering::SeqCst),
        "the other thread's current_token() returned while Token::clone waited"
    );
    assert_eq!(other, Some(1));
    assert_eq!(returned, Some(1));
}

/// Case 2: the clone calls `current_token()` again on its own thread.
#[test]
fn a_clone_that_reads_current_token_on_its_own_thread_returns() {
    let backend = Backend::new();
    let pages = backend.plain_pager();
    load_first_page(&pages, &backend);
    let inner = Arc::new(Mutex::new(None::<Option<u8>>));
    let (hook_inner, hook_pages) = (inner.clone(), pages.clone());
    backend.arm(move || {
        *hook_inner.lock().unwrap() = Some(token_number(&hook_pages));
    });

    let (done_tx, done_rx) = mpsc::channel();
    let outer_pages = pages.clone();
    // On a regression this thread stays blocked; the bounded wait still ends.
    thread::spawn(move || {
        let _ = done_tx.send(token_number(&outer_pages));
    });

    let outer = done_rx
        .recv_timeout(HOOK_BOUND)
        .expect("current_token() returned after its clone read the cursor again");
    assert_eq!(outer, Some(1));
    assert_eq!(*inner.lock().unwrap(), Some(Some(1)));
}

/// Case 2 through a load: the load's cursor read runs a clone that calls
/// `current_token()` on the load's thread. The load finishes and commits.
fn current_token_inside_load_cursor_read<T: Keyed>(
    pages: TokenPagedComposition<T, HookToken>,
    backend: &Backend,
) {
    load_first_page(&pages, backend);
    let inner = Arc::new(Mutex::new(None::<Option<u8>>));
    let (hook_inner, hook_pages) = (inner.clone(), pages.clone());
    backend.arm(move || {
        *hook_inner.lock().unwrap() = Some(token_number(&hook_pages));
    });

    let load_pages = pages.clone();
    let load = thread::spawn(move || load_pages.load_next());
    join_bounded(load, "the load");

    assert_eq!(*inner.lock().unwrap(), Some(Some(1)));
    assert_eq!(keys(&pages), [1, 2]);
    assert_eq!(token_number(&pages), Some(2));
}

#[test]
fn a_load_next_cursor_read_whose_clone_reads_current_token_finishes() {
    let backend = Backend::new();
    current_token_inside_load_cursor_read(backend.plain_pager(), &backend);
}

#[test]
fn an_auto_construct_load_next_cursor_read_whose_clone_reads_current_token_finishes() {
    let backend = Backend::new();
    current_token_inside_load_cursor_read(backend.auto_construct_pager(), &backend);
}

/// A `Send + Sync` token that keeps its state in a shared atomic.
#[derive(Clone, Debug)]
struct SharedToken(Arc<AtomicUsize>);

impl PartialEq for SharedToken {
    fn eq(&self, other: &Self) -> bool {
        self.0.load(Ordering::SeqCst) == other.0.load(Ordering::SeqCst)
    }
}

fn assert_send_sync<T: Send + Sync>() {}

#[test]
fn a_send_and_sync_token_pages() {
    assert_send_sync::<TokenPagedComposition<i32, SharedToken>>();
    let pages =
        TokenPagedComposition::with_loader(None, |token: Option<SharedToken>| match token {
            None => (vec![1], Some(SharedToken(Arc::new(AtomicUsize::new(1))))),
            Some(_) => (vec![2], None),
        });

    pages.load_next();

    assert_eq!(pages.items(), [1]);
    assert_eq!(
        pages.current_token(),
        Some(SharedToken(Arc::new(AtomicUsize::new(1))))
    );
    assert!(pages.has_more());
}
