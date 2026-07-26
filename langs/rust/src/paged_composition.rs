//! Index-based paging over an in-memory composition.
//!
//! Spec: `spec/21-collections.md`.

use super::{lock, Arc, Mutex, Pageable};

/// A mutable in-memory collection exposed as fixed-size indexed pages.
///
/// The current page is clamped whenever the source or page size changes. A
/// page size of zero is the pass-through mode and exposes the complete source
/// as one page when it is non-empty.
#[derive(Clone)]
pub struct PagedComposition<T: Clone + Send + 'static> {
    source: Arc<Mutex<Vec<T>>>,
    page_size: Arc<Mutex<usize>>,
    current_page_index: Arc<Mutex<usize>>,
}

impl<T: Clone + Send + 'static> PagedComposition<T> {
    /// Creates a composition positioned at the first page.
    pub fn new(source: Vec<T>, page_size: usize) -> Self {
        Self {
            source: Arc::new(Mutex::new(source)),
            page_size: Arc::new(Mutex::new(page_size)),
            current_page_index: Arc::new(Mutex::new(0)),
        }
    }

    /// Returns the maximum number of items exposed by a page.
    pub fn page_size(&self) -> usize {
        *lock(&self.page_size)
    }

    /// Changes the page size and clamps the current page to the new range.
    pub fn set_page_size(&self, page_size: usize) {
        *lock(&self.page_size) = page_size;
        self.clamp();
    }

    /// Replaces the complete source and clamps the current page.
    pub fn set_source(&self, source: Vec<T>) {
        *lock(&self.source) = source;
        self.clamp();
    }

    /// Appends an item to the source.
    pub fn push(&self, item: T) {
        lock(&self.source).push(item);
        self.clamp();
    }

    /// Removes and returns the item at `index`, or returns `None` when absent.
    ///
    /// The current page is clamped after either outcome.
    pub fn remove_at(&self, index: usize) -> Option<T> {
        let removed = {
            let mut source = lock(&self.source);
            if index >= source.len() {
                None
            } else {
                Some(source.remove(index))
            }
        };
        self.clamp();
        removed
    }

    /// Returns the number of available pages.
    ///
    /// Pass-through mode (`page_size == 0`) always has exactly one page, even for
    /// an empty source (spec/21-collections.md §5.3). When paging is enabled an
    /// empty source has zero pages (§5.4). The `page_size == 0` branch must be
    /// checked first so the empty case does not shadow it.
    pub fn page_count(&self) -> usize {
        let page_size = self.page_size();
        if page_size == 0 {
            1
        } else {
            lock(&self.source).len().div_ceil(page_size)
        }
    }

    /// Returns the zero-based index of the current page.
    pub fn current_page_index(&self) -> usize {
        *lock(&self.current_page_index)
    }

    /// Selects a page index, clamped to the available range.
    pub fn set_current_page_index(&self, index: usize) {
        let max_index = self.page_count().saturating_sub(1);
        *lock(&self.current_page_index) = index.min(max_index);
    }

    /// Reports whether finite paging is enabled.
    pub fn is_paging_enabled(&self) -> bool {
        self.page_size() > 0
    }

    /// Returns a snapshot of the items in the current page.
    pub fn current_page(&self) -> Vec<T> {
        let source = lock(&self.source);
        let page_size = self.page_size();
        if page_size == 0 {
            return source.clone();
        }
        let start = self.current_page_index() * page_size;
        source.iter().skip(start).take(page_size).cloned().collect()
    }

    /// Advances one page, remaining at the final page when already there.
    pub fn next_page(&self) {
        let max_index = self.page_count().saturating_sub(1);
        let mut current = lock(&self.current_page_index);
        *current = (*current + 1).min(max_index);
    }

    /// Moves back one page, remaining at the first page when already there.
    pub fn previous_page(&self) {
        let mut current = lock(&self.current_page_index);
        *current = current.saturating_sub(1);
    }

    /// Moves to the first page, remaining there when already at the bound.
    pub fn move_to_first_page(&self) {
        self.set_current_page_index(0);
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
        self.set_current_page_index(self.page_count().saturating_sub(1));
    }

    fn clamp(&self) {
        let max_index = self.page_count().saturating_sub(1);
        let mut current = lock(&self.current_page_index);
        *current = (*current).min(max_index);
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
