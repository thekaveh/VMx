use crate::models::{note_matches, InMemoryNoteRepository, NoteDraft, NoteModel, NotebookModel};
use std::sync::{Arc, Mutex, MutexGuard};
use vmx::{
    AggregateVm6, Command, ComponentVm, CompositeVm, DecoratorCommand, DiscriminatorVm,
    FilteredCompositeVm, FormVm, MessageHub, NotificationHub, NotificationReaction,
    NotificationType, NotificationVm, NullDispatcher, PagedComposition, ParentHandle, RelayCommand,
    SearchableState, TokenPagedComposition, VmNode, VmxError, VmxResult, NO_HOOK,
};

const PAGE_SIZE: usize = 2;
const SEARCH_PAGE_SIZE: usize = 2;
/// One refresh fetches the first page at most this many times. Each extra
/// fetch replaces a refresh that a racing load discarded.
const SEARCH_RUNS: usize = 3;
/// At most this many notifications stay pending, as in every flavor.
const NOTIFICATION_CAP: usize = 5;

/// Observer told about each note a save persisted.
type SavedHook = Arc<Mutex<Option<Arc<dyn Fn(&NoteModel) + Send + Sync>>>>;

#[derive(Clone)]
pub struct NoteVm {
    component: ComponentVm<NoteModel>,
}

impl NoteVm {
    fn new(note: NoteModel, hub: MessageHub) -> Self {
        Self {
            component: ComponentVm::with_model(note.id.clone(), note, hub, NullDispatcher::new()),
        }
    }

    pub fn model(&self) -> NoteModel {
        self.component.model()
    }

    pub fn id(&self) -> String {
        self.model().id
    }

    pub fn title(&self) -> String {
        self.model().title
    }

    fn set_model(&self, note: NoteModel) {
        self.component.set_model(note);
    }

    fn matches(&self, term: &str) -> bool {
        let term = term.trim().to_lowercase();
        if term.is_empty() {
            return true;
        }
        let note = self.model();
        note.title.to_lowercase().contains(&term)
            || note.body.to_lowercase().contains(&term)
            || note
                .tags
                .iter()
                .any(|tag| tag.to_lowercase().contains(&term))
    }
}

impl PartialEq for NoteVm {
    fn eq(&self, other: &Self) -> bool {
        self.component.id() == other.component.id()
    }
}

impl Eq for NoteVm {}

impl VmNode for NoteVm {
    fn id(&self) -> usize {
        self.component.id()
    }

    fn construct(&self) -> VmxResult<()> {
        self.component.construct()
    }

    fn destruct(&self) -> VmxResult<()> {
        self.component.destruct()
    }

    fn dispose(&self) -> VmxResult<()> {
        self.component.dispose()
    }

    fn status(&self) -> vmx::ConstructionStatus {
        self.component.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.component.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        self.component.parent_id()
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.component.set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.component.parent_handle()
    }

    fn set_current_flag(&self, is_current: bool) {
        self.component.set_current_flag(is_current);
    }

    fn is_current(&self) -> bool {
        self.component.is_current()
    }
}

#[derive(Clone)]
pub struct NotebooksVm {
    core: ComponentVm<()>,
    notebooks: Vec<NotebookModel>,
    current_id: Arc<Mutex<String>>,
}

impl NotebooksVm {
    fn new(repository: &InMemoryNoteRepository, hub: MessageHub) -> Self {
        let notebooks = repository.notebooks();
        let current_id = notebooks
            .first()
            .map(|notebook| notebook.id.clone())
            .unwrap_or_default();
        Self {
            core: ComponentVm::with_model("notebooks", (), hub, NullDispatcher::new()),
            notebooks,
            current_id: Arc::new(Mutex::new(current_id)),
        }
    }

    pub fn current_id(&self) -> String {
        lock(&self.current_id).clone()
    }

    pub fn current_title(&self) -> String {
        let current = self.current_id();
        self.notebooks
            .iter()
            .find(|notebook| notebook.id == current)
            .map(|notebook| notebook.title.clone())
            .unwrap_or_default()
    }

    pub fn titles(&self) -> Vec<String> {
        self.notebooks
            .iter()
            .map(|notebook| notebook.title.clone())
            .collect()
    }

    pub fn select(&self, notebook_id: &str) -> VmxResult<()> {
        if !self
            .notebooks
            .iter()
            .any(|notebook| notebook.id == notebook_id)
        {
            return Err(VmxError::InvalidArgument("unknown notebook".to_string()));
        }
        *lock(&self.current_id) = notebook_id.to_string();
        Ok(())
    }
}

impl NotebooksVm {
    /// Owns no disposable primitives beyond its core.
    fn release_owned(&self) {}
}

impl_node!(NotebooksVm);

#[derive(Clone)]
pub struct NotesViewVm {
    core: ComponentVm<()>,
    repository: InMemoryNoteRepository,
    notebook_id: Arc<Mutex<String>>,
    search_term: Arc<Mutex<String>>,
    source: CompositeVm<NoteVm>,
    filtered: FilteredCompositeVm<NoteVm>,
    pager: PagedComposition<NoteVm>,
}

impl NotesViewVm {
    fn new(
        repository: InMemoryNoteRepository,
        notebook_id: Arc<Mutex<String>>,
        hub: MessageHub,
    ) -> Self {
        let source = CompositeVm::with_services("notes", hub.clone(), NullDispatcher::new());
        let search_term = Arc::new(Mutex::new(String::new()));
        let filtered_search = search_term.clone();
        let filtered = FilteredCompositeVm::new(source.clone(), move |note: &NoteVm| {
            note.matches(&lock(&filtered_search))
        });
        let vm = Self {
            core: ComponentVm::with_model("notes-view", (), hub, NullDispatcher::new()),
            repository,
            notebook_id,
            search_term,
            source,
            filtered,
            pager: PagedComposition::new(Vec::new(), PAGE_SIZE),
        };
        vm.reload();
        vm
    }

    pub fn set_notebook(&self, notebook_id: &str) {
        *lock(&self.notebook_id) = notebook_id.to_string();
        self.reload();
        // A different notebook starts on its first page, as in the other
        // flavors; set_source alone only clamps the old index.
        self.pager.move_to_first_page();
    }

    pub fn set_search_term(&self, term: &str) {
        *lock(&self.search_term) = term.to_string();
        self.refresh_page();
    }

    pub fn search_term(&self) -> String {
        lock(&self.search_term).clone()
    }

    pub fn visible_titles(&self) -> Vec<String> {
        self.refresh_page();
        self.pager
            .current_page()
            .into_iter()
            .map(|note| note.title())
            .collect()
    }

    /// The visible page as `(title, is_selected)` rows, so a view can mark
    /// the note that commands such as delete act on.
    pub fn visible_rows(&self) -> Vec<(String, bool)> {
        self.refresh_page();
        let current = self.source.current().map(|note| note.id());
        self.pager
            .current_page()
            .into_iter()
            .map(|note| {
                let selected = current.as_deref() == Some(note.id().as_str());
                (note.title(), selected)
            })
            .collect()
    }

    /// Keeps the selection on the visible page: when the current note is not
    /// shown, the first visible note becomes current; when nothing is shown,
    /// the selection is cleared. Returns the selected note.
    pub fn sync_selection_to_page(&self) -> Option<NoteModel> {
        self.refresh_page();
        let page = self.pager.current_page();
        if let Some(current) = self.source.current() {
            if page.iter().any(|note| note.id() == current.id()) {
                return Some(current.model());
            }
        }
        match page.first().cloned() {
            Some(first) => {
                let _ = self.source.set_current(Some(first.clone()));
                Some(first.model())
            }
            None => {
                let _ = self.source.set_current(None);
                None
            }
        }
    }

    pub fn page_summary(&self) -> String {
        self.refresh_page();
        let total = self.filtered.visible_count();
        if total == 0 {
            return "0 of 0".to_string();
        }
        let start = self.pager.current_page_index() * PAGE_SIZE + 1;
        let end = (start + self.pager.current_page().len() - 1).min(total);
        format!("{start}-{end} of {total}")
    }

    pub fn next_page(&self) {
        self.refresh_page();
        self.pager.next_page();
    }

    pub fn previous_page(&self) {
        self.refresh_page();
        self.pager.previous_page();
    }

    /// Selects the next note on the visible page. Returns the note when the
    /// selection changed.
    pub fn select_next_visible(&self) -> Option<NoteModel> {
        self.step_visible(true)
    }

    /// Selects the previous note on the visible page. Returns the note when
    /// the selection changed.
    pub fn select_previous_visible(&self) -> Option<NoteModel> {
        self.step_visible(false)
    }

    /// Moves the selection one row on the visible page. When the current note
    /// is not on the page, the first visible note becomes current. At the
    /// first or last row, the selection stays.
    fn step_visible(&self, forward: bool) -> Option<NoteModel> {
        self.refresh_page();
        let page = self.pager.current_page();
        let current = self.source.current().map(|note| note.id());
        let index = current
            .as_deref()
            .and_then(|id| page.iter().position(|note| note.id() == id));
        let target = match index {
            None => 0,
            Some(index) if forward => index + 1,
            Some(index) => index.checked_sub(1)?,
        };
        let note = page.get(target).cloned()?;
        if index == Some(target) {
            return None;
        }
        let _ = self.source.set_current(Some(note.clone()));
        Some(note.model())
    }

    pub fn current_note(&self) -> Option<NoteModel> {
        self.source.current().map(|note| note.model())
    }

    pub fn current_title(&self) -> String {
        self.current_note()
            .map(|note| note.title)
            .unwrap_or_default()
    }

    pub fn select_note(&self, note_id: &str) -> VmxResult<Option<NoteModel>> {
        self.reload();
        let note = self
            .source
            .items()
            .into_iter()
            .find(|note| note.id() == note_id)
            .ok_or_else(|| VmxError::InvalidArgument("unknown note".to_string()))?;
        self.source.set_current(Some(note.clone()))?;
        Ok(Some(note.model()))
    }

    pub fn select_first_visible(&self) -> Option<NoteModel> {
        self.refresh_page();
        let note = self.pager.current_page().first().cloned()?;
        let _ = self.source.set_current(Some(note.clone()));
        Some(note.model())
    }

    /// Reseats a saved note into its row, so the list, local search, delete
    /// prompt, and a later editor load see the persisted values.
    pub fn refresh_note(&self, note: &NoteModel) {
        let Some(row) = self
            .source
            .items()
            .into_iter()
            .find(|row| row.id() == note.id)
        else {
            return;
        };
        row.set_model(note.clone());
        self.refresh_page();
    }

    pub fn reload(&self) {
        let _ = self.source.clear();
        let notebook_id = lock(&self.notebook_id).clone();
        for note in self.repository.notes_for_notebook(&notebook_id) {
            let _ = self.source.add(NoteVm::new(note, self.core.hub()));
        }
        if let Some(first) = self.source.items().first().cloned() {
            let _ = self.source.set_current(Some(first));
        }
        self.refresh_page();
    }

    fn refresh_page(&self) {
        self.filtered.refresh();
        self.pager.set_source(self.filtered.visible());
    }
}

impl NotesViewVm {
    /// Releases the primitives this view-model owns once its core is disposed.
    fn release_owned(&self) {
        self.filtered.dispose();
        let _ = self.source.dispose();
    }
}

impl_node!(NotesViewVm);

#[derive(Clone)]
pub struct NoteFormVm {
    core: ComponentVm<()>,
    repository: InMemoryNoteRepository,
    current_note_id: Arc<Mutex<String>>,
    form: Arc<Mutex<FormVm<NoteDraft>>>,
    on_saved: SavedHook,
}

impl NoteFormVm {
    fn new(repository: InMemoryNoteRepository, note: NoteModel, hub: MessageHub) -> Self {
        let note_id = note.id.clone();
        let on_saved: SavedHook = Arc::new(Mutex::new(None));
        let form = build_form(
            repository.clone(),
            &note_id,
            NoteDraft::from_note(&note),
            hub.clone(),
            on_saved.clone(),
        );
        Self {
            core: ComponentVm::with_model("note-form", (), hub, NullDispatcher::new()),
            repository,
            current_note_id: Arc::new(Mutex::new(note_id)),
            form: Arc::new(Mutex::new(form)),
            on_saved,
        }
    }

    /// Calls `hook` with each note a save persisted (the workspace reseats
    /// it into the notes list).
    pub fn set_on_saved(&self, hook: impl Fn(&NoteModel) + Send + Sync + 'static) {
        *lock(&self.on_saved) = Some(Arc::new(hook));
    }

    /// Leaves the editor empty when no note is selected (for example after
    /// the last note is deleted), so it never shows or saves a stale note.
    pub fn clear(&self) {
        let form = build_form(
            self.repository.clone(),
            "",
            NoteDraft {
                title: String::new(),
                body: String::new(),
                tags: Vec::new(),
            },
            self.core.hub(),
            self.on_saved.clone(),
        );
        lock(&self.current_note_id).clear();
        let previous = std::mem::replace(&mut *lock(&self.form), form);
        previous.dispose();
    }

    /// Whether the editor holds a note.
    pub fn has_note(&self) -> bool {
        !lock(&self.current_note_id).is_empty()
    }

    pub fn load_note(&self, note: NoteModel) {
        let note_id = note.id.clone();
        let form = build_form(
            self.repository.clone(),
            &note_id,
            NoteDraft::from_note(&note),
            self.core.hub(),
            self.on_saved.clone(),
        );
        *lock(&self.current_note_id) = note_id;
        let previous = std::mem::replace(&mut *lock(&self.form), form);
        previous.dispose();
    }

    pub fn title(&self) -> String {
        lock(&self.form).model().title
    }

    pub fn body(&self) -> String {
        lock(&self.form).model().body
    }

    pub fn tags(&self) -> Vec<String> {
        lock(&self.form).model().tags
    }

    pub fn set_title(&self, title: &str) {
        let mut draft = lock(&self.form).model();
        draft.title = title.to_string();
        lock(&self.form).set_model(draft);
    }

    pub fn set_body(&self, body: &str) {
        let mut draft = lock(&self.form).model();
        draft.body = body.to_string();
        lock(&self.form).set_model(draft);
    }

    pub fn set_tags(&self, tags: Vec<String>) {
        let mut draft = lock(&self.form).model();
        draft.tags = tags;
        lock(&self.form).set_model(draft);
    }

    pub fn title_error(&self) -> Option<String> {
        lock(&self.form).field_error("title")
    }

    pub fn is_valid(&self) -> bool {
        lock(&self.form).is_valid()
    }

    pub fn is_dirty(&self) -> bool {
        lock(&self.form).is_dirty()
    }

    pub fn save(&self) -> VmxResult<()> {
        // Release the slot before persisting: a second save while this one is
        // pending must reach the form's single-flight rule instead of
        // waiting on this lock and saving again.
        if !self.has_note() {
            // Nothing is selected: there is no note to persist.
            return Ok(());
        }
        let form = lock(&self.form).clone();
        form.approve()
    }

    pub fn revert(&self) {
        lock(&self.form).revert();
    }
}

impl NoteFormVm {
    /// Releases the primitives this view-model owns once its core is disposed.
    fn release_owned(&self) {
        lock(&self.form).dispose();
    }
}

impl_node!(NoteFormVm);

fn build_form(
    repository: InMemoryNoteRepository,
    note_id: &str,
    draft: NoteDraft,
    hub: MessageHub,
    on_saved: SavedHook,
) -> FormVm<NoteDraft> {
    let note_id = note_id.to_string();
    FormVm::builder()
        .initial(draft)
        .hub(hub)
        .strict(true)
        .validator("title", |draft: &NoteDraft| {
            if draft.title.trim().is_empty() {
                Some("Title is required.".to_string())
            } else {
                None
            }
        })
        .persister(move |draft| {
            let saved = repository
                .save_draft(&note_id, draft)
                .ok_or_else(|| VmxError::InvalidArgument("note not found".to_string()))?;
            // The repository alone holds the saved note until it is reseated
            // into its NoteVm; otherwise the list and later editor loads use
            // the old model and a later save writes it back.
            let hook = lock(&on_saved).clone();
            if let Some(hook) = hook {
                hook(&saved);
            }
            Ok(())
        })
        .build()
        .expect("form builder is complete")
}

/// One search result: a note and the term that found it.
///
/// The derived equality includes the term, so pages for different terms are
/// never equal, and a refresh for a new term replaces the loaded pages and
/// their cursor (spec 21 §6.2).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SearchHit {
    pub term: String,
    pub note: NoteModel,
}

/// The cursor for the next page. It keeps the term of the loaded pages, so
/// Load more continues that term even after the query is edited.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SearchCursor {
    pub term: String,
    pub offset: usize,
}

/// Search progress that `refresh()` and `load_more()` share. No lock on it is
/// held while the pager runs, so a refresh re-entered from a hub subscriber
/// cannot deadlock.
#[derive(Debug, Default)]
struct SearchProgress {
    /// The `refresh()` calls that are running. Load more is unavailable while
    /// one runs.
    refreshing: usize,
    /// The first-page fetches started so far.
    first_page_fetches: usize,
    /// The term of the latest first-page fetch.
    first_page_term: String,
}

/// Ends one `refresh()` call, also when the pager panics.
struct RefreshRun<'a>(&'a Mutex<SearchProgress>);

impl Drop for RefreshRun<'_> {
    fn drop(&mut self) {
        lock(self.0).refreshing -= 1;
    }
}

#[derive(Clone)]
pub struct GlobalSearchVm {
    core: ComponentVm<()>,
    state: SearchableState<NoteModel>,
    pages: TokenPagedComposition<SearchHit, SearchCursor>,
    progress: Arc<Mutex<SearchProgress>>,
}

impl GlobalSearchVm {
    fn new(repository: InMemoryNoteRepository, hub: MessageHub) -> Self {
        // The searchable state owns the term. The token pager pages over
        // repository search results, which use the same matching rule.
        let state = SearchableState::from_items(
            {
                let repository = repository.clone();
                move || repository.notes()
            },
            |note: &NoteModel, term: &str| note_matches(note, term),
        );
        let progress = Arc::new(Mutex::new(SearchProgress::default()));
        let loader_state = state.clone();
        let loader_progress = progress.clone();
        let pages = TokenPagedComposition::with_loader_and_hub(
            None,
            move |cursor: Option<SearchCursor>| {
                // The first page uses the current term. A later page uses the
                // term in the cursor, so Load more continues the term of the
                // loaded pages.
                let (term, offset) = match cursor {
                    Some(cursor) => (cursor.term, cursor.offset),
                    None => {
                        let term = loader_state.search_term();
                        let mut progress = lock(&loader_progress);
                        progress.first_page_fetches += 1;
                        progress.first_page_term = term.clone();
                        (term, 0)
                    }
                };
                let (notes, next) = repository.search_notes(&term, offset, SEARCH_PAGE_SIZE);
                let hits = notes
                    .into_iter()
                    .map(|note| SearchHit {
                        term: term.clone(),
                        note,
                    })
                    .collect();
                (hits, next.map(|offset| SearchCursor { term, offset }))
            },
            hub.clone(),
        );
        Self {
            core: ComponentVm::with_model("global-search", (), hub, NullDispatcher::new()),
            state,
            pages,
            progress,
        }
    }

    pub fn set_query(&self, query: &str) {
        self.state.set_search_term(query);
    }

    pub fn query(&self) -> String {
        self.state.search_term()
    }

    /// Refreshes the results for the current term.
    ///
    /// Load more is unavailable while this runs. A load that passed its
    /// check just before the refresh began can still start during the
    /// refresh, and the pager then discards the refresh (spec 21 §6.2). So
    /// when the results do not all carry the term that the refresh fetched,
    /// this searches again, at most `SEARCH_RUNS` times in all.
    pub fn refresh(&self) {
        lock(&self.progress).refreshing += 1;
        let _run = RefreshRun(&self.progress);
        for _ in 0..SEARCH_RUNS {
            let fetches = lock(&self.progress).first_page_fetches;
            self.pages.refresh();
            let (fetched, term) = {
                let progress = lock(&self.progress);
                (
                    progress.first_page_fetches != fetches,
                    progress.first_page_term.clone(),
                )
            };
            // A refused or disposed refresh fetched nothing to check.
            if !fetched || self.pages.items().iter().all(|hit| hit.term == term) {
                return;
            }
        }
    }

    /// Loads and appends the next page. A call made during a refresh does
    /// nothing, so the results never mix two terms.
    pub fn load_more(&self) {
        if lock(&self.progress).refreshing > 0 {
            return;
        }
        self.pages.load_next();
    }

    /// Reports whether Load more can run: a next page exists and no refresh
    /// is running.
    pub fn can_load_more(&self) -> bool {
        lock(&self.progress).refreshing == 0 && self.pages.can_load_more()
    }

    pub fn result_titles(&self) -> Vec<String> {
        self.pages
            .items()
            .into_iter()
            .map(|hit| hit.note.title)
            .collect()
    }
}

impl GlobalSearchVm {
    /// Releases the primitives this view-model owns once its core is disposed.
    fn release_owned(&self) {
        self.state.dispose();
        self.pages.dispose();
    }
}

impl_node!(GlobalSearchVm);

#[derive(Clone)]
pub struct NotificationsVm {
    core: ComponentVm<()>,
    hub: NotificationHub,
    active_vms: Arc<Mutex<Vec<NotificationVm>>>,
}

impl NotificationsVm {
    fn new(hub: MessageHub) -> Self {
        Self {
            core: ComponentVm::with_model("notifications", (), hub, NullDispatcher::new()),
            hub: NotificationHub::new(),
            active_vms: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn post(&self, kind: NotificationType, message: impl Into<String>) -> u64 {
        let notification = self.hub.post(kind, message);
        let (resolved, dropped) = {
            let mut active = lock(&self.active_vms);
            // Entries resolved through the hub must not hold a cap slot.
            let resolved = active
                .extract_if(.., |vm| vm.is_resolved())
                .collect::<Vec<_>>();
            active.push(NotificationVm::with_hub(
                notification.clone(),
                self.hub.clone(),
                60_000,
            ));
            let excess = active.len().saturating_sub(NOTIFICATION_CAP);
            (resolved, active.drain(..excess).collect::<Vec<_>>())
        };
        // A removed entry is disposed, as in spec 16 §8.1.
        for vm in resolved {
            vm.dispose();
        }
        // Over the cap, the oldest are dismissed, not just hidden, so the
        // hub's pending list stays bounded too.
        for vm in dropped {
            vm.dismiss();
            vm.dispose();
        }
        notification.id
    }

    pub fn resolve(&self, notification_id: u64, reaction: NotificationReaction) {
        self.hub.resolve(notification_id, reaction);
        let resolved = lock(&self.active_vms)
            .extract_if(.., |vm| vm.is_resolved())
            .collect::<Vec<_>>();
        for vm in resolved {
            vm.dispose();
        }
    }

    /// Returns the entries that are still pending, oldest first.
    pub fn visible(&self) -> Vec<NotificationVm> {
        lock(&self.active_vms).clone()
    }

    pub fn messages(&self) -> Vec<String> {
        self.hub
            .pending()
            .into_iter()
            .map(|notification| notification.message)
            .collect()
    }
}

impl NotificationsVm {
    /// Releases the primitives this view-model owns once its core is disposed.
    fn release_owned(&self) {
        let remaining = std::mem::take(&mut *lock(&self.active_vms));
        for vm in remaining {
            vm.dispose();
        }
        self.hub.dispose();
    }
}

impl_node!(NotificationsVm);

#[derive(Clone)]
pub struct EditorModeVm {
    core: ComponentVm<()>,
    discriminator: DiscriminatorVm<String>,
}

impl EditorModeVm {
    fn new(hub: MessageHub) -> Self {
        Self {
            core: ComponentVm::with_model("editor-mode", (), hub, NullDispatcher::new()),
            discriminator: DiscriminatorVm::new("edit".to_string()),
        }
    }

    pub fn mode(&self) -> String {
        self.discriminator.active_key()
    }

    pub fn show_edit(&self) {
        self.discriminator.set_active_key("edit".to_string());
    }

    pub fn show_preview(&self) {
        self.discriminator.set_active_key("preview".to_string());
    }

    pub fn toggle(&self) {
        if self.mode() == "edit" {
            self.show_preview();
        } else {
            self.show_edit();
        }
    }
}

impl EditorModeVm {
    /// Releases the primitives this view-model owns once its core is disposed.
    fn release_owned(&self) {
        self.discriminator.dispose();
    }
}

impl_node!(EditorModeVm);

type WorkspaceAggregate = AggregateVm6<
    NotebooksVm,
    NotesViewVm,
    NoteFormVm,
    GlobalSearchVm,
    NotificationsVm,
    EditorModeVm,
>;

#[derive(Clone)]
pub struct WorkspaceVm {
    repository: InMemoryNoteRepository,
    aggregate: WorkspaceAggregate,
    notebooks: NotebooksVm,
    notes: NotesViewVm,
    form: NoteFormVm,
    global_search: GlobalSearchVm,
    notifications: NotificationsVm,
    editor: EditorModeVm,
    pending_delete: Arc<Mutex<Option<(String, String, u64)>>>,
    delete_command: DecoratorCommand<RelayCommand>,
}

impl WorkspaceVm {
    pub fn seeded() -> VmxResult<Self> {
        Self::new(InMemoryNoteRepository::seeded())
    }

    pub fn new(repository: InMemoryNoteRepository) -> VmxResult<Self> {
        let hub = MessageHub::new();
        let notebooks = NotebooksVm::new(&repository, hub.clone());
        let notebook_id = notebooks.current_id.clone();
        let notes = NotesViewVm::new(repository.clone(), notebook_id, hub.clone());
        let selected = notes
            .current_note()
            .or_else(|| repository.notes().first().cloned())
            .ok_or_else(|| {
                VmxError::InvalidArgument("seed data requires at least one note".to_string())
            })?;
        let form = NoteFormVm::new(repository.clone(), selected, hub.clone());
        let global_search = GlobalSearchVm::new(repository.clone(), hub.clone());
        let notifications = NotificationsVm::new(hub.clone());
        let editor = EditorModeVm::new(hub);
        let aggregate = AggregateVm6::new(
            "workspace",
            notebooks.clone(),
            notes.clone(),
            form.clone(),
            global_search.clone(),
            notifications.clone(),
            editor.clone(),
        );
        aggregate.construct()?;
        form.set_on_saved({
            let notes = notes.clone();
            move |note| notes.refresh_note(note)
        });
        let pending_delete = Arc::new(Mutex::new(None));
        let delete_command = RelayCommand::new({
            let notes = notes.clone();
            let notifications = notifications.clone();
            let pending_delete = pending_delete.clone();
            move || {
                // One delete confirmation at a time: a second request would
                // replace the only slot that `y`/`r` resolve and strand the
                // first confirmation.
                if lock(&pending_delete).is_some() {
                    return;
                }
                if let Some(note) = notes.current_note() {
                    let message = format!("Delete note '{}'?", note.title);
                    let notification_id =
                        notifications.post(NotificationType::Confirmation, message);
                    *lock(&pending_delete) = Some((note.id, note.title, notification_id));
                }
            }
        })
        // Fluent helper (`CommandExt`): only a selected note can be deleted.
        // `NO_HOOK` stands in for the absent pre- and post-actions.
        .wrap_with(
            Some({
                let notes = notes.clone();
                move || notes.current_note().is_some()
            }),
            NO_HOOK,
            NO_HOOK,
        );
        Ok(Self {
            repository,
            aggregate,
            notebooks,
            notes,
            form,
            global_search,
            notifications,
            editor,
            pending_delete,
            delete_command,
        })
    }

    pub fn notebooks(&self) -> NotebooksVm {
        self.notebooks.clone()
    }

    pub fn notes(&self) -> NotesViewVm {
        self.notes.clone()
    }

    pub fn form(&self) -> NoteFormVm {
        self.form.clone()
    }

    pub fn global_search(&self) -> GlobalSearchVm {
        self.global_search.clone()
    }

    pub fn notifications(&self) -> NotificationsVm {
        self.notifications.clone()
    }

    pub fn editor(&self) -> EditorModeVm {
        self.editor.clone()
    }

    pub fn select_notebook(&self, notebook_id: &str) -> VmxResult<()> {
        self.notebooks.select(notebook_id)?;
        self.reject_delete_current();
        self.notes.set_notebook(notebook_id);
        match self.notes.select_first_visible() {
            Some(note) => self.form.load_note(note),
            None => self.form.clear(),
        }
        Ok(())
    }

    // Paging, searching, and switching notebooks cancel a pending delete, so
    // `y` confirms only a prompt that the user saw on the current screen.
    // Paging and searching never change the selection or reload the editor,
    // so a hidden note keeps its draft (ADR-0201 §2.1). `d` deletes the
    // current note even while its row is hidden. The editor shows that note,
    // and the prompt names it.

    pub fn next_page(&self) {
        self.reject_delete_current();
        self.notes.next_page();
    }

    pub fn previous_page(&self) {
        self.reject_delete_current();
        self.notes.previous_page();
    }

    pub fn set_search_term(&self, term: &str) {
        self.reject_delete_current();
        self.notes.set_search_term(term);
    }

    /// Selects the next note on the visible page and loads it into the
    /// editor when the selection changed.
    pub fn select_next_note(&self) {
        if let Some(note) = self.notes.select_next_visible() {
            self.form.load_note(note);
        }
    }

    /// Selects the previous note on the visible page and loads it into the
    /// editor when the selection changed.
    pub fn select_previous_note(&self) {
        if let Some(note) = self.notes.select_previous_visible() {
            self.form.load_note(note);
        }
    }

    pub fn select_note(&self, note_id: &str) -> VmxResult<()> {
        if let Some(note) = self.notes.select_note(note_id)? {
            self.form.load_note(note);
        }
        Ok(())
    }

    pub fn request_delete_current(&self) {
        self.delete_command.execute();
    }

    pub fn reject_delete_current(&self) {
        if let Some((_, _, notification_id)) = lock(&self.pending_delete).take() {
            self.notifications
                .resolve(notification_id, NotificationReaction::Reject);
        }
    }

    pub fn approve_delete_current(&self) {
        let Some((note_id, title, notification_id)) = lock(&self.pending_delete).take() else {
            return;
        };
        self.notifications
            .resolve(notification_id, NotificationReaction::Approve);
        if self.repository.delete_note(&note_id).is_some() {
            self.notes.reload();
            match self.notes.sync_selection_to_page() {
                Some(note) => self.form.load_note(note),
                None => self.form.clear(),
            }
            self.notifications
                .post(NotificationType::Notification, format!("Deleted '{title}'"));
        }
    }

    pub fn smoke_summary(&self) -> String {
        self.global_search.set_query("vmx");
        self.global_search.refresh();
        format!(
            "VMx Rust TUI smoke: notebook={}, notes={}, search={}",
            self.notebooks.current_title(),
            self.notes.visible_titles().len(),
            self.global_search.result_titles().len()
        )
    }

    pub fn dispose(&self) -> VmxResult<()> {
        self.aggregate.dispose()
    }
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

macro_rules! impl_node {
    ($name:ident) => {
        impl PartialEq for $name {
            fn eq(&self, other: &Self) -> bool {
                self.core.id() == other.core.id()
            }
        }

        impl Eq for $name {}

        impl VmNode for $name {
            fn id(&self) -> usize {
                self.core.id()
            }

            fn construct(&self) -> VmxResult<()> {
                self.core.construct()
            }

            fn destruct(&self) -> VmxResult<()> {
                self.core.destruct()
            }

            fn dispose(&self) -> VmxResult<()> {
                let result = self.core.dispose();
                self.release_owned();
                result
            }

            fn status(&self) -> vmx::ConstructionStatus {
                self.core.status()
            }

            fn set_parent_id(&self, parent_id: Option<usize>) {
                self.core.set_parent_id(parent_id);
            }

            fn parent_id(&self) -> Option<usize> {
                self.core.parent_id()
            }

            fn set_parent_handle(&self, parent: Option<ParentHandle>) {
                self.core.set_parent_handle(parent);
            }

            fn parent_handle(&self) -> Option<ParentHandle> {
                self.core.parent_handle()
            }

            fn set_current_flag(&self, is_current: bool) {
                self.core.set_current_flag(is_current);
            }

            fn is_current(&self) -> bool {
                self.core.is_current()
            }
        }
    };
}

pub(crate) use impl_node;
