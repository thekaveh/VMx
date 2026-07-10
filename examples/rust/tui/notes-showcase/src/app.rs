use crate::{views, InMemoryNoteRepository, WorkspaceVm};
use crossterm::{
    event::{self, Event, KeyCode},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{backend::CrosstermBackend, Terminal};
use std::io::{self, Stdout};
use std::time::Duration;
use vmx::{VmxError, VmxResult};

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
    loop {
        terminal
            .draw(|frame| views::render(frame, workspace))
            .map_err(to_vmx_error)?;
        if !event::poll(Duration::from_millis(100)).map_err(to_vmx_error)? {
            continue;
        }
        if let Event::Key(key) = event::read().map_err(to_vmx_error)? {
            match key.code {
                KeyCode::Char('q') => break,
                KeyCode::Char('/') => workspace.notes().set_search_term("vmx"),
                KeyCode::Char('x') => workspace.notes().set_search_term(""),
                KeyCode::Char('n') => workspace.notes().next_page(),
                KeyCode::Char('p') => workspace.notes().previous_page(),
                KeyCode::Char('m') => {
                    workspace.editor().toggle()?;
                }
                KeyCode::Char('d') => workspace.request_delete_current(),
                KeyCode::Char('y') => workspace.approve_delete_current(),
                KeyCode::Char('r') => workspace.reject_delete_current(),
                _ => {}
            }
        }
    }
    Ok(())
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
