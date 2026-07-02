#!/usr/bin/env python3
"""Generate the VMx documentation diagram set.

This task intentionally keeps the source local to docs/assets/diagrams so the
docs-site branch can evolve the diagram triplets without touching shared tooling.
"""

from __future__ import annotations

import json
import re
import tempfile
import subprocess
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DIAGRAM_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = DIAGRAM_DIR / "diagram-registry.json"
README_PATH = REPO_ROOT / "README.md"
SPEC_README_PATH = REPO_ROOT / "spec" / "README.md"
NOTES_PARITY_PATH = REPO_ROOT / "examples" / "notes-showcase-parity.md"
SPEC_VERSION_PATH = REPO_ROOT / "spec" / "VERSION"
CONFORMANCE_PATH = REPO_ROOT / "spec" / "12-conformance.md"
CAPABILITIES_PATH = REPO_ROOT / "spec" / "14-capabilities.md"
PNG_WIDTH = 3200
SVG_FONT_STACK = (
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
    "'Liberation Mono', 'Courier New', monospace"
)
HTML_FONT_STACK = (
    "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "
    "'Segoe UI', sans-serif"
)

COLORS = {
    "frontend": ("rgba(102, 170, 226, 0.16)", "#2f6fa3"),
    "backend": ("rgba(102, 183, 142, 0.16)", "#2e7d59"),
    "database": ("rgba(174, 161, 231, 0.16)", "#7862c9"),
    "cloud": ("rgba(236, 190, 104, 0.18)", "#b87a1f"),
    "security": ("rgba(220, 145, 179, 0.16)", "#b55479"),
    "bus": ("rgba(239, 174, 104, 0.18)", "#c77729"),
    "generic": ("rgba(170, 184, 201, 0.18)", "#6a7c91"),
}

RELATION_STYLES = {
    "extends": {"color": "#22d3ee", "dash": "", "width": 3.0},
    "implements": {"color": "#34d399", "dash": "10 6", "width": 3.0},
    "owns": {"color": "#fbbf24", "dash": "", "width": 3.0},
    "wraps": {"color": "#fb923c", "dash": "14 4", "width": 3.0},
    "decorates": {"color": "#fb7185", "dash": "8 6 2 6", "width": 3.0},
    "adapts": {"color": "#a78bfa", "dash": "3 6", "width": 3.0},
}

SVG_THEME = {
    "bg": "#f3f7fb",
    "grid": "#d7e1ec",
    "panel_mask": "#ffffff",
    "panel_fill": "rgba(255, 255, 255, 0.86)",
    "note_mask": "#f8fbff",
    "note_fill": "rgba(255, 255, 255, 0.94)",
    "boundary_fill": "rgba(255, 255, 255, 0.48)",
    "chip_fill": "#ffffff",
    "title": "#0f172a",
    "body": "#516273",
    "muted": "#64748b",
}


@dataclass(frozen=True)
class SourceFacts:
    spec_version: str
    spec_chapter_count: int
    adr_count: int
    fixture_count: int
    library_conformance_count: int
    theme_conformance_count: int
    total_conformance_count: int
    capability_count: int
    notes_feature_count: int
    notes_flavor_labels: tuple[str, ...]
    registry_ids: tuple[str, ...]
    registry_titles: tuple[tuple[str, str], ...]

    def title_for(self, diagram_id: str) -> str:
        for key, value in self.registry_titles:
            if key == diagram_id:
                return value
        raise KeyError(f"unknown diagram id: {diagram_id}")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require_match(text: str, pattern: str, description: str) -> re.Match[str]:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise ValueError(f"unable to find {description}")
    return match


def load_source_facts() -> SourceFacts:
    repo_readme = read_text(README_PATH)
    spec_readme = read_text(SPEC_README_PATH)
    notes_parity = read_text(NOTES_PARITY_PATH)
    conformance = read_text(CONFORMANCE_PATH)
    capabilities = read_text(CAPABILITIES_PATH)
    registry = json.loads(read_text(REGISTRY_PATH))
    if not isinstance(registry, list):
        raise ValueError("diagram-registry.json must contain a JSON array")

    spec_version = read_text(SPEC_VERSION_PATH).strip()
    spec_chapter_count = len(list((REPO_ROOT / "spec").glob("[0-9][0-9]-*.md")))
    adr_count = len(list((REPO_ROOT / "spec" / "ADRs").glob("[0-9][0-9][0-9][0-9]-*.md")))
    fixture_count = len(list((REPO_ROOT / "spec" / "fixtures").glob("*.json")))
    conformance_ids = re.findall(r"^### ([A-Z]+-\d{3})\b", conformance, re.MULTILINE)
    theme_conformance_count = sum(1 for item in conformance_ids if item.startswith("THEME-"))
    total_conformance_count = len(conformance_ids)
    library_conformance_count = total_conformance_count - theme_conformance_count
    capability_count = int(
        require_match(
            capabilities,
            r"lists the (\d+) capability interfaces",
            "capability count in spec/14-capabilities.md",
        ).group(1)
    )
    notes_feature_count = len(
        re.findall(r"^\| \d+\s+\|", notes_parity, re.MULTILINE)
    )
    notes_flavor_labels = tuple(
        re.findall(r"^- \*\*(.+?)\*\* \u2014 ", notes_parity, re.MULTILINE)
    )

    readme_conformance = require_match(
        repo_readme,
        r"(\d+)\s+library conformance IDs\s+\+\s+(\d+)\s+THEME scenario IDs\s+=\s+\*\*(\d+)\s+total\*\*",
        "README conformance summary",
    )
    if (
        int(readme_conformance.group(1)) != library_conformance_count
        or int(readme_conformance.group(2)) != theme_conformance_count
        or int(readme_conformance.group(3)) != total_conformance_count
    ):
        raise ValueError("README.md conformance summary drifted from spec/12-conformance.md")

    spec_readme_total = int(
        require_match(
            spec_readme,
            r"12-conformance\.md.*\((\d+) IDs\)",
            "spec/README.md conformance total",
        ).group(1)
    )
    if spec_readme_total != total_conformance_count:
        raise ValueError("spec/README.md conformance total drifted from spec/12-conformance.md")

    readme_notes_feature_count = int(
        require_match(
            repo_readme,
            r"\*\*(\d+)\s+distinct VMx features\*\*",
            "README.md Notes Workspace feature count",
        ).group(1)
    )
    if readme_notes_feature_count != notes_feature_count:
        raise ValueError("README.md Notes Workspace feature count drifted from examples parity doc")

    if len(notes_flavor_labels) != 4:
        raise ValueError("expected four Notes Workspace flavor labels")

    registry_ids: list[str] = []
    registry_titles: list[tuple[str, str]] = []
    for item in registry:
        if not isinstance(item, dict):
            raise ValueError("diagram-registry.json rows must be objects")
        diagram_id = item.get("id")
        title = item.get("title")
        if not isinstance(diagram_id, str) or not isinstance(title, str):
            raise ValueError("diagram-registry.json rows need string id/title values")
        registry_ids.append(diagram_id)
        registry_titles.append((diagram_id, title))

    return SourceFacts(
        spec_version=spec_version,
        spec_chapter_count=spec_chapter_count,
        adr_count=adr_count,
        fixture_count=fixture_count,
        library_conformance_count=library_conformance_count,
        theme_conformance_count=theme_conformance_count,
        total_conformance_count=total_conformance_count,
        capability_count=capability_count,
        notes_feature_count=notes_feature_count,
        notes_flavor_labels=notes_flavor_labels,
        registry_ids=tuple(registry_ids),
        registry_titles=tuple(registry_titles),
    )


SOURCE_FACTS = load_source_facts()
SPEC_VERSION = SOURCE_FACTS.spec_version


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int
    title: str
    lines: tuple[str, ...]
    kind: str = "generic"
    title_size: int = 18
    line_size: int = 13
    dashed: bool = False
    align: str = "middle"


@dataclass(frozen=True)
class Boundary:
    x: int
    y: int
    w: int
    h: int
    label: str
    color: str = "#fbbf24"
    dash: str = "8 4"


@dataclass(frozen=True)
class Note:
    x: int
    y: int
    w: int
    h: int
    title: str
    lines: tuple[str, ...]
    color: str = "#94a3b8"


@dataclass(frozen=True)
class Polyline:
    points: tuple[tuple[int, int], ...]
    color: str = "#64748b"
    width: float = 2.2
    dash: str | None = None
    label: str | None = None
    label_xy: tuple[int, int] | None = None
    marker: bool = True


@dataclass(frozen=True)
class Relationship:
    kind: str
    points: tuple[tuple[int, int], ...]
    label_xy: tuple[int, int]


@dataclass(frozen=True)
class Diagram:
    diagram_id: str
    title: str
    subtitle: str
    width: int
    height: int
    boxes: tuple[Box, ...] = field(default_factory=tuple)
    boundaries: tuple[Boundary, ...] = field(default_factory=tuple)
    notes: tuple[Note, ...] = field(default_factory=tuple)
    lines: tuple[Polyline, ...] = field(default_factory=tuple)
    relationships: tuple[Relationship, ...] = field(default_factory=tuple)
    cards: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)
    footer: str = ""


def svg_text(
    x: int,
    y: int,
    value: str,
    *,
    size: int = 16,
    color: str = "#e2e8f0",
    weight: str = "400",
    anchor: str = "middle",
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>'
    )


def multiline_text(
    x: int,
    y: int,
    lines: tuple[str, ...],
    *,
    size: int = 13,
    color: str = "#cbd5e1",
    anchor: str = "middle",
    line_height: int = 20,
) -> str:
    return "\n".join(
        svg_text(x, y + index * line_height, line, size=size, color=color, anchor=anchor)
        for index, line in enumerate(lines)
    )


def draw_box(box: Box) -> str:
    fill, stroke = COLORS[box.kind]
    dash = ' stroke-dasharray="8 6"' if box.dashed else ""
    title_anchor = box.align
    text_x = box.x + box.w // 2 if box.align == "middle" else box.x + 18
    body_x = box.x + box.w // 2 if box.align == "middle" else box.x + 18
    body_anchor = "middle" if box.align == "middle" else "start"
    return "\n".join(
        [
            f'<rect x="{box.x}" y="{box.y}" width="{box.w}" height="{box.h}" rx="8" fill="{SVG_THEME["panel_mask"]}"/>',
            f'<rect x="{box.x}" y="{box.y}" width="{box.w}" height="{box.h}" rx="8" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.8"{dash}/>',
            svg_text(
                text_x,
                box.y + 28,
                box.title,
                size=box.title_size,
                color=SVG_THEME["title"],
                weight="700",
                anchor=title_anchor,
            ),
            multiline_text(
                body_x,
                box.y + 54,
                box.lines,
                size=box.line_size,
                color=SVG_THEME["body"],
                anchor=body_anchor,
                line_height=max(18, box.line_size + 6),
            ),
        ]
    )


def draw_boundary(boundary: Boundary) -> str:
    return "\n".join(
        [
            f'<rect x="{boundary.x}" y="{boundary.y}" width="{boundary.w}" height="{boundary.h}" '
            f'rx="12" fill="{SVG_THEME["boundary_fill"]}" stroke="{boundary.color}" stroke-width="1.2" '
            f'stroke-dasharray="{boundary.dash}"/>',
            svg_text(
                boundary.x + 14,
                boundary.y + 22,
                boundary.label,
                size=12,
                color=boundary.color,
                weight="700",
                anchor="start",
            ),
        ]
    )


def draw_note(note: Note) -> str:
    return "\n".join(
        [
            f'<rect x="{note.x}" y="{note.y}" width="{note.w}" height="{note.h}" rx="8" fill="{SVG_THEME["note_mask"]}"/>',
            f'<rect x="{note.x}" y="{note.y}" width="{note.w}" height="{note.h}" rx="8" '
            f'fill="{SVG_THEME["note_fill"]}" stroke="{note.color}" stroke-width="1.2"/>',
            svg_text(
                note.x + 16,
                note.y + 24,
                note.title,
                size=13,
                color=SVG_THEME["title"],
                weight="700",
                anchor="start",
            ),
            multiline_text(
                note.x + 16,
                note.y + 46,
                note.lines,
                size=12,
                color=SVG_THEME["body"],
                anchor="start",
                line_height=18,
            ),
        ]
    )


def draw_polyline(line: Polyline) -> str:
    points = " ".join(f"{x},{y}" for x, y in line.points)
    dash = f' stroke-dasharray="{line.dash}"' if line.dash else ""
    marker = ' marker-end="url(#arrowhead)"' if line.marker else ""
    parts = [
        f'<polyline points="{points}" fill="none" stroke="{line.color}" stroke-width="{line.width}"{dash}{marker}/>'
    ]
    if line.label and line.label_xy:
        parts.append(draw_label_chip(line.label_xy[0], line.label_xy[1], line.label, line.color))
    return "\n".join(parts)


def draw_label_chip(x: int, y: int, label: str, color: str) -> str:
    width = max(54, len(label) * 7 + 18)
    left = x - width // 2
    top = y - 12
    return "\n".join(
        [
            f'<rect x="{left}" y="{top}" width="{width}" height="20" rx="10" fill="{SVG_THEME["chip_fill"]}" stroke="{color}" stroke-width="1"/>',
            svg_text(x, y + 2, label, size=11, color=color, weight="700"),
        ]
    )


def draw_relationship(rel: Relationship) -> str:
    style = RELATION_STYLES[rel.kind]
    return draw_polyline(
        Polyline(
            points=rel.points,
            color=style["color"],
            width=style["width"],
            dash=style["dash"] or None,
            label=rel.kind,
            label_xy=rel.label_xy,
        )
    )


def relationship_legend(x: int, y: int) -> str:
    parts = [
        svg_text(
            x,
            y,
            "Relationship legend",
            size=13,
            color=SVG_THEME["title"],
            weight="700",
            anchor="start",
        )
    ]
    order = ("extends", "implements", "owns", "wraps", "decorates", "adapts")
    for index, kind in enumerate(order):
        style = RELATION_STYLES[kind]
        row_y = y + 22 + index * 24
        dash = f' stroke-dasharray="{style["dash"]}"' if style["dash"] else ""
        parts.append(
            f'<line x1="{x}" y1="{row_y}" x2="{x + 54}" y2="{row_y}" stroke="{style["color"]}" '
            f'stroke-width="{style["width"]}"{dash} marker-end="url(#arrowhead)"/>'
        )
        parts.append(
            svg_text(x + 72, row_y + 4, kind, size=12, color=SVG_THEME["body"], anchor="start")
        )
    return "\n".join(parts)


def svg_doc(diagram: Diagram) -> str:
    body_parts: list[str] = []
    body_parts.extend(draw_relationship(rel) for rel in diagram.relationships)
    body_parts.extend(draw_polyline(line) for line in diagram.lines)
    body_parts.extend(draw_boundary(boundary) for boundary in diagram.boundaries)
    body_parts.extend(draw_box(box) for box in diagram.boxes)
    body_parts.extend(draw_note(note) for note in diagram.notes)
    if diagram.diagram_id == "class-architecture":
        body_parts.append(relationship_legend(diagram.width - 300, diagram.height - 230))
    body = "\n".join(body_parts)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{diagram.width}" height="{diagram.height}" viewBox="0 0 {diagram.width} {diagram.height}" style="font-family: {SVG_FONT_STACK};">
  <defs>
    <style>
      text {{ font-family: {SVG_FONT_STACK}; }}
    </style>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="{SVG_THEME["grid"]}" stroke-width="0.8"/>
    </pattern>
    <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#64748b"/>
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="{SVG_THEME["bg"]}"/>
  <rect width="100%" height="100%" fill="url(#grid)"/>
  {svg_text(40, 54, diagram.title, size=28, color=SVG_THEME["title"], weight="700", anchor="start")}
  {svg_text(40, 82, diagram.subtitle, size=15, color=SVG_THEME["muted"], anchor="start")}
  {body}
</svg>
"""


def html_doc(diagram: Diagram, svg_name: str) -> str:
    cards = "\n".join(
        f"""      <section class="card">
        <div class="card-header">
          <div class="card-dot {dot_class(index)}"></div>
          <h2>{escape(title)}</h2>
        </div>
        <ul>{"".join(f"<li>{escape(item)}</li>" for item in items)}</ul>
      </section>"""
        for index, (title, items) in enumerate(diagram.cards)
    )
    footer = diagram.footer or f"Generated from repo-derived facts for VMx spec {SPEC_VERSION}."
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(diagram.title)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    :root {{
      color-scheme: light dark;
      --page-bg: #edf3fa;
      --page-accent: rgba(34, 211, 238, 0.1);
      --surface: rgba(255, 255, 255, 0.88);
      --surface-strong: #ffffff;
      --surface-border: #c9d4e2;
      --text-primary: #0f172a;
      --text-secondary: #475569;
      --text-tertiary: #64748b;
      --shadow: 0 18px 44px rgba(15, 23, 42, 0.12);
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --page-bg: #020617;
        --page-accent: rgba(56, 189, 248, 0.08);
        --surface: rgba(15, 23, 42, 0.82);
        --surface-strong: rgba(16, 27, 38, 0.94);
        --surface-border: #273542;
        --text-primary: #f8fafc;
        --text-secondary: #cbd5e1;
        --text-tertiary: #94a3b8;
        --shadow: 0 18px 44px rgba(2, 6, 23, 0.45);
      }}
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      padding: 32px;
      background: var(--page-bg);
      background-image:
        radial-gradient(circle at top left, var(--page-accent), transparent 28%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.34), transparent 18rem);
      color: var(--text-primary);
      font-family: {HTML_FONT_STACK};
    }}
    main {{ max-width: 1600px; margin: 0 auto; }}
    header {{ margin-bottom: 20px; }}
    .header-row {{ display: flex; align-items: center; gap: 14px; }}
    .pulse-dot {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: #22d3ee;
      animation: pulse 2s infinite;
    }}
    @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.45; }} }}
    h1 {{ margin: 0; font-size: 26px; line-height: 1.25; }}
    .subtitle {{ margin: 8px 0 0 26px; color: var(--text-secondary); font-size: 14px; }}
    .diagram {{
      overflow-x: auto;
      padding: 14px 14px 10px;
      border: 1px solid var(--surface-border);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }}
    object {{ display: block; width: 100%; min-width: 1180px; }}
    .diagram-caption {{
      margin: 12px 4px 0;
      color: var(--text-secondary);
      font-size: 12px;
      line-height: 1.45;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
      margin-top: 22px;
    }}
    .card {{
      border: 1px solid var(--surface-border);
      border-radius: 8px;
      background: var(--surface-strong);
      padding: 16px;
      box-shadow: var(--shadow);
    }}
    .card-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }}
    .card-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
    .card-dot.cyan {{ background: #22d3ee; }}
    .card-dot.emerald {{ background: #34d399; }}
    .card-dot.violet {{ background: #a78bfa; }}
    .card h2 {{ margin: 0; font-size: 14px; }}
    .card ul {{ margin: 0; padding-left: 18px; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }}
    footer {{ margin-top: 22px; text-align: center; color: var(--text-tertiary); font-size: 12px; }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="header-row"><div class="pulse-dot"></div><h1>{escape(diagram.title)}</h1></div>
      <p class="subtitle">{escape(diagram.subtitle)}</p>
    </header>
    <div class="diagram">
      <object data="{escape(svg_name)}" type="image/svg+xml" aria-label="{escape(diagram.title)}"></object>
      <p class="diagram-caption">Embedded SVG stays high-contrast for portability while the page chrome adapts to your color scheme.</p>
    </div>
    <div class="cards">
{cards}
    </div>
    <footer>{escape(footer)}</footer>
  </main>
</body>
</html>
"""


def dot_class(index: int) -> str:
    return ("cyan", "emerald", "violet")[index % 3]


def system_architecture() -> Diagram:
    facts = SOURCE_FACTS
    return Diagram(
        diagram_id="system-architecture",
        title="VMx System Architecture",
        subtitle=f"spec {facts.spec_version} source of truth -> parity flavors -> host examples",
        width=1700,
        height=1040,
        boundaries=(
            Boundary(60, 118, 420, 264, "Specification control plane"),
            Boundary(520, 118, 560, 324, "Core runtime surface", "#34d399"),
            Boundary(1120, 118, 520, 324, "Support contracts and helpers", "#a78bfa"),
            Boundary(120, 492, 1460, 266, "Flavor implementations", "#22d3ee"),
            Boundary(260, 788, 1180, 172, "Example and validation loop", "#fb923c"),
        ),
        boxes=(
            Box(90, 152, 170, 96, "spec/", (f"{facts.spec_chapter_count} chapters", f"{facts.adr_count} ADRs", f"VERSION {facts.spec_version}"), "cloud"),
            Box(280, 152, 170, 96, "fixtures", (f"{facts.fixture_count} shared JSON fixtures", "lifecycle / messages", "commands / derived"), "cloud"),
            Box(90, 270, 360, 100, "12-conformance", (f"{facts.library_conformance_count} library IDs", f"{facts.theme_conformance_count} THEME scenario IDs", f"{facts.total_conformance_count} total"), "bus"),
            Box(550, 152, 220, 110, "Lifecycle base", ("ComponentVMBase", "guarded transitions", "dispose cascade"), "backend"),
            Box(790, 152, 250, 110, "VM families", ("component", "composite / group / aggregate", "hierarchical + forwarding"), "frontend"),
            Box(550, 288, 220, 110, "Commands", ("RelayCommand", "decorators", "ModeledCrudCommands"), "bus"),
            Box(790, 288, 250, 110, "Capabilities", (f"{facts.capability_count} micro-interfaces", "selection / CRUD / paging", "opt-in behavior"), "security"),
            Box(1150, 152, 220, 110, "Services", ("MessageHub", "Dispatcher", "IDialogService", "ILocalizer"), "security"),
            Box(1390, 152, 220, 110, "Collections + state", ("ObservableList", "DerivedProperty", "SearchableState"), "database"),
            Box(1150, 288, 220, 110, "Paging primitives", ("PagedComposition", "TokenPagedComposition", "filtered ordering"), "database"),
            Box(1390, 288, 220, 110, "Notifications", ("INotificationHub", "NotificationVM", "ConfirmationVM"), "security"),
            Box(160, 536, 250, 136, "C#", ("PascalCase surface", "System.Reactive", "NuGet packages"), "frontend"),
            Box(440, 536, 250, 136, "Python", ("snake_case surface", "reactivex", "uv + pytest"), "frontend"),
            Box(720, 536, 250, 136, "TypeScript", ("camelCase surface", "rxjs", "dual ESM/CJS"), "frontend"),
            Box(1000, 536, 250, 136, "Swift", ("camelCase surface", "Combine", "SwiftPM resources"), "frontend"),
            Box(1280, 536, 270, 136, "Compatibility matrix", ("independent package versions", "manual spec mapping", "major bumps track spec majors"), "generic"),
            Box(
                300,
                820,
                300,
                108,
                "Flagship examples",
                (
                    "Notes Workspace across four hosts",
                    f"{facts.notes_feature_count} feature rows + THEME-001..005",
                ),
                "generic",
            ),
            Box(700, 820, 300, 108, "CI gates", ("spec-discipline", "coverage tool", "examples contract checks"), "bus"),
            Box(1100, 820, 300, 108, "Release posture", ("same conceptual shape", "idiomatic per language", "repo facts drive docs"), "cloud"),
        ),
        lines=(
            Polyline(((260, 200), (280, 200)), color="#fbbf24"),
            Polyline(((450, 200), (550, 200)), color="#fbbf24", label="norms", label_xy=(500, 186)),
            Polyline(((450, 312), (550, 312)), color="#fb923c", label="catalogues", label_xy=(500, 298)),
            Polyline(((770, 206), (790, 206)), color="#22d3ee"),
            Polyline(((1040, 206), (1150, 206)), color="#34d399", label="injects", label_xy=(1096, 192)),
            Polyline(((1040, 344), (1150, 344)), color="#a78bfa", label="coordinates", label_xy=(1094, 330)),
            Polyline(((1520, 262), (1520, 288)), color="#fb7185"),
            Polyline(((660, 398), (280, 536)), color="#22d3ee", label="idiomatic APIs", label_xy=(474, 448)),
            Polyline(((660, 398), (560, 536)), color="#22d3ee"),
            Polyline(((920, 398), (840, 536)), color="#22d3ee"),
            Polyline(((920, 398), (1120, 536)), color="#22d3ee"),
            Polyline(((1270, 398), (1420, 536)), color="#a78bfa", label="versioned separately", label_xy=(1380, 450)),
            Polyline(((410, 672), (450, 820)), color="#64748b", label="hosts", label_xy=(432, 744)),
            Polyline(((845, 672), (850, 820)), color="#fb923c", label="enforces", label_xy=(872, 742)),
            Polyline(((1400, 672), (1250, 820)), color="#34d399", label="documents", label_xy=(1320, 740)),
        ),
        cards=(
            (
                "Source of truth",
                (
                    "Behavior changes start in spec/ and flow through fixtures and conformance IDs.",
                    "The lifecycle table, message ordering, and command truth table are shared repo facts.",
                    "The docs diagrams mirror the same structure rather than invent a parallel model.",
                ),
            ),
            (
                "Parity shape",
                (
                    "C#, Python, TypeScript, and Swift share one conceptual runtime with idiomatic casing only.",
                    "Reactive primitives stay native per flavor: System.Reactive, reactivex, rxjs, and Combine.",
                    "Runtime helpers such as paging, derived properties, dialogs, and notifications remain consistent.",
                ),
            ),
            (
                "Examples and gates",
                (
                    f"The flagship Notes Workspace exercises {facts.notes_feature_count} framework features plus THEME scenarios.",
                    "Coverage, spec discipline, and example checks keep docs claims tied to repository state.",
                    "Compatibility and release surfaces are versioned per flavor but tracked against the spec.",
                ),
            ),
        ),
    )


def class_architecture() -> Diagram:
    return Diagram(
        diagram_id="class-architecture",
        title="Class Architecture Map",
        subtitle="lineage, wrappers, commands, and paging helpers with relationship endpoints grounded in spec/source",
        width=1800,
        height=1320,
        boundaries=(
            Boundary(60, 118, 1680, 204, "Core VM lineage", "#22d3ee"),
            Boundary(60, 352, 1680, 322, "Wrappers and specialized companions", "#34d399"),
            Boundary(60, 704, 1680, 352, "Commands, paging, and notification adapters", "#a78bfa"),
        ),
        boxes=(
            Box(90, 150, 240, 108, "ComponentVMBase", ("lifecycle state machine", "hub + dispatcher", "protected hooks"), "backend"),
            Box(390, 142, 220, 120, "ComponentVM<M>", ("modeled leaf VM", "extends ComponentVMBaseOfM<M>", "implements IComponentVM<M>"), "frontend"),
            Box(670, 142, 220, 120, "CompositeVM", ("children list", "Current slot", "select_component"), "frontend"),
            Box(950, 142, 220, 120, "GroupVM", ("peer children", "no Current", "batch updates"), "frontend"),
            Box(1230, 142, 220, 120, "AggregateVM1..6", ("fixed arity", "Component1..6 accessors", "heterogeneous slots"), "frontend"),
            Box(1510, 142, 220, 120, "HierarchicalVM", ("recursive nodes", "Parent / Depth / Path", "tree change messages"), "frontend"),
            Box(90, 402, 220, 96, "IComponentVM<M>", ("name / hint / model", "selection + lifecycle verbs"), "generic"),
            Box(360, 390, 260, 120, "ForwardingComponentVM", ("wraps IComponentVM<M>", "default delegation", "override selected members"), "frontend"),
            Box(690, 402, 220, 96, "ICompositeVM<VM>", ("IList surface + Current", "child selection helpers"), "generic"),
            Box(960, 390, 280, 120, "ForwardingCompositeVM", ("wraps ICompositeVM<VM>", "forwards Current + iteration", "subclass overrides stay surgical"), "frontend"),
            Box(1300, 390, 220, 120, "DiscriminatorVM", ("ActiveKey", "modal precedence stack", "single-active slot"), "frontend"),
            Box(90, 550, 250, 132, "FormVM", ("snapshot + IsDirty", "approve_async + errors", "validation-aware persist flow"), "frontend"),
            Box(390, 560, 210, 112, "Approve + Deny commands", ("ICommand pair", "approve is fire-and-forget", "deny reverts Model"), "bus"),
            Box(650, 550, 260, 132, "Persister + validation", ("persister / snapshotter", "validators + equality", "hub messages on deny"), "security"),
            Box(980, 560, 230, 112, "NotificationVM", ("lifespan / opacity", "DismissCommand", "auto-resolve at expiry"), "security"),
            Box(1270, 550, 250, 112, "ConfirmationVM", ("ApproveCommand", "RejectCommand", "no auto-resolve at expiry"), "security"),
            Box(90, 756, 210, 96, "ICommand", ("CanExecute / Execute", "CanExecuteChanged"), "generic"),
            Box(350, 744, 230, 120, "RelayCommand", ("implements ICommand", "predicate + task", "reactive triggers"), "bus"),
            Box(630, 744, 240, 120, "DecoratorCommand", ("single inner command", "pre/post actions", "extra gate"), "bus"),
            Box(920, 732, 270, 132, "ConfirmationDecoratorCommand", ("confirm delegate gate", "errors observable", "fire-and-forget + async entry"), "bus"),
            Box(1240, 732, 250, 132, "ModeledCrudCommands", ("CreateNew / UpdateCurrent / DeleteCurrent", "optional confirm delegates", "selection trigger re-evaluates"), "bus"),
            Box(90, 916, 210, 96, "IPageable", ("page size / page count", "current page navigation"), "generic"),
            Box(350, 904, 230, 120, "PagedComposition", ("implements IPageable", "wraps iterable source", "current page slice"), "database"),
            Box(630, 904, 260, 120, "TokenPagedComposition", ("forward-only fetch_next", "load_more + refresh", "items accumulator + token"), "database"),
            Box(960, 916, 220, 96, "INotificationHub", ("Post / Resolve", "Pending stream", "NullNotificationHub"), "security"),
            Box(1230, 904, 220, 120, "ConfirmHelper", ("make_confirm", "awaits Post/Resolve flow", "returns async bool delegate"), "security"),
            Box(1510, 916, 180, 96, "Confirm delegate", ("() -> Task<bool>", "Approve means proceed"), "generic"),
        ),
        relationships=(
            Relationship("extends", ((500, 202), (330, 202)), (414, 186)),
            Relationship("extends", ((780, 202), (330, 202)), (626, 186)),
            Relationship("extends", ((1060, 202), (330, 202)), (894, 186)),
            Relationship("extends", ((1340, 202), (330, 202)), (1170, 186)),
            Relationship("extends", ((1620, 202), (330, 202)), (1450, 186)),
            Relationship("implements", ((500, 262), (500, 330), (200, 330), (200, 402)), (330, 350)),
            Relationship("implements", ((780, 262), (780, 330), (800, 330), (800, 402)), (828, 350)),
            Relationship("wraps", ((360, 450), (310, 450)), (336, 434)),
            Relationship("wraps", ((960, 450), (910, 450)), (936, 434)),
            Relationship("owns", ((340, 616), (390, 616)), (364, 600)),
            Relationship("owns", ((340, 642), (650, 642)), (494, 626)),
            Relationship("extends", ((1270, 616), (1210, 616)), (1240, 600)),
            Relationship("implements", ((465, 744), (465, 700), (195, 700), (195, 852)), (310, 718)),
            Relationship("decorates", ((630, 804), (300, 804)), (464, 788)),
            Relationship("decorates", ((920, 804), (300, 804)), (628, 836)),
            Relationship("owns", ((1055, 864), (1055, 900), (1600, 900), (1600, 916)), (1340, 884)),
            Relationship("implements", ((465, 904), (465, 872), (195, 872), (195, 916)), (314, 892)),
            Relationship("adapts", ((1450, 964), (1510, 964)), (1480, 948)),
        ),
        notes=(
            Note(
                80,
                1110,
                1160,
                104,
                "Assertion",
                (
                    "PagedComposition and TokenPagedComposition are composition/paging primitives, not CompositeVM subclasses.",
                    "Use them beside CompositeVM or a filtered source; they do not alter the container hierarchy.",
                ),
                "#fb923c",
            ),
            Note(
                80,
                1234,
                1640,
                70,
                "Reading hint",
                (
                    "Helper boxes make interface and delegate endpoints explicit so wraps/decorates/adapts stay literal.",
                    "The map is cluster-level, but every visible arrow endpoint names a real surface from spec or shipped code.",
                ),
                "#94a3b8",
            ),
        ),
        cards=(
            (
                "Lineage",
                (
                    "The base-type story is narrow on purpose: the core VM families extend ComponentVMBase, while FormVM and paging helpers do not.",
                    "CompositeVM, GroupVM, AggregateVM, and HierarchicalVM stay separate container families instead of one mutable mega-type.",
                    "Forwarding decorators remain wrappers around canonical interfaces, matching chapter 09.",
                ),
            ),
            (
                "Composition helpers",
                (
                    "FormVM owns its command pair and persister/validation collaborators rather than inheriting from the component tree.",
                    "PagedComposition implements IPageable over a wrapped source; TokenPagedComposition owns an accumulator and next-token flow.",
                    "ConfirmationVM extends NotificationVM because the shipped notifications package and ADR-0031 say it does.",
                ),
            ),
            (
                "Command and service seams",
                (
                    "RelayCommand is the plain ICommand implementation; DecoratorCommand and ConfirmationDecoratorCommand layer behavior onto an inner ICommand.",
                    "ConfirmHelper adapts INotificationHub into the async bool delegate used by confirmation decorators.",
                    "ModeledCrudCommands packages a command set around selection-driven actions without changing the composite type itself.",
                ),
            ),
        ),
    )


def viewmodel_families() -> Diagram:
    facts = SOURCE_FACTS
    return Diagram(
        diagram_id="viewmodel-families",
        title="ViewModel Families Map",
        subtitle="one conceptual hierarchy, five idioms, and specialized companions",
        width=1700,
        height=980,
        boundaries=(
            Boundary(60, 122, 1580, 694, "VM family bands", "#22d3ee"),
        ),
        boxes=(
            Box(120, 170, 220, 106, "Lifecycle base", ("ComponentVMBase", "Constructed / Disposed", "message hub hooks"), "backend"),
            Box(120, 320, 220, 132, "Leaf family", ("ComponentVM", "ComponentVM<M>", "ReadonlyComponentVM<M>"), "frontend"),
            Box(390, 170, 240, 132, "Selectable containers", ("CompositeVM<VM>", "CompositeVM<M,VM>", "Current slot"), "frontend"),
            Box(390, 336, 240, 116, "Peer containers", ("GroupVM<VM>", "homogeneous peers", "no Current"), "frontend"),
            Box(680, 170, 240, 132, "Fixed-arity containers", ("AggregateVM1..6", "heterogeneous components", "typed ComponentN slots"), "frontend"),
            Box(680, 336, 240, 116, "Recursive container", ("HierarchicalVM<TModel,TVM>", "Parent / Depth / Path", "structural messages"), "frontend"),
            Box(970, 170, 240, 132, "Forwarding decorators", ("ForwardingComponentVM", "ForwardingCompositeVM", "instrumentation / overrides"), "frontend"),
            Box(1260, 170, 260, 132, "Specialized VMs", ("FormVM", "NotificationVM", "ConfirmationVM", "DiscriminatorVM"), "security"),
            Box(
                390,
                514,
                240,
                128,
                "Capability overlays",
                (
                    "selection / expansion",
                    "CRUD / dialog / paging",
                    f"{facts.capability_count} micro-interfaces",
                ),
                "security",
            ),
            Box(680, 514, 240, 128, "State helpers", ("DerivedProperty", "ExpandableState", "SearchableState"), "database"),
            Box(970, 514, 240, 128, "Paging helpers", ("PagedComposition", "TokenPagedComposition", "filtered/scored views"), "database"),
            Box(1260, 514, 260, 128, "Services + messages", ("MessageHub", "IDialogService", "INotificationHub", "PropertyChangedMessage"), "bus"),
            Box(240, 694, 1240, 86, "Flavor surface", ("C# PascalCase, Python snake_case, TypeScript and Swift camelCase - same shape, idiomatic surface only."), "generic"),
        ),
        lines=(
            Polyline(((230, 276), (230, 320)), color="#22d3ee", label="extends", label_xy=(278, 300)),
            Polyline(((340, 224), (390, 224)), color="#22d3ee"),
            Polyline(((340, 246), (680, 246)), color="#22d3ee"),
            Polyline(((340, 268), (970, 268)), color="#22d3ee"),
            Polyline(((340, 290), (1260, 290)), color="#22d3ee"),
            Polyline(((510, 452), (510, 514)), color="#34d399", label="implements", label_xy=(566, 486)),
            Polyline(((800, 452), (800, 514)), color="#a78bfa", label="composes", label_xy=(856, 486)),
            Polyline(((1090, 452), (1090, 514)), color="#fb923c", label="wraps / decorates", label_xy=(1174, 486)),
            Polyline(((1390, 452), (1390, 514)), color="#fb7185", label="injects / posts", label_xy=(1468, 486)),
            Polyline(((1390, 642), (1390, 694)), color="#64748b"),
            Polyline(((1090, 642), (1090, 694)), color="#64748b"),
            Polyline(((800, 642), (800, 694)), color="#64748b"),
            Polyline(((510, 642), (510, 694)), color="#64748b"),
        ),
        notes=(
            Note(
                80,
                842,
                1540,
                76,
                "Reading note",
                (
                    "VMx keeps containers, decorators, helpers, and specialized VMs as separate families so host apps can compose only the primitives they need.",
                ),
                "#94a3b8",
            ),
        ),
        cards=(
            (
                "Five idioms",
                (
                    "Leaf, composite, group, aggregate, and hierarchical shapes are distinct on purpose.",
                    "Forwarding decorators and specialized VMs stay outside the core container split.",
                    "This is the same family map every flavor implements.",
                ),
            ),
            (
                "Behavior overlays",
                (
                    "Capabilities describe what a VM can do, not what it is.",
                    "State helpers and paging helpers compose beside the VM family instead of inflating the inheritance tree.",
                    "Form, dialog, notification, and discriminator behaviors remain opt-in surfaces.",
                ),
            ),
            (
                "Docs use",
                (
                    "This map is the quick orientation diagram for contributors reading the spec index.",
                    "It complements the class architecture map by grouping primitives into usage families.",
                    "The Notes Workspace diagrams later show how the families combine in practice.",
                ),
            ),
        ),
    )


def lifecycle_messaging() -> Diagram:
    return Diagram(
        diagram_id="lifecycle-messaging",
        title="Lifecycle And Messaging Flow",
        subtitle="guarded state transitions, rollback rules, and hub publication paths",
        width=1720,
        height=1040,
        boundaries=(
            Boundary(70, 118, 1580, 232, "Lifecycle state machine", "#22d3ee"),
            Boundary(70, 378, 1580, 224, "Operations and atomicity rules", "#34d399"),
            Boundary(70, 630, 1580, 240, "Hub publication and cross-VM coordination", "#a78bfa"),
        ),
        boxes=(
            Box(110, 170, 180, 94, "Destructed", ("fresh build state", "construct() legal"), "generic"),
            Box(340, 170, 180, 94, "Constructing", ("OnConstruct hook", "intermediate status"), "backend"),
            Box(570, 170, 180, 94, "Constructed", ("ready for selection", "can_reconstruct()"), "frontend"),
            Box(800, 170, 180, 94, "Destructing", ("Current clears first", "OnDestruct hook"), "backend"),
            Box(1030, 170, 180, 94, "Disposed", ("terminal", "late completion aborts"), "security"),
            Box(1300, 160, 290, 112, "Fixture-backed validator", ("spec/fixtures/lifecycle-transitions.json", "shared across all conformance suites"), "cloud"),
            Box(110, 420, 230, 122, "Operations", ("construct", "destruct", "reconstruct", "dispose"), "bus"),
            Box(390, 420, 250, 122, "Predicates", ("can_construct()", "can_destruct()", "can_reconstruct()", "safe no-op states"), "security"),
            Box(690, 420, 260, 122, "Per-VM guard", ("serializes lifecycle ops", "rejects concurrent re-entry", "prevents resurrection"), "backend"),
            Box(1000, 420, 260, 122, "Transactional rollback", ("failed construct -> Destructed", "failed destruct -> Constructed", "rollback publishes status"), "security"),
            Box(1310, 420, 260, 122, "Parent orchestration", ("composite/group/aggregate", "wait for child settled states", "sequential reference impls"), "frontend"),
            Box(110, 684, 260, 132, "ConstructionStatusChangedMessage", ("two emissions for construct/destruct", "four for reconstruct", "hot FIFO hub delivery"), "bus"),
            Box(420, 684, 260, 132, "PropertyChangedMessage", ("IsCurrent, Model, Snapshot, ActiveKey", "per-flavor property names"), "bus"),
            Box(730, 684, 260, 132, "Collection + tree messages", ("CollectionChangedMessage", "TreeStructureChangedMessage", "batch Reset interactions"), "bus"),
            Box(1040, 684, 260, 132, "Per-instance binding surface", ("INotifyPropertyChanged / propertyChanged", "adapter-friendly single-VM binding"), "frontend"),
            Box(1350, 684, 220, 132, "Consumers", ("commands", "view adapters", "cross-VM observers"), "generic"),
        ),
        lines=(
            Polyline(((290, 217), (340, 217)), color="#22d3ee", label="construct()", label_xy=(318, 202)),
            Polyline(((520, 217), (570, 217)), color="#22d3ee"),
            Polyline(((750, 217), (800, 217)), color="#fb923c", label="destruct()", label_xy=(776, 202)),
            Polyline(((980, 217), (1030, 217)), color="#fb7185", label="dispose()", label_xy=(1006, 202)),
            Polyline(((660, 264), (660, 310), (430, 310), (430, 264)), color="#34d399", label="reconstruct()", label_xy=(548, 298)),
            Polyline(((1210, 217), (1300, 217)), color="#fbbf24", label="validated by", label_xy=(1256, 202)),
            Polyline(((225, 542), (225, 684)), color="#64748b"),
            Polyline(((515, 542), (515, 684)), color="#34d399", label="gates commands", label_xy=(588, 612)),
            Polyline(((820, 542), (820, 684)), color="#fb7185", label="publishes", label_xy=(866, 612)),
            Polyline(((1130, 542), (1130, 684)), color="#fb7185"),
            Polyline(((1440, 542), (1440, 684)), color="#22d3ee", label="drives children", label_xy=(1516, 612)),
            Polyline(((370, 750), (420, 750)), color="#94a3b8"),
            Polyline(((680, 750), (730, 750)), color="#94a3b8"),
            Polyline(((990, 750), (1040, 750)), color="#94a3b8"),
            Polyline(((1300, 750), (1350, 750)), color="#94a3b8"),
        ),
        notes=(
            Note(
                120,
                874,
                1460,
                94,
                "Key rule",
                (
                    "Lifecycle operations raise when called from an illegal state, while selection after Disposed is a silent no-op.",
                    "That distinction matters for both conformance and view-adapter expectations.",
                ),
                "#fb923c",
            ),
        ),
        cards=(
            (
                "State semantics",
                (
                    "Destructed is the fresh-builder start, Constructed is the ready state, and Disposed is terminal.",
                    "Reconstruct is not shorthand in docs: it is its own observable four-step sequence.",
                    "Rollback after failed hooks is part of the normative lifecycle contract.",
                ),
            ),
            (
                "Atomicity",
                (
                    "A per-VM guard serializes lifecycle work and blocks concurrent re-entry.",
                    "Late async completions that race dispose() abort instead of reviving a torn-down VM.",
                    "Container VMs orchestrate children but do not change the core state machine.",
                ),
            ),
            (
                "Messaging",
                (
                    "Hub messages remain the cross-VM coordination surface.",
                    "Per-instance propertyChanged surfaces exist so views do not need to filter the shared hub when they bind one VM.",
                    "Collection and tree messages extend the same hot-stream model for containers and recursive trees.",
                ),
            ),
        ),
    )


def composite_family() -> Diagram:
    return Diagram(
        diagram_id="composite-family",
        title="Composite Family Deep Dive",
        subtitle="selection containers, peer groups, fixed aggregates, recursive trees, and paging companions",
        width=1760,
        height=1080,
        boundaries=(
            Boundary(70, 118, 1620, 620, "Container primitives", "#22d3ee"),
            Boundary(70, 768, 1620, 210, "Composition helpers around containers", "#a78bfa"),
        ),
        boxes=(
            Box(110, 170, 290, 168, "CompositeVM", ("ordered homogeneous children", "Current designates one selected child", "select_component / deselect_component", "ModeledCrudCommands can bind to Current"), "frontend"),
            Box(450, 170, 290, 168, "GroupVM", ("same IList surface", "peer children only", "group child select command stays disabled", "good for notification stacks"), "frontend"),
            Box(790, 170, 300, 168, "AggregateVM1..6", ("heterogeneous fixed slots", "Component1..6 accessors", "factories invoked on construct()", "best for shells and workspaces"), "frontend"),
            Box(1140, 170, 420, 168, "HierarchicalVM", ("recursive nodes with Parent / Depth / Path", "lazy or eager child materialization", "TreeStructureChangedMessage on structure changes", "walk / walk_expanded integrate naturally"), "frontend"),
            Box(150, 398, 280, 162, "Selection semantics", ("CompositeVM.Current must be null or a contained child", "children update IsCurrent on transitions", "AsyncSelection is opt-in per builder"), "security"),
            Box(490, 398, 280, 162, "Collection semantics", ("Add / Remove / Insert / Clear publish collection change", "BatchUpdate collapses granular events to one Reset"), "database"),
            Box(830, 398, 280, 162, "Construction semantics", ("container reaches Constructed after children settle", "reference implementations visit children sequentially"), "backend"),
            Box(1170, 398, 360, 162, "Tree semantics", ("HierarchicalVM rejects ancestor cycles", "InvalidateChildren refreshes the child cache", "lazy boundaries stay explicit"), "security"),
            Box(180, 810, 290, 120, "SearchableState", ("filter first", "debounced SearchTerm", "filtered view source"), "database"),
            Box(540, 810, 290, 120, "PagedComposition", ("finite page slice", "implements IPageable", "decorates iterable source"), "database"),
            Box(900, 810, 310, 120, "TokenPagedComposition", ("forward-only fetch_next(token)", "LoadMore / Refresh", "accumulated Items + HasMore"), "database"),
            Box(1280, 810, 290, 120, "ForwardingCompositeVM", ("wraps ICompositeVM<VM>", "override single behaviors", "still forwards disposal"), "frontend"),
        ),
        lines=(
            Polyline(((400, 250), (450, 250)), color="#94a3b8", label="same IList minus Current", label_xy=(432, 236)),
            Polyline(((740, 250), (790, 250)), color="#94a3b8", label="fixed heterogeneity", label_xy=(762, 236)),
            Polyline(((1090, 250), (1140, 250)), color="#94a3b8", label="recursive domain", label_xy=(1116, 236)),
            Polyline(((255, 338), (255, 398)), color="#fbbf24", label="selection", label_xy=(300, 370)),
            Polyline(((595, 338), (630, 398)), color="#a78bfa", label="events", label_xy=(650, 370)),
            Polyline(((940, 338), (970, 398)), color="#34d399", label="lifecycle", label_xy=(1000, 370)),
            Polyline(((1350, 338), (1350, 398)), color="#fb7185", label="structure", label_xy=(1400, 370)),
            Polyline(((325, 560), (325, 680), (685, 680), (685, 810)), color="#a78bfa", label="filter -> page", label_xy=(520, 664)),
            Polyline(((685, 930), (900, 930)), color="#94a3b8", label="finite vs token", label_xy=(794, 914)),
            Polyline(((1210, 870), (1280, 870)), color="#fb923c", label="wraps", label_xy=(1246, 854)),
        ),
        notes=(
            Note(
                1120,
                596,
                500,
                112,
                "Why separate primitives",
                (
                    "CompositeVM handles current selection, GroupVM represents peers, AggregateVM encodes fixed heterogeneity, and HierarchicalVM owns recursive structure.",
                    "Paging helpers sit beside those containers instead of pretending to be new container subclasses.",
                ),
                "#fb923c",
            ),
        ),
        cards=(
            (
                "Choosing a container",
                (
                    "Use CompositeVM when a current child matters.",
                    "Use GroupVM when children are peers and selection would be misleading.",
                    "Use AggregateVM when slots are heterogeneous and fixed at compile time.",
                ),
            ),
            (
                "Recursive vs paged",
                (
                    "HierarchicalVM is the tree primitive because it carries structural metadata and mutation messages.",
                    "PagedComposition and TokenPagedComposition are companion views over an existing source, not alternate container bases.",
                    "Search/filter is idiomatically applied before finite paging.",
                ),
            ),
            (
                "Docs emphasis",
                (
                    "This diagram is the bridge between the family map and the Notes Workspace example.",
                    "It explains why the framework kept several focused container types instead of flattening them.",
                    "It also answers the common question about where paging belongs in the architecture.",
                ),
            ),
        ),
    )


def commands_capabilities() -> Diagram:
    facts = SOURCE_FACTS
    return Diagram(
        diagram_id="commands-capabilities",
        title="Commands And Capabilities Map",
        subtitle=f"reactive ICommand primitives and the {facts.capability_count} opt-in behavior contracts",
        width=1780,
        height=1100,
        boundaries=(
            Boundary(70, 118, 520, 820, "Command primitives", "#fb923c"),
            Boundary(630, 118, 1080, 820, "Capability families", "#22d3ee"),
        ),
        boxes=(
            Box(120, 170, 420, 118, "ICommand / ICommand<T>", ("CanExecute / Execute / CanExecuteChanged", "parameterized variant when payload is needed"), "bus"),
            Box(120, 322, 420, 118, "RelayCommand", ("optional predicate + task", "trigger observables re-fire CanExecuteChanged", "disposed command becomes inert"), "bus"),
            Box(120, 474, 420, 118, "CompositeCommand", ("execute every enabled inner command", "aggregate CanExecute over children"), "bus"),
            Box(120, 626, 420, 118, "DecoratorCommand", ("inner command + extra gate", "optional pre/post actions"), "bus"),
            Box(120, 778, 420, 118, "ConfirmationDecoratorCommand", ("confirm delegate before Execute", "ExecuteAsync and errors channel", "fluent Confirm helper overloads"), "bus"),
            Box(690, 170, 300, 132, "Selection family", ("ISelectable", "IDeselectable", "ISelectionTogglable"), "security"),
            Box(1030, 170, 300, 132, "Expansion family", ("IExpandable", "ICollapsible", "IExpansionTogglable"), "security"),
            Box(1370, 170, 300, 132, "Lifecycle family", ("IConstructable", "IDestructable", "IReconstructable"), "security"),
            Box(690, 346, 300, 132, "Dialog / form family", ("IClosable", "IApprovable", "ICancelable"), "security"),
            Box(1030, 346, 300, 132, "Search / filter family", ("ISearchable", "IFilterable<TItem>"), "security"),
            Box(1370, 346, 300, 132, "Paging family", ("IPageable", "page navigation surface only"), "security"),
            Box(690, 522, 300, 132, "CRUD family", ("INewCreatable", "IDeletable<T>", "IUpdatable<T>", "ISavable<T>"), "security"),
            Box(1030, 522, 300, 132, "Container-current family", ("ICurrentDeletable", "ICurrentUpdatable"), "security"),
            Box(1370, 522, 300, 132, "Management escape hatch", ("IManagable<T>", "consumer-specific management action"), "security"),
            Box(820, 730, 720, 166, "Typical compositions", ("CompositeVM.Current -> ModeledCrudCommands triggers", "ExpandableState delegates expansion capabilities", "PagedComposition implements IPageable over a filtered source", "FormVM and dialogs wire commands rather than grow a custom command type"), "frontend"),
        ),
        lines=(
            Polyline(((540, 229), (690, 229)), color="#34d399", label="commands call capability verbs", label_xy=(620, 213)),
            Polyline(((540, 381), (690, 381)), color="#34d399", label="bind UI affordances", label_xy=(620, 365)),
            Polyline(((540, 533), (690, 533)), color="#34d399", label="gate CRUD", label_xy=(604, 517)),
            Polyline(((540, 685), (690, 685), (690, 588)), color="#34d399", label="extra gate", label_xy=(616, 669)),
            Polyline(((540, 837), (1030, 837)), color="#fb7185", label="confirm / dialog integration", label_xy=(786, 821)),
            Polyline(((1180, 654), (1180, 730)), color="#a78bfa", label="implemented by helpers", label_xy=(1260, 696)),
            Polyline(((1520, 478), (1520, 730)), color="#a78bfa"),
            Polyline(((840, 654), (840, 730)), color="#a78bfa"),
            Polyline(((1520, 302), (1520, 346)), color="#94a3b8"),
            Polyline(((1180, 302), (1180, 346)), color="#94a3b8"),
            Polyline(((840, 302), (840, 346)), color="#94a3b8"),
        ),
        notes=(
            Note(
                130,
                948,
                1540,
                94,
                "Why micro-interfaces matter",
                (
                    "Capability interfaces advertise exactly the verbs a VM supports, so command bars and view adapters can stay capability-based without reshaping the core VM hierarchy.",
                ),
                "#fb923c",
            ),
        ),
        cards=(
            (
                "Command stack",
                (
                    "RelayCommand is the concrete workhorse.",
                    "CompositeCommand and decorator commands layer orchestration and gating without changing the ICommand contract.",
                    "Reactive triggers keep enabled state honest when predicates depend on mutable VM state.",
                ),
            ),
            (
                "Capability taxonomy",
                (
                    "The selection and expansion triples stay granular on purpose.",
                    "CRUD is split into independent verb interfaces so VMs advertise only the mutations they support.",
                    "Paging is a navigation contract; it does not imply a specific container implementation.",
                ),
            ),
            (
                "Practical wiring",
                (
                    "ModeledCrudCommands turns current-selection state into concrete commands.",
                    "FormVM, dialog flows, and confirmation helpers compose with the same command surface.",
                    "This map explains the capability-aware action bar used in the flagship example.",
                ),
            ),
        ),
    )


def forms_dialogs_notifications() -> Diagram:
    return Diagram(
        diagram_id="forms-dialogs-notifications",
        title="Forms Dialogs And Notifications Flow",
        subtitle="edit lifecycle, modal request/response, and fire-and-forget notification channels",
        width=1720,
        height=1040,
        boundaries=(
            Boundary(70, 118, 520, 760, "FormVM edit lifecycle", "#22d3ee"),
            Boundary(620, 118, 470, 760, "Modal dialog seam", "#fbbf24"),
            Boundary(1120, 118, 530, 760, "Notification hub and rendering VMs", "#fb7185"),
        ),
        boxes=(
            Box(120, 170, 420, 128, "FormVM<TM>", ("Snapshot captured at construct()", "Model mutates via SetModel()", "IsDirty derives from Model vs Snapshot"), "frontend"),
            Box(120, 336, 200, 118, "DenyCommand", ("revert Model to Snapshot", "publish property changes"), "bus"),
            Box(340, 336, 200, 118, "ApproveCommand", ("fire-and-forget entry point", "calls ApproveAsync()", "errors -> ApproveErrors"), "bus"),
            Box(120, 494, 420, 142, "Validation surface", ("field validators + model validator", "Errors / FieldError(field)", "IsValid gates approval", "strict mode = IsDirty && IsValid"), "database"),
            Box(120, 678, 420, 146, "Success + failure channels", ("OnApproved emits persisted model", "ApproveAsync throws to awaiter", "command path surfaces failures on ApproveErrors"), "security"),
            Box(670, 210, 370, 128, "IDialogService", ("PickFileToOpen / PickFileToSave", "Confirm(message, title?)", "Notify(message, severity?)", "Present(modalVM) for VM-backed modals"), "security"),
            Box(670, 392, 370, 124, "ConfirmationDecoratorCommand", ("wraps delete or deny commands", "confirm delegate can call dialogService.Confirm()", "same pattern works for file/export prompts"), "bus"),
            Box(670, 570, 370, 140, "NullDialogService + cancellation", ("safe defaults: PickFile* -> null", "Confirm -> false, Notify -> no-op", "cancellation completes with safe default"), "generic"),
            Box(1170, 170, 430, 128, "INotificationHub", ("Post(notification) -> await NotificationReaction", "Resolve(notification, reaction)", "Pending behaves like a hot current snapshot"), "security"),
            Box(1170, 338, 200, 118, "NotificationVM", ("wraps Notification", "auto-dismiss at lifespan end", "DismissCommand resolves Approve"), "frontend"),
            Box(1400, 338, 200, 118, "ConfirmationVM", ("inherits NotificationVM", "ApproveCommand / RejectCommand", "no auto-resolve on timeout"), "frontend"),
            Box(1170, 494, 430, 140, "Bridge helper", ("make_confirm(hub, prompt) -> async bool", "posts Confirmation notification", "adapts hub flow for command decorators"), "bus"),
            Box(1170, 678, 430, 146, "Responsibility split", ("dialogs: modal request/response", "notification hub: informational or queued user action", "both can be injected into the same VM"), "generic"),
        ),
        lines=(
            Polyline(((320, 298), (220, 336)), color="#94a3b8", label="cancel path", label_xy=(242, 320)),
            Polyline(((340, 298), (440, 336)), color="#94a3b8", label="save path", label_xy=(418, 320)),
            Polyline(((220, 454), (220, 494)), color="#34d399"),
            Polyline(((440, 454), (440, 494)), color="#34d399"),
            Polyline(((330, 636), (330, 678)), color="#fb7185"),
            Polyline(((540, 394), (670, 394)), color="#fbbf24", label="wrap Deny/Delete", label_xy=(608, 378)),
            Polyline(((855, 516), (855, 570)), color="#fbbf24", label="host modal semantics", label_xy=(954, 544)),
            Polyline(((1040, 454), (1170, 454)), color="#fb7185", label="alternatively bridge via hub", label_xy=(1118, 438)),
            Polyline(((1385, 298), (1385, 338)), color="#fb7185"),
            Polyline(((1270, 456), (1270, 494)), color="#a78bfa", label="adapts", label_xy=(1318, 478)),
            Polyline(((1495, 456), (1495, 494)), color="#a78bfa"),
            Polyline(((1385, 634), (1385, 678)), color="#94a3b8"),
        ),
        notes=(
            Note(
                150,
                896,
                1450,
                86,
                "Decision rule",
                (
                    "Awaiting a user decision belongs on IDialogService. Informing the user without blocking belongs on INotificationHub.",
                ),
                "#fb923c",
            ),
        ),
        cards=(
            (
                "FormVM",
                (
                    "FormVM is an edit-lifecycle primitive, not a persistence framework.",
                    "Snapshot, dirty tracking, validation, and success/error channels all live on the VM surface.",
                    "Dialog confirmation is documented composition, not a hard dependency.",
                ),
            ),
            (
                "Dialog seam",
                (
                    "IDialogService is the host-facing modal contract for file pickers, confirms, and VM-backed modals.",
                    "NullDialogService exists so tests can stay deterministic.",
                    "ConfirmationDecoratorCommand composes directly with dialogService.Confirm().",
                ),
            ),
            (
                "Notifications",
                (
                    "The notifications package is opt-in and orthogonal to dialogs.",
                    "NotificationVM and ConfirmationVM render posted notifications without changing the core VM family.",
                    "The make_confirm bridge is the clean way to reuse notification flows for command confirmation.",
                ),
            ),
        ),
    )


def examples_vm_layer() -> Diagram:
    facts = SOURCE_FACTS
    return Diagram(
        diagram_id="examples-vm-layer",
        title="Examples VM Layer Map",
        subtitle="Notes Workspace composition contract across C#, Python, TypeScript, and Swift",
        width=1820,
        height=1120,
        boundaries=(
            Boundary(70, 118, 1680, 640, "VM layer contract", "#22d3ee"),
            Boundary(70, 786, 1680, 236, "Framework adapters and host seams", "#fb923c"),
        ),
        boxes=(
            Box(250, 160, 980, 110, "WorkspaceVM", ("wraps AggregateVM6 root and forwards lifecycle", "owns notebooksRoot, notesView, noteForm, statusBar, notifications, capabilityActions", "focusedVM derives from current notebook / note / notes view"), "frontend"),
            Box(1270, 160, 200, 110, "ThemeVM", ("palette + accent + font scale", "workspace-owned sibling VM"), "database"),
            Box(1500, 160, 200, 110, "GlobalSearchVM", ("TokenPagedComposition-based", "forward-token all-notes search"), "database"),
            Box(110, 340, 250, 180, "NotebooksRootVM", ("tree-style notebook navigation", "addNotebook emits TreeStructureChangedMessage", "expand/collapse state"), "frontend"),
            Box(400, 340, 260, 180, "NotesViewVM", ("PagedComposition over notes", "searchTerm + starred filter", "current NoteVM drives editor binding"), "frontend"),
            Box(700, 340, 270, 180, "NoteFormVM", ("FormVM<NoteModel>", "title validation + tag autocomplete", "DiscriminatorVM edit/preview mode"), "frontend"),
            Box(1010, 340, 230, 180, "StatusBarVM", ("DerivedProperty text slots", "note count, starred, editing state"), "frontend"),
            Box(1280, 340, 230, 180, "NotificationsVM", ("visible NotificationVM list", "hub-driven toast region", "cap 5 visible items"), "frontend"),
            Box(1550, 340, 180, 180, "CapabilityActionsVM", ("DerivedProperty<ActionVM[]>", "capability-aware action bar"), "frontend"),
            Box(190, 830, 320, 122, "Repository + models", ("NotebookModel / NoteModel", "loadAll, loadNotes, save, delete, search"), "cloud"),
            Box(560, 830, 320, 122, "Property / command / collection bridges", ("adapter code subscribes once to VM signals", "framework-native disabled/binding updates"), "generic"),
            Box(930, 830, 320, 122, "DialogService + dispatcher", ("host modal stack and UI scheduler", "pure-VM contract leaves UI state out of VMs"), "generic"),
            Box(1300, 830, 320, 122, "Per-framework views", ("Avalonia", "Textual", "React", "SwiftUI"), "generic"),
        ),
        lines=(
            Polyline(((490, 270), (235, 340)), color="#22d3ee", label="Component1", label_xy=(332, 292)),
            Polyline(((620, 270), (530, 340)), color="#22d3ee", label="Component2", label_xy=(580, 292)),
            Polyline(((760, 270), (835, 340)), color="#22d3ee", label="Component3", label_xy=(806, 292)),
            Polyline(((920, 270), (1125, 340)), color="#22d3ee", label="Component4", label_xy=(1004, 292)),
            Polyline(((1060, 270), (1395, 340)), color="#22d3ee", label="Component5", label_xy=(1208, 292)),
            Polyline(((1200, 270), (1640, 340)), color="#22d3ee", label="Component6", label_xy=(1420, 292)),
            Polyline(((1370, 270), (1370, 340)), color="#a78bfa", label="sibling VM", label_xy=(1432, 310)),
            Polyline(((1600, 270), (1600, 340)), color="#a78bfa"),
            Polyline(((360, 430), (400, 430)), color="#94a3b8", label="current notebook -> bindTo()", label_xy=(420, 414)),
            Polyline(((660, 430), (700, 430)), color="#94a3b8", label="current note", label_xy=(680, 414)),
            Polyline(((835, 520), (835, 620), (1125, 620), (1125, 520)), color="#fb7185", label="saved / dirty / valid", label_xy=(986, 606)),
            Polyline(((1510, 430), (1550, 430)), color="#34d399", label="focusedVM capabilities", label_xy=(1550, 414)),
            Polyline(((290, 520), (290, 830)), color="#fbbf24", label="load / mutate", label_xy=(354, 676)),
            Polyline(((530, 520), (530, 830)), color="#fbbf24"),
            Polyline(((835, 520), (1090, 830)), color="#fb7185", label="save / export", label_xy=(986, 690)),
            Polyline(((1395, 520), (1090, 830)), color="#fb7185", label="post / resolve", label_xy=(1250, 690)),
            Polyline(((720, 952), (720, 1010), (1460, 1010), (1460, 952)), color="#64748b", label="bind / render", label_xy=(1094, 996)),
            Polyline(((1090, 952), (1090, 1010), (1460, 1010)), color="#64748b"),
        ),
        notes=(
            Note(
                120,
                558,
                1590,
                138,
                "Cross-flavor parity facts",
                (
                    f"The Notes Workspace portfolio exercises {facts.notes_feature_count} VMx features in every flagship host.",
                    "ThemeVM remains a workspace-owned sibling rather than an AggregateVM7 child, while GlobalSearchVM demonstrates TokenPagedComposition.",
                    "Views stay thin; adapter code owns the framework-native property, command, collection, dialog, and dispatcher bridges.",
                ),
                "#fb923c",
            ),
        ),
        cards=(
            (
                "Root composition",
                (
                    "WorkspaceVM presents a stable language-neutral VM surface even though C# AggregateVM6 is sealed.",
                    "All four examples therefore wrap composition rather than subclassing the aggregate root directly.",
                    "The same child responsibilities show up in each host implementation.",
                ),
            ),
            (
                "Feature coverage",
                (
                    "NotesViewVM covers paging, filtering, searching, and current selection.",
                    "NoteFormVM covers FormVM validation, DiscriminatorVM modes, and SearchableState tag suggestions.",
                    "NotificationsVM and CapabilityActionsVM surface the optional notification and capability-driven UI seams.",
                ),
            ),
            (
                "Adapter boundary",
                (
                    "The VM layer stays framework-neutral and view-pure checks enforce that split.",
                    "Property, command, collection, dialog, and dispatcher adapters bridge each host toolkit to VMx.",
                    "That separation is why the example portfolio is useful as a documentation reference.",
                ),
            ),
        ),
    )


def build_diagrams() -> dict[str, Diagram]:
    return {
        "system-architecture": system_architecture(),
        "class-architecture": class_architecture(),
        "viewmodel-families": viewmodel_families(),
        "lifecycle-messaging": lifecycle_messaging(),
        "composite-family": composite_family(),
        "commands-capabilities": commands_capabilities(),
        "forms-dialogs-notifications": forms_dialogs_notifications(),
        "examples-vm-layer": examples_vm_layer(),
    }


def write_triplet(diagram: Diagram, html_name: str, svg_name: str, png_name: str) -> None:
    svg_path = DIAGRAM_DIR / svg_name
    html_path = DIAGRAM_DIR / html_name
    png_path = DIAGRAM_DIR / png_name
    svg_path.write_text(svg_doc(diagram), encoding="utf-8")
    html_path.write_text(html_doc(diagram, svg_name), encoding="utf-8")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
    try:
        subprocess.run(
            [
                "rsvg-convert",
                "-w",
                str(PNG_WIDTH),
                "-f",
                "png",
                "-o",
                str(tmp_path),
                str(svg_path),
            ],
            check=True,
        )
        subprocess.run(
            [
                "magick",
                str(tmp_path),
                "-strip",
                "-colors",
                "256",
                f"PNG8:{png_path}",
            ],
            check=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    diagrams = build_diagrams()
    registry_ids = set(SOURCE_FACTS.registry_ids)
    missing = registry_ids - diagrams.keys()
    extra = diagrams.keys() - registry_ids
    if missing or extra:
        raise SystemExit(
            f"registry mismatch: missing={sorted(missing)} extra={sorted(extra)}"
        )
    for item in registry:
        expected_title = SOURCE_FACTS.title_for(item["id"])
        if diagrams[item["id"]].title != expected_title:
            raise SystemExit(
                f"title mismatch for {item['id']}: "
                f"{diagrams[item['id']].title!r} != {expected_title!r}"
            )
        write_triplet(
            diagrams[item["id"]],
            item["html"],
            item["svg"],
            item["png"],
        )


if __name__ == "__main__":
    main()
