#!/usr/bin/env python3
"""Generate repository documentation diagrams.

The diagrams are intentionally plain SVG plus standalone HTML wrappers so they
render on GitHub, in browsers, and through `rsvg-convert` for PNG exports.
"""

# ruff: noqa: E501

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_VERSION = (ROOT / "spec" / "VERSION").read_text(encoding="utf-8").strip()
ADR_COUNT = len(list((ROOT / "spec" / "ADRs").glob("[0-9][0-9][0-9][0-9]-*.md")))
CONFORMANCE_IDS = re.findall(
    r"^### ([A-Z]+-\d{3})\b",
    (ROOT / "spec" / "12-conformance.md").read_text(encoding="utf-8"),
    re.MULTILINE,
)
THEME_COUNT = sum(item.startswith("THEME-") for item in CONFORMANCE_IDS)
LIBRARY_COUNT = len(CONFORMANCE_IDS) - THEME_COUNT


COLORS = {
    "frontend": ("rgba(8, 51, 68, 0.42)", "#22d3ee"),
    "backend": ("rgba(6, 78, 59, 0.42)", "#34d399"),
    "database": ("rgba(76, 29, 149, 0.42)", "#a78bfa"),
    "cloud": ("rgba(120, 53, 15, 0.34)", "#fbbf24"),
    "security": ("rgba(136, 19, 55, 0.42)", "#fb7185"),
    "bus": ("rgba(251, 146, 60, 0.34)", "#fb923c"),
    "generic": ("rgba(30, 41, 59, 0.55)", "#94a3b8"),
}


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int
    title: str
    lines: tuple[str, ...]
    kind: str = "generic"
    dash: bool = False


def text(
    x: int,
    y: int,
    value: str,
    size: int = 18,
    color: str = "#e2e8f0",
    weight: str = "400",
    anchor: str = "middle",
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>'
    )


def box(b: Box) -> str:
    fill, stroke = COLORS[b.kind]
    dash = ' stroke-dasharray="8 6"' if b.dash else ""
    parts = [
        f'<rect x="{b.x}" y="{b.y}" width="{b.w}" height="{b.h}" rx="12" fill="#0f172a"/>',
        f'<rect x="{b.x}" y="{b.y}" width="{b.w}" height="{b.h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>',
        text(b.x + b.w // 2, b.y + 32, b.title, 18, "white", "700"),
    ]
    for i, line in enumerate(b.lines):
        parts.append(text(b.x + b.w // 2, b.y + 58 + i * 24, line, 14, "#cbd5e1"))
    return "\n".join(parts)


def arrow(
    x1: int, y1: int, x2: int, y2: int, label: str = "", color: str = "#64748b", dash: bool = False
) -> str:
    dash_attr = ' stroke-dasharray="8 6"' if dash else ""
    mid_x = (x1 + x2) // 2
    mid_y = (y1 + y2) // 2 - 10
    label_svg = text(mid_x, mid_y, label, 12, color) if label else ""
    return (
        f'<path d="M{x1},{y1} C{mid_x},{y1} {mid_x},{y2} {x2},{y2}" '
        f'fill="none" stroke="{color}" stroke-width="2.2" marker-end="url(#arrowhead)"{dash_attr}/>'
        f"\n{label_svg}"
    )


def svg_doc(title: str, subtitle: str, width: int, height: int, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;">
  <defs>
    <style>text {{ font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}</style>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" stroke-width="0.7"/>
    </pattern>
    <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#64748b"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#020617"/>
  <rect width="100%" height="100%" fill="url(#grid)"/>
  {text(40, 54, title, 28, "white", "700", "start")}
  {text(40, 84, subtitle, 15, "#94a3b8", "400", "start")}
  {body}
</svg>
'''


def html_doc(title: str, subtitle: str, svg_name: str, cards: list[tuple[str, list[str]]]) -> str:
    card_html = "\n".join(
        f"""      <section class="card">
        <h2>{escape(card_title)}</h2>
        <ul>{"".join(f"<li>{escape(item)}</li>" for item in items)}</ul>
      </section>"""
        for card_title, items in cards
    )
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(title)}</title>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; padding: 32px; background: #020617; color: white; font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace; }}
    main {{ max-width: 1500px; margin: 0 auto; }}
    header {{ margin-bottom: 24px; }}
    .header-row {{ display: flex; align-items: center; gap: 14px; }}
    .pulse-dot {{ width: 12px; height: 12px; border-radius: 50%; background: #22d3ee; animation: pulse 2s infinite; }}
    @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.45; }} }}
    h1 {{ margin: 0; font-size: 26px; line-height: 1.25; }}
    .subtitle {{ margin: 8px 0 0 26px; color: #94a3b8; font-size: 14px; }}
    .diagram {{ overflow-x: auto; padding: 18px; border: 1px solid #1e293b; border-radius: 14px; background: rgba(15, 23, 42, 0.58); }}
    object {{ display: block; width: 100%; min-width: 1180px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-top: 24px; }}
    .card {{ padding: 18px; border: 1px solid #1e293b; border-radius: 12px; background: rgba(15, 23, 42, 0.58); }}
    .card h2 {{ margin: 0 0 10px; font-size: 15px; }}
    .card ul {{ margin: 0; padding-left: 18px; color: #cbd5e1; font-size: 12px; line-height: 1.55; }}
    footer {{ margin-top: 24px; text-align: center; color: #64748b; font-size: 12px; }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="header-row"><div class="pulse-dot"></div><h1>{escape(title)}</h1></div>
      <p class="subtitle">{escape(subtitle)}</p>
    </header>
    <div class="diagram"><object data="{escape(svg_name)}" type="image/svg+xml" aria-label="{escape(title)}"></object></div>
    <div class="cards">
{card_html}
    </div>
    <footer>Generated for VMx spec {SPEC_VERSION} documentation.</footer>
  </main>
</body>
</html>
'''


def write_pair(
    path: Path,
    title: str,
    subtitle: str,
    width: int,
    height: int,
    body: str,
    cards: list[tuple[str, list[str]]],
) -> None:
    svg_path = ROOT / path.with_suffix(".svg")
    html_path = ROOT / path.with_suffix(".html")
    svg_path.write_text(svg_doc(title, subtitle, width, height, body), encoding="utf-8")
    html_path.write_text(html_doc(title, subtitle, svg_path.name, cards), encoding="utf-8")


def architecture() -> None:
    boxes = [
        Box(
            60,
            130,
            300,
            160,
            "Spec Source",
            (
                "23 chapters",
                f"{ADR_COUNT} ADRs",
                f"{len(CONFORMANCE_IDS)} conformance IDs",
                "4 JSON fixtures",
            ),
            "cloud",
        ),
        Box(
            450,
            130,
            300,
            160,
            "Core VMx Runtime",
            (
                "Lifecycle state machine",
                "MessageHub + Dispatcher",
                "Commands + capabilities",
                "Builders + tree utilities",
            ),
            "backend",
        ),
        Box(
            840,
            130,
            300,
            160,
            "State + Data Helpers",
            (
                "DerivedProperty",
                "SearchableState / ExpandableState",
                "Observable collections",
                "Paged + token-paged views",
            ),
            "database",
        ),
        Box(
            1230,
            130,
            300,
            160,
            "Services",
            ("IDialogService", "ILocalizer", "Notification hub", "Null-object defaults"),
            "security",
        ),
        Box(
            40,
            410,
            220,
            145,
            "C# Flavor",
            (
                "System.Reactive",
                "Avalonia / WPF / MAUI",
                f"Full {LIBRARY_COUNT}+{THEME_COUNT} parity",
            ),
            "frontend",
        ),
        Box(
            290,
            410,
            220,
            145,
            "Python Flavor",
            ("reactivex", "Textual / Tk / NiceGUI", f"Full {LIBRARY_COUNT}+{THEME_COUNT} parity"),
            "frontend",
        ),
        Box(
            540,
            410,
            220,
            145,
            "TypeScript Flavor",
            ("rxjs", "React / DOM adapters", f"Full {LIBRARY_COUNT}+{THEME_COUNT} parity"),
            "frontend",
        ),
        Box(
            790,
            410,
            220,
            145,
            "Swift Flavor",
            ("Combine", "SwiftUI flagship", f"Full {LIBRARY_COUNT}+{THEME_COUNT} parity"),
            "frontend",
        ),
        Box(
            1040,
            410,
            220,
            145,
            "Rust Flavor",
            ("rxrust facade", "UI-neutral core", f"Full {LIBRARY_COUNT}+{THEME_COUNT} parity"),
            "frontend",
        ),
        Box(
            1300,
            410,
            240,
            145,
            "CI Gates",
            ("Spec discipline", "Coverage", "Examples contracts"),
            "bus",
        ),
        Box(
            260,
            700,
            1080,
            170,
            "Example Portfolio",
            (
                "Notes Workspace flagships: Avalonia, Textual, React, SwiftUI",
                "19 VMx features: hierarchy, forms, derived state, dialogs, notifications, token paging, discriminator modes",
                "Smaller demos exercise console, WPF, Tk, inspector, and integration recipes",
            ),
            "generic",
        ),
    ]
    body = "\n".join(
        [
            arrow(360, 210, 450, 210, "norms"),
            arrow(750, 210, 840, 210, "uses"),
            arrow(1140, 210, 1230, 210, "injects"),
            arrow(600, 290, 150, 410, "idiomatic APIs"),
            arrow(600, 290, 400, 410),
            arrow(600, 290, 650, 410),
            arrow(600, 290, 900, 410),
            arrow(600, 290, 1150, 410),
            arrow(1420, 410, 1420, 290, "enforces", "#fb923c", True),
            arrow(840, 555, 800, 700, "showcases"),
        ]
        + [box(b) for b in boxes]
    )
    cards = [
        (
            "Spec discipline",
            [
                "spec/ is the source of truth.",
                f"Every full-parity flavor tracks {LIBRARY_COUNT} library IDs.",
                "THEME-001..005 live in the flagship examples.",
            ],
        ),
        (
            "Runtime shape",
            [
                "Core primitives are language-neutral.",
                "API casing follows ADR-0006.",
                "Reactive primitive is native per flavor.",
            ],
        ),
        (
            "Examples",
            [
                "Notes Workspace now covers 19 VMx features.",
                "Global search uses TokenPagedComposition.",
                "Editor mode uses DiscriminatorVM.",
            ],
        ),
    ]
    write_pair(
        Path("assets/architecture"),
        "VMx Architecture",
        f"spec {SPEC_VERSION} · five full-parity flavors · examples as contract probes",
        1600,
        940,
        body,
        cards,
    )


def class_diagram() -> None:
    boxes = [
        Box(
            60,
            130,
            300,
            145,
            "Lifecycle Base",
            (
                "ComponentVMBase",
                "ConstructionStatus",
                "construct / destruct / dispose",
                "fixture-backed transitions",
            ),
            "backend",
        ),
        Box(
            400,
            130,
            300,
            145,
            "Messages",
            (
                "PropertyChangedMessage",
                "ConstructionStatusChanged",
                "TreeStructureChanged",
                "PropertyValueChanged",
            ),
            "bus",
        ),
        Box(
            740,
            130,
            300,
            145,
            "Services",
            ("MessageHub", "Dispatcher", "ILocalizer", "IDialogService", "Null* variants"),
            "security",
        ),
        Box(
            1080,
            130,
            300,
            145,
            "Builders",
            (
                "immutable fluent setters",
                "required-field validation",
                "options-value factories",
                "per-flavor idioms",
            ),
            "cloud",
        ),
        Box(
            60,
            350,
            260,
            170,
            "Leaf VMs",
            ("ComponentVM", "ComponentVM<M>", "ReadonlyComponentVM<M>", "ForwardingComponentVM"),
            "frontend",
        ),
        Box(
            360,
            350,
            260,
            170,
            "Containers",
            ("CompositeVM", "GroupVM", "AggregateVM1..6", "HierarchicalVM"),
            "frontend",
        ),
        Box(
            660,
            350,
            260,
            170,
            "Specialized VMs",
            ("FormVM", "DiscriminatorVM", "NotificationVM", "ConfirmationVM"),
            "frontend",
        ),
        Box(
            960,
            350,
            260,
            170,
            "Collections",
            ("ObservableList", "ObservableDictionary", "Serviced collection", "multi-key indexes"),
            "database",
        ),
        Box(
            1260,
            350,
            260,
            170,
            "Paged Views",
            (
                "PagedComposition",
                "TokenPagedComposition",
                "filtered composite view",
                "scored composite view",
            ),
            "database",
        ),
        Box(
            160,
            610,
            320,
            150,
            "Commands",
            (
                "RelayCommand / AsyncRelayCommand",
                "DecoratorCommand",
                "ConfirmationDecoratorCommand",
                "ModeledCrudCommands",
            ),
            "bus",
        ),
        Box(
            550,
            610,
            320,
            150,
            "Capabilities",
            (
                "22 micro-interfaces",
                "select / expand / close",
                "filter / page / count",
                "CRUD and dialog contracts",
            ),
            "security",
        ),
        Box(
            940,
            610,
            320,
            150,
            "State Helpers",
            ("DerivedProperty", "SearchableState", "ExpandableState", "Discriminator active key"),
            "database",
        ),
        Box(
            1330,
            610,
            210,
            150,
            "Tree Utils",
            ("walk", "walk_expanded", "find", "materialized paths"),
            "generic",
        ),
    ]
    body = "\n".join(
        [
            arrow(210, 275, 190, 350),
            arrow(210, 275, 490, 350),
            arrow(210, 275, 790, 350),
            arrow(550, 275, 550, 350, "hub events"),
            arrow(890, 275, 1090, 350, "service owns"),
            arrow(1230, 275, 790, 350, "builds", "#fbbf24"),
            arrow(520, 520, 320, 610, "commands"),
            arrow(790, 520, 710, 610, "capabilities"),
            arrow(1090, 520, 1100, 610, "derived state"),
        ]
        + [box(b) for b in boxes]
    )
    cards = [
        (
            "Current additions",
            [
                "DiscriminatorVM is part of the specialized VM family.",
                "TokenPagedComposition covers cursor paging.",
                "Filtered/scored composite views are catalogued with collections.",
            ],
        ),
        (
            "Parity model",
            [
                "Every flavor exposes the same conceptual shape.",
                "Names are idiomatic per language.",
                "Swift is now full-catalog parity.",
            ],
        ),
        (
            "Usage",
            [
                "Apps combine small VMx primitives.",
                "Builders validate construction.",
                "Services are injected and replaceable.",
            ],
        ),
    ]
    write_pair(
        Path("assets/class-diagram"),
        "VMx Library Class Map",
        f"cluster-level class families for spec {SPEC_VERSION}",
        1600,
        860,
        body,
        cards,
    )


def showcase_hierarchy() -> None:
    boxes = [
        Box(
            80,
            125,
            1440,
            105,
            "WorkspaceVM",
            (
                "AggregateVM6 root + ThemeVM and GlobalSearchVM siblings",
                "Wires notebook current -> notes bind, note current -> form bind, saved note -> row refresh",
            ),
            "frontend",
        ),
        Box(
            80,
            310,
            320,
            295,
            "NotebooksRootVM",
            (
                "HierarchicalVM<NotebookModel, NotebookVM>",
                "recursive notebooks",
                "current notebook selection",
                "expand/collapse state",
            ),
            "frontend",
        ),
        Box(
            460,
            310,
            320,
            295,
            "NotesViewVM",
            (
                "CompositeVM<NoteVM>",
                "PagedComposition finite page state",
                "SearchableState title search",
                "IFilterable starred filter",
            ),
            "frontend",
        ),
        Box(
            840,
            310,
            360,
            295,
            "NoteFormVM",
            (
                "strict FormVM<NoteModel>",
                "validators expose title errors",
                "DiscriminatorVM edit/preview",
                "SearchableState tag suggestions",
            ),
            "frontend",
        ),
        Box(
            1260,
            310,
            260,
            295,
            "GlobalSearchVM",
            (
                "TokenPagedComposition<NoteVM,string>",
                "cursor-based search all notes",
                "refresh + load-more commands",
                "auto-constructs result VMs",
            ),
            "database",
        ),
        Box(
            80,
            690,
            360,
            130,
            "CapabilityActionsVM",
            (
                "DerivedProperty focused VM",
                "capability-aware commands",
                "confirmation-decorated delete",
            ),
            "security",
        ),
        Box(
            500,
            690,
            320,
            130,
            "StatusBarVM",
            ("DerivedProperty text slots", "notebook + count + dirty state", "view-bound only"),
            "database",
        ),
        Box(
            880,
            690,
            300,
            130,
            "NotificationsVM",
            (
                "GroupVM notification children",
                "INotificationHub subscription",
                "NotificationVM + ConfirmationVM",
            ),
            "security",
        ),
        Box(
            1240,
            690,
            280,
            130,
            "Repository",
            ("in-memory source of truth", "CRUD capability surface", "token-paged search method"),
            "cloud",
        ),
    ]
    body = "\n".join(
        [
            arrow(240, 230, 240, 310, "Component1"),
            arrow(620, 230, 620, 310, "Component2"),
            arrow(1020, 230, 1020, 310, "Component3"),
            arrow(1390, 230, 1390, 310, "sibling"),
            arrow(400, 455, 460, 455, "current"),
            arrow(780, 455, 840, 455),
            arrow(1020, 605, 1020, 690, "saved", "#fb7185", True),
            arrow(1390, 605, 1390, 690, "queries"),
            arrow(1180, 755, 880, 755, "post", "#fb7185", True),
            arrow(620, 605, 660, 690, "derived"),
            arrow(240, 605, 260, 690, "focus"),
        ]
        + [box(b) for b in boxes]
    )
    cards = [
        (
            "Shape",
            [
                "WorkspaceVM composes the six main panes through AggregateVM6.",
                "Theme and global search are siblings because they are cross-cutting.",
                "Views bind to VM surfaces only.",
            ],
        ),
        (
            "New showcase features",
            [
                "Global search uses TokenPagedComposition.",
                "Editor mode uses DiscriminatorVM.",
                "Tag autocomplete uses SearchableState over repository tags.",
            ],
        ),
        (
            "Determinism",
            [
                "Initial notes and tag suggestions are awaited during workspace construction.",
                "Form binding itself stays synchronous.",
                "Repository reads are explicit async steps.",
            ],
        ),
    ]
    write_pair(
        Path("examples/assets/notes-showcase-vm-hierarchy"),
        "Notes Showcase VM Hierarchy",
        "19-feature flagship hierarchy across C#, Python, TypeScript, and Swift",
        1600,
        900,
        body,
        cards,
    )


def showcase_components() -> None:
    boxes = [
        Box(
            80,
            130,
            310,
            165,
            "Root Composition",
            ("WorkspaceVM", "AggregateVM6", "ThemeVM sibling", "GlobalSearchVM sibling"),
            "frontend",
        ),
        Box(
            470,
            130,
            310,
            165,
            "Navigation Layer",
            ("NotebooksRootVM", "HierarchicalVM", "NotebookVM recursion", "ExpandableState"),
            "frontend",
        ),
        Box(
            860,
            130,
            310,
            165,
            "List Layer",
            (
                "NotesViewVM",
                "CompositeVM<NoteVM>",
                "PagedComposition",
                "SearchableState + IFilterable",
            ),
            "frontend",
        ),
        Box(
            1250,
            130,
            310,
            165,
            "Editor Layer",
            ("NoteFormVM", "FormVM validation", "DiscriminatorVM mode", "tag SearchableState"),
            "frontend",
        ),
        Box(
            160,
            430,
            330,
            165,
            "Command Layer",
            (
                "RelayCommand",
                "AsyncRelayCommand",
                "ConfirmationDecoratorCommand",
                "reactive canExecute triggers",
            ),
            "bus",
        ),
        Box(
            580,
            430,
            330,
            165,
            "Derived State",
            ("DerivedProperty", "status bar text", "dirty / valid flags", "focused VM actions"),
            "database",
        ),
        Box(
            1000,
            430,
            330,
            165,
            "Services",
            ("MessageHub", "Dispatcher", "IDialogService", "INotificationHub"),
            "security",
        ),
        Box(
            250,
            710,
            330,
            145,
            "View Adapters",
            ("Avalonia bindings", "Textual bridge", "React hooks", "SwiftUI ObservableObject"),
            "generic",
        ),
        Box(
            710,
            710,
            330,
            145,
            "Models + Repository",
            ("NotebookModel", "NoteModel", "CRUD interfaces", "token search pages"),
            "cloud",
        ),
        Box(
            1170,
            710,
            330,
            145,
            "Example Contract",
            ("19 parity rows", "THEME-001..005", "layer purity checks", "cross-flavor tests"),
            "cloud",
        ),
    ]
    body = "\n".join(
        [
            arrow(390, 212, 470, 212, "owns"),
            arrow(780, 212, 860, 212, "selects"),
            arrow(1170, 212, 1250, 212, "binds"),
            arrow(1015, 295, 745, 430, "page/filter signals"),
            arrow(1405, 295, 745, 430, "valid/dirty"),
            arrow(1015, 295, 1165, 430, "messages"),
            arrow(325, 595, 415, 710, "button bridges"),
            arrow(745, 595, 415, 710, "observable bridges"),
            arrow(1165, 595, 875, 710, "async IO"),
            arrow(875, 855, 1335, 855, "verified by"),
        ]
        + [box(b) for b in boxes]
    )
    cards = [
        (
            "Purpose",
            [
                "Shows the VMx primitives selected by the examples.",
                "Complements the hierarchy diagram.",
                "Useful when deciding which component to use in new examples.",
            ],
        ),
        (
            "Best-fit usage",
            [
                "Finite page state remains PagedComposition.",
                "Global search uses TokenPagedComposition.",
                "Editor mode uses DiscriminatorVM instead of local booleans.",
            ],
        ),
        (
            "View layer",
            [
                "Views stay thin and framework-specific.",
                "Adapters bridge VMx observables to each UI toolkit.",
                "Business state remains in the VM layer.",
            ],
        ),
    ]
    write_pair(
        Path("examples/assets/notes-showcase-vmx-components"),
        "Notes Showcase VMx Component Map",
        "how the example VM layer is shaped from VMx primitives",
        1600,
        930,
        body,
        cards,
    )


def main() -> None:
    architecture()
    class_diagram()
    showcase_hierarchy()
    showcase_components()


if __name__ == "__main__":
    main()
