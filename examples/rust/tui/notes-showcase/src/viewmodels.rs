use crate::models::{InMemoryNoteRepository, NoteDraft, NoteModel, NotebookModel};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard};
use vmx::{
    AggregateVm6, Command, ComponentVm, CompositeVm, DiscriminatorVm, FilteredCompositeVm, FormVm,
    MessageHub, NotificationHub, NotificationReaction, NotificationType, NotificationVm,
    NullDispatcher, PagedComposition, RelayCommand, SearchableState, TokenPagedComposition, VmNode,
    VmxError, VmxResult,
};

const PAGE_SIZE: usize = 2;
const SEARCH_PAGE_SIZE: usize = 2;

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

    pub fn reload(&self) {
        self.source.clear();
        let notebook_id = lock(&self.notebook_id).clone();
        for note in self.repository.notes_for_notebook(&notebook_id) {
            let _ = self.source.add(NoteVm::new(note, MessageHub::new()));
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

impl_node!(NotesViewVm);

#[derive(Clone)]
pub struct NoteFormVm {
    core: ComponentVm<()>,
    repository: InMemoryNoteRepository,
    current_note_id: Arc<Mutex<String>>,
    form: Arc<Mutex<FormVm<NoteDraft>>>,
}

impl NoteFormVm {
    fn new(repository: InMemoryNoteRepository, note: NoteModel, hub: MessageHub) -> Self {
        let note_id = note.id.clone();
        let form = build_form(
            repository.clone(),
            &note_id,
            NoteDraft::from_note(&note),
            hub.clone(),
        );
        Self {
            core: ComponentVm::with_model("note-form", (), hub, NullDispatcher::new()),
            repository,
            current_note_id: Arc::new(Mutex::new(note_id)),
            form: Arc::new(Mutex::new(form)),
        }
    }

    pub fn load_note(&self, note: NoteModel) {
        let note_id = note.id.clone();
        let form = build_form(
            self.repository.clone(),
            &note_id,
            NoteDraft::from_note(&note),
            MessageHub::new(),
        );
        *lock(&self.current_note_id) = note_id;
        *lock(&self.form) = form;
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
        lock(&self.form).approve()
    }

    pub fn revert(&self) {
        lock(&self.form).revert();
    }
}

impl_node!(NoteFormVm);

fn build_form(
    repository: InMemoryNoteRepository,
    note_id: &str,
    draft: NoteDraft,
    hub: MessageHub,
) -> FormVm<NoteDraft> {
    let note_id = note_id.to_string();
    FormVm::builder()
        .initial(draft)
        .hub(hub)
        .strict(true)
        .validator("title", |draft: &NoteDraft| {
            if draft.title.trim().is_empty() {
                Some("Title is required".to_string())
            } else {
                None
            }
        })
        .model_validator(|draft: &NoteDraft| {
            let mut errors = BTreeMap::new();
            if draft.body.trim().is_empty() {
                errors.insert("body".to_string(), "Body is required".to_string());
            }
            errors
        })
        .persister(move |draft| {
            repository
                .save_draft(&note_id, draft)
                .map(|_| ())
                .ok_or_else(|| VmxError::InvalidArgument("note not found".to_string()))
        })
        .build()
        .expect("form builder is complete")
}

#[derive(Clone)]
pub struct GlobalSearchVm {
    core: ComponentVm<()>,
    query: Arc<Mutex<String>>,
    state: SearchableState<NoteModel>,
    pages: TokenPagedComposition<NoteModel, usize>,
}

impl GlobalSearchVm {
    fn new(repository: InMemoryNoteRepository, hub: MessageHub) -> Self {
        let query = Arc::new(Mutex::new(String::new()));
        let state_query = query.clone();
        let state = SearchableState::from_items(
            {
                let repository = repository.clone();
                move || repository.notes()
            },
            move |note: &NoteModel, _term: &str| note_matches(note, &lock(&state_query)),
        );
        let loader_query = query.clone();
        let pages = TokenPagedComposition::with_loader_and_hub(
            Some(0usize),
            move |token| {
                let offset = token.unwrap_or(0);
                let matches = repository
                    .notes()
                    .into_iter()
                    .filter(|note| note_matches(note, &lock(&loader_query)))
                    .collect::<Vec<_>>();
                let page = matches
                    .iter()
                    .skip(offset)
                    .take(SEARCH_PAGE_SIZE)
                    .cloned()
                    .collect::<Vec<_>>();
                let next = offset + page.len();
                let next_token = (next < matches.len()).then_some(next);
                (page, next_token)
            },
            hub.clone(),
        );
        Self {
            core: ComponentVm::with_model("global-search", (), hub, NullDispatcher::new()),
            query,
            state,
            pages,
        }
    }

    pub fn set_query(&self, query: &str) {
        *lock(&self.query) = query.to_string();
        self.state.set_search_term(query);
    }

    pub fn query(&self) -> String {
        lock(&self.query).clone()
    }

    pub fn refresh(&self) {
        self.pages.refresh();
    }

    pub fn load_more(&self) {
        self.pages.load_next();
    }

    pub fn can_load_more(&self) -> bool {
        self.pages.can_load_more()
    }

    pub fn result_titles(&self) -> Vec<String> {
        self.pages
            .items()
            .into_iter()
            .map(|note| note.title)
            .collect()
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
        lock(&self.active_vms).push(NotificationVm::with_hub(
            notification.clone(),
            self.hub.clone(),
            60_000,
        ));
        notification.id
    }

    pub fn resolve(&self, notification_id: u64, reaction: NotificationReaction) {
        self.hub.resolve(notification_id, reaction);
        lock(&self.active_vms).retain(|vm| !vm.is_resolved());
    }

    pub fn messages(&self) -> Vec<String> {
        self.hub
            .pending()
            .into_iter()
            .map(|notification| notification.message)
            .collect()
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
            discriminator: DiscriminatorVm::new(
                "edit".to_string(),
                ["edit".to_string(), "preview".to_string()],
            ),
        }
    }

    pub fn mode(&self) -> String {
        self.discriminator.active_key()
    }

    pub fn show_edit(&self) -> VmxResult<()> {
        self.discriminator.set_active_key("edit".to_string())
    }

    pub fn show_preview(&self) -> VmxResult<()> {
        self.discriminator.set_active_key("preview".to_string())
    }

    pub fn toggle(&self) -> VmxResult<()> {
        if self.mode() == "edit" {
            self.show_preview()
        } else {
            self.show_edit()
        }
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
    delete_command: RelayCommand,
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
        let pending_delete = Arc::new(Mutex::new(None));
        let delete_command = RelayCommand::new({
            let notes = notes.clone();
            let notifications = notifications.clone();
            let pending_delete = pending_delete.clone();
            move || {
                if let Some(note) = notes.current_note() {
                    let message = format!("Delete note '{}'?", note.title);
                    let notification_id =
                        notifications.post(NotificationType::Confirmation, message);
                    *lock(&pending_delete) = Some((note.id, note.title, notification_id));
                }
            }
        });
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
        self.notes.set_notebook(notebook_id);
        if let Some(note) = self.notes.select_first_visible() {
            self.form.load_note(note);
        }
        Ok(())
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
            if let Some(note) = self.notes.select_first_visible() {
                self.form.load_note(note);
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
        self.aggregate.destruct()
    }
}

fn note_matches(note: &NoteModel, term: &str) -> bool {
    let term = term.trim().to_lowercase();
    if term.is_empty() {
        return true;
    }
    note.title.to_lowercase().contains(&term)
        || note.body.to_lowercase().contains(&term)
        || note
            .tags
            .iter()
            .any(|tag| tag.to_lowercase().contains(&term))
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
                self.core.dispose()
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
