//! Index-based paging over an in-memory composition.
//!
//! Spec: `spec/17-collections-and-paging.md`.

use super::{lock, Arc, Mutex};

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
    /// An empty source has no pages. Pass-through mode (`page_size == 0`) has
    /// one page for every non-empty source.
    pub fn page_count(&self) -> usize {
        let len = lock(&self.source).len();
        let page_size = self.page_size();
        if len == 0 {
            0
        } else if page_size == 0 {
            1
        } else {
            len.div_ceil(page_size)
        }
    }

    /// Returns the zero-based index of the current page.
    pub fn current_page_index(&self) -> usize {
        *lock(&self.current_page_index)
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

    fn clamp(&self) {
        let max_index = self.page_count().saturating_sub(1);
        let mut current = lock(&self.current_page_index);
        *current = (*current).min(max_index);
    }
}
