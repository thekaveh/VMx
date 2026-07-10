# Rust Notes Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cross-platform Rust TUI showcase example that demonstrates a 100% VMx-owned MVVM application.

**Architecture:** Ratatui and crossterm provide rendering/input only. Models and view models live in separate modules, while the host shell translates terminal events into VM commands and draws snapshots from VM getters.

**Tech Stack:** Rust 1.82+, VMx Rust crate, Ratatui, crossterm, standard `cargo test` and `cargo run -- --smoke`.

## Global Constraints

- Branch: `codex/rust-showcase-example-71`.
- Keep domain state in VMx view models; Ratatui views must not own search, selection, form, paging, notifications, or editor mode.
- Follow Rust flavor idioms from ADR-0006: snake_case methods and Rust-native result handling.
- Use existing VMx abstractions instead of recreating equivalent state machines in the example.
- Add tests before production/example code.

______________________________________________________________________

## 1. File Structure

- Create `examples/rust/tui/notes-showcase/Cargo.toml`: standalone example crate.
- Create `examples/rust/tui/notes-showcase/src/models.rs`: data records, seed data, in-memory repository.
- Create `examples/rust/tui/notes-showcase/src/viewmodels.rs`: VMx-backed showcase state and commands.
- Create `examples/rust/tui/notes-showcase/src/views.rs`: pure Ratatui render functions.
- Create `examples/rust/tui/notes-showcase/src/app.rs`: terminal loop, key mapping, smoke runner.
- Create `examples/rust/tui/notes-showcase/src/main.rs`: CLI entry point.
- Create `examples/rust/tui/notes-showcase/tests/viewmodels.rs`: VM-layer behavior tests.
- Modify `.github/workflows/rust.yml`: test and smoke-run the new example.
- Modify `examples/rust/README.md`, `docs/site/examples/*.md`, `docs/wiki/Examples/*.md`, and Rust flavor docs.

## 2. TDD Tasks

### Task 1: VM Layer Tests

- [ ] Write failing tests for notebook selection, note filtering, paging, form validation, save/revert, editor mode, global search, and notifications.
- [ ] Run `cargo test --manifest-path examples/rust/tui/notes-showcase/Cargo.toml` and confirm the crate or APIs are missing.
- [ ] Implement models and view models with VMx primitives until tests pass.
- [ ] Run `cargo test --manifest-path examples/rust/tui/notes-showcase/Cargo.toml`.

### Task 2: TUI Host and Smoke Mode

- [ ] Write/extend tests for non-interactive smoke behavior.
- [ ] Implement `--smoke` as scripted VM commands plus a text summary.
- [ ] Implement Ratatui render functions and key dispatch as a thin adapter.
- [ ] Run `cargo run --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --smoke`.

### Task 3: CI and Docs

- [ ] Add rust workflow commands for showcase tests and smoke mode.
- [ ] Update in-repo examples documentation.
- [ ] Update MkDocs site pages and native wiki pages.
- [ ] Run docs/example checks impacted by the change.

### Task 4: Verification

- [ ] Run `cargo fmt --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --check`.
- [ ] Run `cargo clippy --manifest-path examples/rust/tui/notes-showcase/Cargo.toml --all-targets -- -D warnings`.
- [ ] Run `cargo test --manifest-path examples/rust/tui/notes-showcase/Cargo.toml`.
- [ ] Run `cargo test --manifest-path langs/rust/Cargo.toml`.
- [ ] Run `python3 tools/check-showcase-parity.py`.
- [ ] Confirm `git status --short` contains only intended files.
