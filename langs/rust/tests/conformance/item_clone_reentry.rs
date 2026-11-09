//! Regression tests: `TokenPagedComposition` runs the item `T::clone` with no
//! pager lock held, so a clone that waits for another load or refresh of the
//! same pager returns instead of deadlocking (spec 21 §6.2, #1277).
//!
//! The item runs a one-shot hook in `Clone`. Each hook waits at most
//! [`HOOK_BOUND`] and records whether the operation it waited for finished, so
//! a regression fails an assertion and does not hang the suite.

use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
use vmx::{ConstructionStatus, TokenPagedComposition, VmNode, VmxResult};

/// How long a hook waits inside `T::clone`.
const HOOK_BOUND: Duration = Duration::from_secs(2);
/// How long the test waits for a thread outside the hook.
const BOUND: Duration = Duration::from_secs(10);

type Hook = Box<dyn FnOnce() + Send>;
type HookSlot = Arc<Mutex<Option<Hook>>>;
/// The thread a hook spawned, which the test joins after the clone returns.
type Spawned = Arc<Mutex<Option<JoinHandle<()>>>>;
type Pager = TokenPagedComposition<HookItem, u8>;

/// An item whose next clone runs the armed hook. It is also a VM node, so the
/// auto-construct pager can hold it.
struct HookItem {
    n: i32,
    hook: HookSlot,
}

impl Clone for HookItem {
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

impl PartialEq for HookItem {
    fn eq(&self, other: &Self) -> bool {
        self.n == other.n
    }
}

impl VmNode for HookItem {
    fn id(&self) -> usize {
        self.n as usize
    }

    fn construct(&self) -> VmxResult<()> {
        Ok(())
    }

    fn destruct(&self) -> VmxResult<()> {
        Ok(())
    }

    fn dispose(&self) -> VmxResult<()> {
        Ok(())
    }

    fn status(&self) -> ConstructionStatus {
        ConstructionStatus::Constructed
    }

    fn set_parent_id(&self, _parent_id: Option<usize>) {}

    fn parent_id(&self) -> Option<usize> {
        None
    }
}

/// The backend: the first page is `[900]` with token 9. Every item shares
/// one hook slot.
#[derive(Clone)]
struct Backend {
    hook: HookSlot,
}

impl Backend {
    fn new() -> Self {
        Self {
            hook: Arc::new(Mutex::new(None)),
        }
    }

    fn item(&self, n: i32) -> HookItem {
        HookItem {
            n,
            hook: self.hook.clone(),
        }
    }

    fn fetch(&self, token: Option<u8>) -> (Vec<HookItem>, Option<u8>) {
        match token {
            None => (vec![self.item(900)], Some(9)),
            Some(_) => (Vec::new(), None),
        }
    }

    fn arm(&self, hook: impl FnOnce() + Send + 'static) {
        *self.hook.lock().unwrap() = Some(Box::new(hook));
    }

    fn plain_pager(&self) -> Pager {
        let backend = self.clone();
        TokenPagedComposition::with_loader(None, move |token| backend.fetch(token))
    }

    fn auto_construct_pager(&self) -> Pager {
        let backend = self.clone();
        TokenPagedComposition::with_auto_construct_loader(None, move |token| backend.fetch(token))
    }
}

fn keys(pages: &Pager) -> Vec<i32> {
    pages.items().iter().map(|item| item.n).collect()
}

/// Loads `[1]` with token 1 through an ad hoc load.
fn load_first_page(pages: &Pager, backend: &Backend) {
    let first = backend.item(1);
    pages.load_more(move |_| (vec![first], Some(1)));
    assert_eq!(keys(pages), [1]);
    assert_eq!(pages.current_token(), Some(1));
}

fn join_bounded(handle: JoinHandle<()>, what: &str) {
    let deadline = Instant::now() + BOUND;
    while !handle.is_finished() {
        assert!(Instant::now() < deadline, "{what} did not finish");
        thread::sleep(Duration::from_millis(1));
    }
    handle.join().unwrap_or_else(|_| panic!("{what} panicked"));
}

/// Arms a hook that runs `operation` on a new thread and waits for it to
/// finish. The returned flag reports whether it finished within the wait.
fn arm_and_wait(
    backend: &Backend,
    operation: impl FnOnce() + Send + 'static,
) -> (Arc<AtomicBool>, Spawned) {
    let finished = Arc::new(AtomicBool::new(false));
    let spawned: Spawned = Arc::new(Mutex::new(None));
    let (hook_finished, hook_spawned) = (finished.clone(), spawned.clone());
    backend.arm(move || {
        let (done_tx, done_rx) = mpsc::channel();
        let worker = thread::spawn(move || {
            operation();
            let _ = done_tx.send(());
        });
        *hook_spawned.lock().unwrap() = Some(worker);
        let done = done_rx.recv_timeout(HOOK_BOUND).is_ok();
        hook_finished.store(done, Ordering::SeqCst);
    });
    (finished, spawned)
}

fn join_spawned(spawned: &Spawned, what: &str) {
    let worker = spawned.lock().unwrap().take().expect("the hook ran");
    join_bounded(worker, what);
}

/// The ad hoc load of cases 2 and 3: it appends `[2]` with token 2.
fn second_page_load(pages: &Pager, backend: &Backend) -> impl FnOnce() + Send + 'static {
    let (pages, second) = (pages.clone(), backend.item(2));
    move || pages.load_more(move |_| (vec![second], Some(2)))
}

/// Case 1: `items()` clones an item whose hook refreshes on another thread.
/// The refresh, which compares that item, finishes while the clone waits.
#[test]
fn a_refresh_started_inside_an_items_clone_finishes() {
    let backend = Backend::new();
    let pages = backend.plain_pager();
    load_first_page(&pages, &backend);
    let refresh_pages = pages.clone();
    let (finished, spawned) = arm_and_wait(&backend, move || refresh_pages.refresh());

    let returned = keys(&pages);
    join_spawned(&spawned, "the refresh");

    assert!(
        finished.load(Ordering::SeqCst),
        "the refresh finished while T::clone waited"
    );
    assert_eq!(returned, [1]);
    assert_eq!(keys(&pages), [900]);
    assert_eq!(pages.current_token(), Some(9));
}

/// Case 2: `items()` clones an item whose hook loads on another thread. The
/// load finishes while the clone waits.
#[test]
fn a_load_started_inside_an_items_clone_finishes() {
    let backend = Backend::new();
    let pages = backend.plain_pager();
    load_first_page(&pages, &backend);
    let (finished, spawned) = arm_and_wait(&backend, second_page_load(&pages, &backend));

    let returned = keys(&pages);
    join_spawned(&spawned, "the load");

    assert!(
        finished.load(Ordering::SeqCst),
        "the load finished while T::clone waited"
    );
    assert_eq!(returned, [1]);
    assert_eq!(keys(&pages), [1, 2]);
    assert_eq!(pages.current_token(), Some(2));
}

/// Case 3: a refresh's comparison copy clones an item whose hook loads on
/// another thread. The load finishes and supersedes the refresh.
fn load_inside_refresh_comparison(pages: Pager, backend: &Backend) {
    load_first_page(&pages, backend);
    let (finished, spawned) = arm_and_wait(backend, second_page_load(&pages, backend));

    let refresh_pages = pages.clone();
    let refresh = thread::spawn(move || refresh_pages.refresh());
    join_bounded(refresh, "the refresh");
    join_spawned(&spawned, "the load");

    assert!(
        finished.load(Ordering::SeqCst),
        "the load finished while the comparison clone waited"
    );
    assert_eq!(
        keys(&pages),
        [1, 2],
        "the superseded refresh committed nothing"
    );
    assert_eq!(pages.current_token(), Some(2));
}

#[test]
fn a_load_started_inside_a_refresh_comparison_clone_finishes() {
    let backend = Backend::new();
    load_inside_refresh_comparison(backend.plain_pager(), &backend);
}

#[test]
fn a_load_started_inside_an_auto_construct_refresh_comparison_clone_finishes() {
    let backend = Backend::new();
    load_inside_refresh_comparison(backend.auto_construct_pager(), &backend);
}
