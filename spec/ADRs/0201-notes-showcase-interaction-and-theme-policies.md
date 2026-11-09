# ADR 0201 — Notes showcase interaction and theme policies

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (scenario contracts only: the notes showcase
  proposal §5.2 and the theme proposal §4 and §7; no chapter changes)
- **Related:** [ADR-0036](0036-v2.4-platform-and-theming.md) §2.C (theme scenario
  contract), [ADR-0067](0067-swift-notes-showcase-flagship.md) (Swift
  flagship), [ADR-0009](0009-cross-flavor-divergence-catalogue.md) (Swift
  commands cannot throw), #1331.

## 1. Context

The notes showcase has four flagships (C#, Python, TypeScript and Swift) and
a reduced Rust TUI companion. Six user-visible policies differed between the
apps, or no document stated them (#1331):

1. **Selection after a refilter.** The four flagships keep `current` when a
   search hides the current note. The Rust TUI makes the first visible note
   current and loads it into the editor. The Rust TUI does the same on a page
   change. The Avalonia list does not highlight the current note again when
   a search hides it and a later search shows it again.
1. **Unsaved edits on a note switch.** Every app replaces the editor form
   with no dirty check. No document states that the switch discards the
   draft.
1. **Two Save actions.** The capability action bar reuses
   `NoteVM.SaveCommand`, which persists the stored model. With unsaved edits,
   the action-bar Save writes the old values. The editor Save writes the
   draft.
1. **Theme controls.** Only Swift has theme controls. Parity matrix row 16
   still marks the theme scenario `Yes` for all four flagships.
1. **Accent validation.** TypeScript rejects an accent that is not `#RGB` or
   `#RRGGBB`. Python ignores an empty or `None` accent. C# rejects only
   `null`. Swift accepts any string. The theme proposal made the rule
   flavor-discretionary.
1. **Follow-system with no provider.** No flagship passes a host theme
   provider. With no provider, Python adopts the dark preset. TypeScript reads
   `matchMedia` or adopts the dark preset. C# and Swift keep the current theme
   and set only `followsSystem`.

The owner delegated these decisions. The rule is to pick the simplest
common-sense option that is the same in every app.

## 2. Decision

Decided under the owner's 2026-11-07 delegation. Each policy applies to every
app that has the feature. The Rust TUI has no theme VM and no capability
action bar, so only policies 1 and 2 apply to it.

### 2.1. Selection after a refilter or a page change

A search, the starred filter or a page change never changes `current`. While
the current note is not on the visible page, the editor keeps that note and
its draft. When the note is visible again, the list marks it as selected
again.

- The C# `NotesViewVM` raises `Current` changed when the current note goes
  back into the visible slice, so the Avalonia `ListBox` selects it again.
  While the note is hidden, the list has no row for it. Thus the
  `ListBox` `SelectedItem` is `null`, and `Current` keeps the note.
- The Rust `WorkspaceVm` no longer changes the selection or reloads the
  editor on a search or a page change. The Rust TUI gains the `j` and `k`
  keys. They select the next or the previous note on the visible page. When
  the current note is not on that page, both keys select the first visible
  note.
- The Rust `d` key deletes the current note even while its row is hidden.
  The editor shows that note, and the delete prompt names it. A page
  change or a search still cancels a pending delete.

Rejected: move the selection to a visible note. That reloads the editor and
discards the draft each time the user types a search term.

### 2.2. Unsaved edits on a note switch

A selection of another note discards the unsaved draft with no prompt. The
editor then shows the stored values of the selected note. A return to the
first note also shows its stored values. Before the switch, the status bar's
dirty marker and the enabled Save and Revert show that the draft is unsaved.
No app changes. Each app adds a test for this policy.

Rejected: a prompt. It needs a selection veto in four UI toolkits and an
asynchronous dialog in the selection path. Rejected: an automatic save. It
adds a second write path, and it cannot save a draft that fails validation.

### 2.3. The action-bar Save

The action-bar Save on a note is the editor Save when the editor holds that
note. It persists the editor draft with the same validation and the same
"Saved" notification. It persists nothing when the draft is clean or not
valid. When the editor holds another note, the Save persists the stored model
of the focused note, as before.

Each flagship implements this rule in the save handler that `NotesViewVM`
gives each `NoteVM`. `WorkspaceVM` supplies that handler. The capability
action bar keeps `NoteVM.SaveCommand`.

Rejected: keep a Save that writes the stored model. It writes old values over
the visible draft and makes the user's edit look saved.

### 2.4. Theme controls

All four flagships ship one theme control strip. The strip has one button for
each preset, which runs `setThemeCommand` with the preset name. It has a
high-contrast toggle, which runs `toggleHighContrast`. It has a decrease and
an increase font-size button, which run `setFontScale` with the current
factor minus or plus 0.1. `ThemeVM` clamps the result. The Swift
`ThemeControlsView` already matches this strip.

No flagship ships an accent control or a follow-system control. The
flagships have no accent picker and no host theme provider, so these controls
would have no visible effect. The theme proposal §7 now states this scope.

### 2.5. Accent validation

`setAccentColor` accepts only `#RGB` or `#RRGGBB`, with hexadecimal digits in
either case. It stores an accepted value as given. Any other value, an empty
string and a null value included, is rejected like an unknown preset in
`THEME-002`:

- C#, Python and TypeScript raise their idiomatic argument error:
  `ArgumentException` (`ArgumentNullException` for `null`), `ValueError` and
  `Error`. C# `RelayCommand<string>` never runs its task for a `null`
  parameter, so a `null` accent sent through the command does nothing.
- Swift adds the public `applyAccentColor(_:) throws` member, which throws
  `ThemeError.invalidAccent`. `setAccentColor` discards the rejection, as
  `setThemeCommand` discards an unknown preset (ADR-0009).
- A rejected accent publishes no `ThemeChangedMessage` and leaves the model
  unchanged.
- `setAccentColor` has no argument predicate in any flavor. Python drops its
  predicate, so an empty or `None` accent reaches the task and is rejected.

### 2.6. Follow-system with no provider

With no host theme provider, `followSystemCommand` keeps the name, accent,
font scale and high-contrast values and sets `followsSystem` to true. It
publishes one `ThemeChangedMessage` when `followsSystem` was false, and none
when it was already true. A provider that reports a name that is not a preset
has the same result. With a provider that reports a preset, `THEME-005`
applies as before.

- Python drops `_default_host_theme_provider`, which returned the dark
  preset.
- TypeScript drops the `matchMedia` default resolver, so `ThemeVM` no longer
  reads `window`. A host that wants to follow the system passes a resolver.
- C# and Swift already have this behavior.

No conformance ID is added. The theme proposal and the parity document state
policies 2.4 to 2.6. Each flagship tests them with VM tests and, for 2.4, a
view test where the flagship has a headless view harness.

## 3. Consequences

- The notes showcase proposal §5.2 states policies 2.1 to 2.3. The theme
  proposal §4 states policies 2.5 and 2.6, and §7 states the control scope.
- `examples/notes-showcase-parity.md` gains an interaction-policy section,
  and row 16 names the theme controls that each flagship ships.
- C#: the Avalonia list highlight fix, the action-bar Save, the theme control
  strip and accent validation.
- Python: the action-bar Save, the theme control strip, accent validation and
  the no-provider follow-system result.
- TypeScript: the action-bar Save, the theme control strip and the
  no-provider follow-system result.
- Swift: the action-bar Save and accent validation. Its theme controls do not
  change.
- Rust: the selection rule and the `j` and `k` keys.
- The VMx library and the specification chapters do not change.
