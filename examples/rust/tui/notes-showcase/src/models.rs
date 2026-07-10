use std::sync::{Arc, Mutex, MutexGuard};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NotebookModel {
    pub id: String,
    pub title: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NoteModel {
    pub id: String,
    pub notebook_id: String,
    pub title: String,
    pub body: String,
    pub tags: Vec<String>,
    pub starred: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NoteDraft {
    pub title: String,
    pub body: String,
    pub tags: Vec<String>,
}

impl NoteDraft {
    pub fn from_note(note: &NoteModel) -> Self {
        Self {
            title: note.title.clone(),
            body: note.body.clone(),
            tags: note.tags.clone(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct InMemoryNoteRepository {
    inner: Arc<Mutex<RepositoryInner>>,
}

#[derive(Debug, Clone)]
struct RepositoryInner {
    notebooks: Vec<NotebookModel>,
    notes: Vec<NoteModel>,
}

impl InMemoryNoteRepository {
    pub fn new(notebooks: Vec<NotebookModel>, notes: Vec<NoteModel>) -> Self {
        Self {
            inner: Arc::new(Mutex::new(RepositoryInner { notebooks, notes })),
        }
    }

    pub fn seeded() -> Self {
        Self::new(
            vec![
                NotebookModel {
                    id: "product".to_string(),
                    title: "Product".to_string(),
                },
                NotebookModel {
                    id: "engineering".to_string(),
                    title: "Engineering".to_string(),
                },
            ],
            vec![
                NoteModel {
                    id: "rust-parity".to_string(),
                    notebook_id: "product".to_string(),
                    title: "Rust flavor parity".to_string(),
                    body: "Use VMx view models to make the Rust flavor feel native.".to_string(),
                    tags: vec!["rust".to_string(), "vmx".to_string()],
                    starred: true,
                },
                NoteModel {
                    id: "release-channels".to_string(),
                    notebook_id: "product".to_string(),
                    title: "Release channels".to_string(),
                    body: "Track NuGet, npm, Swift, and crates.io readiness.".to_string(),
                    tags: vec!["release".to_string()],
                    starred: false,
                },
                NoteModel {
                    id: "docs-refresh".to_string(),
                    notebook_id: "product".to_string(),
                    title: "Documentation refresh".to_string(),
                    body: "Keep site, wiki, and in-repo docs synchronized.".to_string(),
                    tags: vec!["docs".to_string()],
                    starred: false,
                },
                NoteModel {
                    id: "vmx-inspector".to_string(),
                    notebook_id: "engineering".to_string(),
                    title: "VMx inspector notes".to_string(),
                    body: "Inspect lifecycle and message hub traffic from a terminal host."
                        .to_string(),
                    tags: vec!["vmx".to_string(), "inspector".to_string()],
                    starred: false,
                },
                NoteModel {
                    id: "theme-polish".to_string(),
                    notebook_id: "product".to_string(),
                    title: "Theme polish".to_string(),
                    body: "Show VMx theme state in every supported example.".to_string(),
                    tags: vec!["theme".to_string(), "vmx".to_string()],
                    starred: true,
                },
            ],
        )
    }

    pub fn notebooks(&self) -> Vec<NotebookModel> {
        lock(&self.inner).notebooks.clone()
    }

    pub fn notes(&self) -> Vec<NoteModel> {
        lock(&self.inner).notes.clone()
    }

    pub fn notes_for_notebook(&self, notebook_id: &str) -> Vec<NoteModel> {
        self.notes()
            .into_iter()
            .filter(|note| note.notebook_id == notebook_id)
            .collect()
    }

    pub fn note(&self, note_id: &str) -> Option<NoteModel> {
        self.notes().into_iter().find(|note| note.id == note_id)
    }

    pub fn save_draft(&self, note_id: &str, draft: &NoteDraft) -> Option<NoteModel> {
        let mut inner = lock(&self.inner);
        let note = inner.notes.iter_mut().find(|note| note.id == note_id)?;
        note.title = draft.title.clone();
        note.body = draft.body.clone();
        note.tags = draft.tags.clone();
        Some(note.clone())
    }

    pub fn delete_note(&self, note_id: &str) -> Option<NoteModel> {
        let mut inner = lock(&self.inner);
        let index = inner.notes.iter().position(|note| note.id == note_id)?;
        Some(inner.notes.remove(index))
    }
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}
