//! Index-based paging over an in-memory composition.
//!
//! Spec: `spec/21-collections.md` §5; ADR-0168 and ADR-0208.

use super::{
    lock, next_id, Arc, AtomicBool, CompositeVm, Dispatcher, Message, MessageHub, Mutex, Ordering,
    Pageable, PropertyChangedMessage, Subscription, VmNode, Weak,
};

const PAGE_SIZE: &str = "page_size";
const IS_PAGING_ENABLED: &str = "is_paging_enabled";
const PAGE_COUNT: &str = "page_count";
const CURRENT_PAGE_INDEX: &str = "current_page_index";
const ITEMS: &str = "items";

struct PagerState<T> {
    source: Vec<T>,
    page_size: usize,
    current_page_index: usize,
    /// Counts the source replacements, so a stale copy never overwrites a
    /// newer one.
    source_generation: u64,
}

impl<T> PagerState<T> {
    /// Pass-through mode (`page_size == 0`) always has exactly one page,
    /// even for an empty source (spec/21 §5.3). When paging is enabled, an
    /// empty source has zero pages (§5.4).
    fn page_count(&self) -> usize {
        if self.page_size == 0 {
            1
        } else {
            self.source.len().div_ceil(self.page_size)
        }
    }

    fn max_index(&self) -> usize {
        self.page_count().saturating_sub(1)
    }

    /// Clamps the current page to the available range and reports whether
    /// it moved.
    fn clamp(&mut self) -> bool {
        let clamped = self.current_page_index.min(self.max_index());
        let moved = clamped != self.current_page_index;
        self.current_page_index = clamped;
        moved
    }

    /// Moves to `index` and reports whether the index changed.
    fn move_to(&mut self, index: usize) -> bool {
        let index = index.min(self.max_index());
        let moved = index != self.current_page_index;
        self.current_page_index = index;
        moved
    }
}

struct PagerCore<T> {
    state: Mutex<PagerState<T>>,
    hub: MessageHub,
    id: usize,
    disposed: AtomicBool,
}

impl<T> PagerCore<T> {
    /// Publishes each name as a `PropertyChangedMessage`, unless the pager
    /// is disposed. No lock is held.
    fn publish(&self, names: &[&str]) {
        for name in names {
            if self.disposed.load(Ordering::Acquire) {
                return;
            }
            self.hub
                .send(Message::PropertyChanged(PropertyChangedMessage {
                    sender_id: self.id,
                    sender_name: "PagedComposition".to_string(),
                    property_name: (*name).to_string(),
                }));
        }
    }

    /// Publishes a source change: `page_count`, then `current_page_index`
    /// when the index clamped, then `items` (spec/21 §5.2).
    fn publish_source_change(&self, clamped: bool) {
        if clamped {
            self.publish(&[PAGE_COUNT, CURRENT_PAGE_INDEX, ITEMS]);
        } else {
            self.publish(&[PAGE_COUNT, ITEMS]);
        }
    }

    /// Replaces the stored copy, clamps the index, and publishes the change.
    /// The old items drop after the lock is released.
    fn replace_source(&self, source: Vec<T>) {
        let (previous, clamped) = {
            let mut state = lock(&self.state);
            state.source_generation = state.source_generation.wrapping_add(1);
            let previous = std::mem::replace(&mut state.source, source);
            (previous, state.clamp())
        };
        drop(previous);
        self.publish_source_change(clamped);
    }

    /// Moves the current page and publishes `current_page_index` and
    /// `items` when it changed.
    fn navigate(&self, target: impl FnOnce(&PagerState<T>) -> usize) {
        let moved = {
            let mut state = lock(&self.state);
            let index = target(&state);
            state.move_to(index)
        };
        if moved {
            self.publish(&[CURRENT_PAGE_INDEX, ITEMS]);
        }
    }
}

/// A mutable in-memory collection exposed as fixed-size indexed pages.
///
/// The pager pages a stored copy of its source (ADR-0168). The current page
/// is clamped whenever the source or page size changes. A page size of zero
/// is the pass-through mode and exposes the complete source as one page.
///
/// Each change publishes `PropertyChangedMessage`s on [`hub`](Self::hub)
/// with the snake_case names `page_size`, `is_paging_enabled`, `page_count`,
/// `current_page_index` and `items`. A call that changes nothing publishes
/// nothing. A pager made with [`from_composite`](Self::from_composite)
/// replaces its copy with the composite's children after each composite
/// collection change. After [`dispose`](Self::dispose), the pager stops
/// following the composite and publishes nothing (spec/21 §5.5, ADR-0208).
#[derive(Clone)]
pub struct PagedComposition<T: Clone + Send + 'static> {
    core: Arc<PagerCore<T>>,
    source_subscription: Arc<Mutex<Option<Subscription>>>,
}

impl<T: Clone + Send + 'static> PagedComposition<T> {
    /// Creates a composition positioned at the first page, with a private
    /// message hub.
    pub fn new(source: Vec<T>, page_size: usize) -> Self {
        Self::with_hub(source, page_size, MessageHub::new())
    }

    /// Creates a composition positioned at the first page that publishes its
    /// property changes to `hub`.
    pub fn with_hub(source: Vec<T>, page_size: usize, hub: MessageHub) -> Self {
        Self {
            core: Arc::new(PagerCore {
                state: Mutex::new(PagerState {
                    source,
                    page_size,
                    current_page_index: 0,
                    source_generation: 0,
                }),
                hub,
                id: next_id(),
                disposed: AtomicBool::new(false),
            }),
            source_subscription: Arc::new(Mutex::new(None)),
        }
    }

    /// Returns the identity that this pager's messages carry.
    pub fn id(&self) -> usize {
        self.core.id
    }

    /// Returns the hub that receives this pager's property changes.
    pub fn hub(&self) -> MessageHub {
        self.core.hub.clone()
    }

    /// Stops following a composite source and stops all publication.
    /// Repeated calls are inert.
    pub fn dispose(&self) {
        self.core.disposed.store(true, Ordering::Release);
        let subscription = lock(&self.source_subscription).take();
        drop(subscription);
    }

    /// Returns the maximum number of items exposed by a page.
    pub fn page_size(&self) -> usize {
        lock(&self.core.state).page_size
    }

    /// Changes the page size and clamps the current page to the new range.
    ///
    /// A new value publishes `page_size`, `is_paging_enabled`, `page_count`,
    /// `current_page_index` and `items`. The same value publishes nothing.
    pub fn set_page_size(&self, page_size: usize) {
        {
            let mut state = lock(&self.core.state);
            if state.page_size == page_size {
                return;
            }
            state.page_size = page_size;
            state.clamp();
        }
        self.core.publish(&[
            PAGE_SIZE,
            IS_PAGING_ENABLED,
            PAGE_COUNT,
            CURRENT_PAGE_INDEX,
            ITEMS,
        ]);
    }

    /// Replaces the complete source and clamps the current page.
    pub fn set_source(&self, source: Vec<T>) {
        self.core.replace_source(source);
    }

    /// Appends an item to the source.
    pub fn push(&self, item: T) {
        let clamped = {
            let mut state = lock(&self.core.state);
            state.source.push(item);
            state.clamp()
        };
        self.core.publish_source_change(clamped);
    }

    /// Removes and returns the item at `index`, or returns `None` when absent.
    ///
    /// A removal clamps the current page and publishes the source change. A
    /// missing index changes and publishes nothing.
    pub fn remove_at(&self, index: usize) -> Option<T> {
        let (removed, clamped) = {
            let mut state = lock(&self.core.state);
            if index >= state.source.len() {
                return None;
            }
            let removed = state.source.remove(index);
            (removed, state.clamp())
        };
        self.core.publish_source_change(clamped);
        Some(removed)
    }

    /// Returns the number of available pages.
    ///
    /// Pass-through mode (`page_size == 0`) always has exactly one page, even for
    /// an empty source (spec/21-collections.md §5.3). When paging is enabled an
    /// empty source has zero pages (§5.4).
    pub fn page_count(&self) -> usize {
        lock(&self.core.state).page_count()
    }

    /// Returns the zero-based index of the current page.
    pub fn current_page_index(&self) -> usize {
        lock(&self.core.state).current_page_index
    }

    /// Selects a page index, clamped to the available range.
    pub fn set_current_page_index(&self, index: usize) {
        self.core.navigate(|_| index);
    }

    /// Reports whether finite paging is enabled.
    pub fn is_paging_enabled(&self) -> bool {
        self.page_size() > 0
    }

    /// Returns a snapshot of the items in the current page.
    pub fn current_page(&self) -> Vec<T> {
        let state = lock(&self.core.state);
        if state.page_size == 0 {
            return state.source.clone();
        }
        let start = state.current_page_index * state.page_size;
        state
            .source
            .iter()
            .skip(start)
            .take(state.page_size)
            .cloned()
            .collect()
    }

    /// Advances one page, remaining at the final page when already there.
    pub fn next_page(&self) {
        self.core
            .navigate(|state| state.current_page_index.saturating_add(1));
    }

    /// Moves back one page, remaining at the first page when already there.
    pub fn previous_page(&self) {
        self.core
            .navigate(|state| state.current_page_index.saturating_sub(1));
    }

    /// Moves to the first page, remaining there when already at the bound.
    pub fn move_to_first_page(&self) {
        self.core.navigate(|_| 0);
    }

    /// Moves to the previous page, remaining there when already at the bound.
    pub fn move_to_previous_page(&self) {
        self.previous_page();
    }

    /// Moves to the next page, remaining there when already at the bound.
    pub fn move_to_next_page(&self) {
        self.next_page();
    }

    /// Moves to the last page, remaining at zero for an empty source.
    pub fn move_to_last_page(&self) {
        self.core.navigate(PagerState::max_index);
    }
}

impl<T: VmNode> PagedComposition<T> {
    /// Creates a composition over the children of `source`, with a private
    /// message hub.
    ///
    /// The pager pages a copy of the children. After each local collection
    /// change of `source` it replaces the copy with the current children and
    /// publishes the source change (spec/21 §5.5). The pager does not keep
    /// `source` alive.
    pub fn from_composite<D: Dispatcher>(source: &CompositeVm<T, D>, page_size: usize) -> Self {
        Self::from_composite_with_hub(source, page_size, MessageHub::new())
    }

    /// Creates a composition over the children of `source` that publishes
    /// its property changes to `hub` (see
    /// [`from_composite`](Self::from_composite)).
    pub fn from_composite_with_hub<D: Dispatcher>(
        source: &CompositeVm<T, D>,
        page_size: usize,
        hub: MessageHub,
    ) -> Self {
        let pager = Self::with_hub(source.items(), page_size, hub);
        let core: Weak<PagerCore<T>> = Arc::downgrade(&pager.core);
        let children = source.children_reader();
        let subscription = source.collection_changed().subscribe(move |_| {
            if let Some(core) = core.upgrade() {
                if !core.disposed.load(Ordering::Acquire) {
                    core.replace_source(children());
                }
            }
        });
        *lock(&pager.source_subscription) = Some(subscription);
        // A change between the first read and the subscription is read here,
        // before any caller can observe the pager. A change after the
        // subscription runs the callback, which reads the children after the
        // change. If a callback replaced the copy after this read began, its
        // copy is kept, so an older read never overwrites it.
        let generation = lock(&pager.core.state).source_generation;
        let current = source.children_reader()();
        let previous = {
            let mut state = lock(&pager.core.state);
            if state.source_generation == generation {
                let previous = std::mem::replace(&mut state.source, current);
                state.clamp();
                previous
            } else {
                current
            }
        };
        drop(previous);
        pager
    }
}

impl<T: Clone + Send + 'static> Pageable for PagedComposition<T> {
    fn page_size(&self) -> usize {
        PagedComposition::page_size(self)
    }

    fn set_page_size(&self, page_size: usize) {
        PagedComposition::set_page_size(self, page_size);
    }

    fn current_page_index(&self) -> usize {
        PagedComposition::current_page_index(self)
    }

    fn set_current_page_index(&self, index: usize) {
        PagedComposition::set_current_page_index(self, index);
    }

    fn page_count(&self) -> usize {
        PagedComposition::page_count(self)
    }

    fn is_paging_enabled(&self) -> bool {
        PagedComposition::is_paging_enabled(self)
    }

    fn move_to_first_page(&self) {
        PagedComposition::move_to_first_page(self);
    }

    fn move_to_previous_page(&self) {
        PagedComposition::move_to_previous_page(self);
    }

    fn move_to_next_page(&self) {
        PagedComposition::move_to_next_page(self);
    }

    fn move_to_last_page(&self) {
        PagedComposition::move_to_last_page(self);
    }
}
