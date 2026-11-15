use crate::{views, InMemoryNoteRepository, WorkspaceVm};
use crossterm::{
    event::{self, Event, KeyCode},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{backend::CrosstermBackend, Terminal};
use std::io::{self, Stdout};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use vmx::{Message, Subscription, VmxError, VmxResult};

/// Flags a change to the workspace, so the terminal loop redraws without a
/// key event. A timed notification can expire with no key press, and
/// notifications publish on the notification hub, not the workspace hub. So
/// the signal watches both: the workspace hub and the notification hub's
/// `pending_changed` stream.
pub struct RedrawSignal {
    changed: Arc<AtomicBool>,
    // A subscription ends when it is dropped, so the signal keeps both.
    _subscriptions: [Subscription; 2],
}

impl RedrawSignal {
    pub fn new(workspace: &WorkspaceVm) -> Self {
        let changed = Arc::new(AtomicBool::new(false));
        let flag = {
            let changed = Arc::clone(&changed);
            move |_: &Message| changed.store(true, Ordering::SeqCst)
        };
        let workspace_changes = workspace.hub().subscribe(flag.clone());
        let pending_changes = workspace
            .notifications()
            .hub()
            .pending_changed()
            .subscribe(flag);
        Self {
            changed,
            _subscriptions: [workspace_changes, pending_changes],
        }
    }

    /// Reports whether a change arrived since the last call, and clears the flag.
    pub fn take(&self) -> bool {
        self.changed.swap(false, Ordering::SeqCst)
    }
}

pub fn run_smoke() -> VmxResult<String> {
    let workspace = WorkspaceVm::new(InMemoryNoteRepository::seeded())?;
    let summary = workspace.smoke_summary();
    workspace.dispose()?;
    Ok(summary)
}

pub fn run_interactive() -> VmxResult<()> {
    let mut terminal = TerminalSession::enter().map_err(to_vmx_error)?;
    let workspace = WorkspaceVm::new(InMemoryNoteRepository::seeded())?;
    let result = run_loop(&mut terminal.terminal, &workspace);
    let dispose_result = workspace.dispose();
    terminal.leave().map_err(to_vmx_error)?;
    result?;
    dispose_result
}

fn run_loop(
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
    workspace: &WorkspaceVm,
) -> VmxResult<()> {
    let redraw = RedrawSignal::new(workspace);
    let mut dirty = true;
    loop {
        if dirty {
            terminal
                .draw(|frame| views::render(frame, workspace))
                .map_err(to_vmx_error)?;
            dirty = false;
        }
        if event::poll(Duration::from_millis(100)).map_err(to_vmx_error)? {
            match event::read().map_err(to_vmx_error)? {
                Event::Key(key) => {
                    if !handle_key(workspace, key.code) {
                        break;
                    }
                    dirty = true;
                }
                // The loop no longer redraws on a timer, so a resize redraws here.
                Event::Resize(_, _) => dirty = true,
                _ => {}
            }
        }
        if redraw.take() {
            dirty = true;
        }
    }
    Ok(())
}

/// Dispatches one key to the workspace. Returns `false` when the app should
/// quit. Kept separate from the terminal loop so tests can drive the app
/// through the same key bindings.
pub fn handle_key(workspace: &WorkspaceVm, code: KeyCode) -> bool {
    match code {
        KeyCode::Char('q') => return false,
        KeyCode::Char('/') => workspace.set_search_term("vmx"),
        KeyCode::Char('x') => workspace.set_search_term(""),
        KeyCode::Char('n') => workspace.next_page(),
        KeyCode::Char('p') => workspace.previous_page(),
        KeyCode::Char('j') => workspace.select_next_note(),
        KeyCode::Char('k') => workspace.select_previous_note(),
        KeyCode::Char('m') => workspace.editor().toggle(),
        KeyCode::Char('d') => workspace.request_delete_current(),
        KeyCode::Char('y') => workspace.approve_delete_current(),
        KeyCode::Char('r') => workspace.reject_delete_current(),
        _ => {}
    }
    true
}

fn to_vmx_error(error: io::Error) -> VmxError {
    VmxError::Other(error.to_string())
}

struct TerminalSession {
    terminal: Terminal<CrosstermBackend<Stdout>>,
    active: bool,
}

impl TerminalSession {
    fn enter() -> io::Result<Self> {
        enable_raw_mode()?;
        let mut stdout = io::stdout();
        execute!(stdout, EnterAlternateScreen)?;
        let terminal = Terminal::new(CrosstermBackend::new(stdout))?;
        Ok(Self {
            terminal,
            active: true,
        })
    }

    fn leave(&mut self) -> io::Result<()> {
        if self.active {
            disable_raw_mode()?;
            execute!(self.terminal.backend_mut(), LeaveAlternateScreen)?;
            self.terminal.show_cursor()?;
            self.active = false;
        }
        Ok(())
    }
}

impl Drop for TerminalSession {
    fn drop(&mut self) {
        let _ = self.leave();
    }
}
