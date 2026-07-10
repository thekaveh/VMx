use crate::viewmodels::WorkspaceVm;
use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::Line,
    widgets::{Block, Borders, List, ListItem, Paragraph},
    Frame,
};

pub fn render(frame: &mut Frame<'_>, workspace: &WorkspaceVm) {
    let root = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(12),
            Constraint::Length(4),
        ])
        .split(frame.area());
    render_header(frame, root[0], workspace);
    render_body(frame, root[1], workspace);
    render_notifications(frame, root[2], workspace);
}

fn render_header(frame: &mut Frame<'_>, area: Rect, workspace: &WorkspaceVm) {
    let text = format!(
        "VMx Rust Notes Showcase | notebook: {} | mode: {}",
        workspace.notebooks().current_title(),
        workspace.editor().mode()
    );
    frame.render_widget(
        Paragraph::new(text).block(Block::default().borders(Borders::ALL).title("Workspace")),
        area,
    );
}

fn render_body(frame: &mut Frame<'_>, area: Rect, workspace: &WorkspaceVm) {
    let columns = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(24),
            Constraint::Percentage(32),
            Constraint::Percentage(44),
        ])
        .split(area);
    render_notebooks(frame, columns[0], workspace);
    render_notes(frame, columns[1], workspace);
    render_editor(frame, columns[2], workspace);
}

fn render_notebooks(frame: &mut Frame<'_>, area: Rect, workspace: &WorkspaceVm) {
    let current = workspace.notebooks().current_title();
    let items = workspace
        .notebooks()
        .titles()
        .into_iter()
        .map(|title| {
            if title == current {
                ListItem::new(Line::from(title)).style(
                    Style::default()
                        .fg(Color::Cyan)
                        .add_modifier(Modifier::BOLD),
                )
            } else {
                ListItem::new(Line::from(title))
            }
        })
        .collect::<Vec<_>>();
    frame.render_widget(
        List::new(items).block(Block::default().borders(Borders::ALL).title("Notebooks")),
        area,
    );
}

fn render_notes(frame: &mut Frame<'_>, area: Rect, workspace: &WorkspaceVm) {
    let title = format!(
        "Notes {} | search '{}'",
        workspace.notes().page_summary(),
        workspace.notes().search_term()
    );
    let items = workspace
        .notes()
        .visible_titles()
        .into_iter()
        .map(ListItem::new)
        .collect::<Vec<_>>();
    frame.render_widget(
        List::new(items).block(Block::default().borders(Borders::ALL).title(title)),
        area,
    );
}

fn render_editor(frame: &mut Frame<'_>, area: Rect, workspace: &WorkspaceVm) {
    let form = workspace.form();
    let mut lines = vec![
        Line::from(format!("Title: {}", form.title())),
        Line::from(format!("Tags: {}", form.tags().join(", "))),
        Line::from(""),
        Line::from(form.body()),
    ];
    if let Some(error) = form.title_error() {
        lines.push(Line::from(""));
        lines.push(Line::from(format!("Error: {error}")));
    }
    frame.render_widget(
        Paragraph::new(lines).block(Block::default().borders(Borders::ALL).title("Editor")),
        area,
    );
}

fn render_notifications(frame: &mut Frame<'_>, area: Rect, workspace: &WorkspaceVm) {
    let messages = workspace.notifications().messages();
    let text = if messages.is_empty() {
        "No notifications".to_string()
    } else {
        messages.join(" | ")
    };
    frame.render_widget(
        Paragraph::new(text).block(
            Block::default()
                .borders(Borders::ALL)
                .title("Notifications"),
        ),
        area,
    );
}
