#!/usr/bin/env python3
"""Generate the VMx documentation diagram set.

This task intentionally keeps the source local to docs/assets/diagrams so the
docs-site branch can evolve the diagram triplets without touching shared tooling.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
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
    "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
    "'Liberation Mono', 'Courier New', monospace"
)
HTML_FONT_STACK = (
    "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
    "'Liberation Mono', 'Courier New', monospace"
)

COLORS = {
    "frontend": ("rgba(8, 51, 68, 0.4)", "#22d3ee"),
    "backend": ("rgba(6, 78, 59, 0.4)", "#34d399"),
    "database": ("rgba(76, 29, 149, 0.4)", "#a78bfa"),
    "cloud": ("rgba(120, 53, 15, 0.3)", "#fbbf24"),
    "security": ("rgba(136, 19, 55, 0.4)", "#fb7185"),
    "bus": ("rgba(251, 146, 60, 0.3)", "#fb923c"),
    "generic": ("rgba(30, 41, 59, 0.5)", "#94a3b8"),
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
    "bg": "#020617",
    "grid": "#1e293b",
    "panel_mask": "#0f172a",
    "panel_fill": "rgba(15, 23, 42, 0.88)",
    "note_mask": "#0f172a",
    "note_fill": "rgba(15, 23, 42, 0.94)",
    "boundary_fill": "rgba(2, 6, 23, 0.12)",
    "chip_fill": "#0f172a",
    "title": "#f8fafc",
    "body": "#cbd5e1",
    "muted": "#94a3b8",
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
        (
            r"(\d+)\s+library conformance IDs[\s\S]{0,180}?"
            r"(\d+)\s+(?:additional\s+)?THEME scenario IDs[\s\S]{0,80}?"
            r"\*\*(\d+)\s+total\*\*"
        ),
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


def draw_polyline_path(line: Polyline) -> str:
    return draw_polyline(
        Polyline(
            points=line.points,
            color=line.color,
            width=line.width,
            dash=line.dash,
            marker=line.marker,
        )
    )


def draw_polyline_label(line: Polyline) -> str:
    if line.label and line.label_xy:
        return draw_label_chip(line.label_xy[0], line.label_xy[1], line.label, line.color)
    return ""


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


def draw_relationship_path(rel: Relationship) -> str:
    style = RELATION_STYLES[rel.kind]
    return draw_polyline_path(
        Polyline(
            points=rel.points,
            color=style["color"],
            width=style["width"],
            dash=style["dash"] or None,
        )
    )


def draw_relationship_label(rel: Relationship) -> str:
    style = RELATION_STYLES[rel.kind]
    return draw_label_chip(rel.label_xy[0], rel.label_xy[1], rel.kind, style["color"])


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
    body_parts.extend(draw_relationship_path(rel) for rel in diagram.relationships)
    body_parts.extend(draw_polyline_path(line) for line in diagram.lines)
    body_parts.extend(draw_boundary(boundary) for boundary in diagram.boundaries)
    body_parts.extend(draw_box(box) for box in diagram.boxes)
    body_parts.extend(draw_note(note) for note in diagram.notes)
    body_parts.extend(
        label for rel in diagram.relationships if (label := draw_relationship_label(rel))
    )
    body_parts.extend(
        label for line in diagram.lines if (label := draw_polyline_label(line))
    )
    if diagram.diagram_id == "class-architecture":
        body_parts.append(relationship_legend(diagram.width - 300, 1110))
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
    del svg_name
    inline_svg = svg_doc(diagram)
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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; }}
    :root {{
      color-scheme: dark;
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
    body {{
      margin: 0;
      min-height: 100vh;
      padding: 32px;
      background: var(--page-bg);
      background-image:
        radial-gradient(circle at top left, var(--page-accent), transparent 28%),
        linear-gradient(180deg, rgba(14, 165, 233, 0.08), transparent 18rem);
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
    .svg-frame {{ min-width: 1180px; }}
    .svg-frame svg {{ display: block; width: 100%; height: auto; }}
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
      <div class="svg-frame" role="img" aria-label="{escape(diagram.title)}">
{inline_svg}
      </div>
      <p class="diagram-caption">Dark SVG source uses the VMx architecture palette and keeps arrows behind masked component boxes.</p>
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
            Box(790, 152, 250, 110, "VM families", ("component", "composite / group / aggregate", "shared collection + atomic move"), "frontend"),
            Box(550, 288, 220, 110, "Commands", ("RelayCommand", "decorators", "ModeledCrudCommands"), "bus"),
            Box(790, 288, 250, 110, "Capabilities", (f"{facts.capability_count} micro-interfaces", "selection / CRUD / paging", "opt-in behavior"), "security"),
            Box(1150, 152, 220, 110, "Services", ("MessageHub", "Dispatcher", "IDialogService", "ILocalizer"), "security"),
            Box(1390, 152, 220, 110, "Collections + state", ("VMCollection capability", "ObservableList", "DerivedProperty / SearchableState"), "database"),
            Box(1150, 288, 220, 110, "Paging primitives", ("PagedComposition", "TokenPagedComposition", "filtered ordering"), "database"),
            Box(1390, 288, 220, 110, "Notifications", ("INotificationHub", "NotificationVM", "ConfirmationVM"), "security"),
            Box(150, 536, 210, 136, "C#", ("PascalCase surface", "System.Reactive", "NuGet packages"), "frontend"),
            Box(390, 536, 210, 136, "Python", ("snake_case surface", "reactivex", "uv + pytest"), "frontend"),
            Box(630, 536, 210, 136, "TypeScript", ("camelCase surface", "rxjs", "dual ESM/CJS"), "frontend"),
            Box(870, 536, 210, 136, "Swift", ("camelCase surface", "Combine", "SwiftPM resources"), "frontend"),
            Box(1110, 536, 210, 136, "Rust", ("Rust type names", "rxrust facade", "Cargo crate"), "frontend"),
            Box(1350, 536, 220, 136, "Compatibility matrix", ("independent package versions", "manual spec mapping", "major bumps track spec majors"), "generic"),
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
            Polyline(((660, 398), (255, 536)), color="#22d3ee", label="idiomatic APIs", label_xy=(474, 448)),
            Polyline(((660, 398), (495, 536)), color="#22d3ee"),
            Polyline(((790, 398), (735, 536)), color="#22d3ee"),
            Polyline(((920, 398), (975, 536)), color="#22d3ee"),
            Polyline(((1040, 398), (1215, 536)), color="#22d3ee"),
            Polyline(((1270, 398), (1460, 536)), color="#a78bfa", label="versioned separately", label_xy=(1380, 450)),
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
                    "C#, Python, TypeScript, Swift, and Rust share one conceptual runtime with idiomatic casing only.",
                    "Reactive primitives stay native per flavor: System.Reactive, reactivex, rxjs, Combine, and rxrust facade.",
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
        height=1370,
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
            Relationship("extends", ((500, 202), (330, 202)), (365, 130)),
            Relationship("extends", ((780, 202), (330, 202)), (635, 130)),
            Relationship("extends", ((1060, 202), (330, 202)), (920, 130)),
            Relationship("extends", ((1340, 202), (330, 202)), (1195, 130)),
            Relationship("extends", ((1620, 202), (330, 202)), (1480, 130)),
            Relationship("implements", ((500, 262), (500, 330), (200, 330), (200, 402)), (330, 350)),
            Relationship("implements", ((780, 262), (780, 330), (800, 330), (800, 402)), (828, 350)),
            Relationship("wraps", ((360, 450), (310, 450)), (336, 434)),
            Relationship("wraps", ((960, 450), (910, 450)), (936, 434)),
            Relationship("owns", ((340, 616), (390, 616)), (365, 535)),
            Relationship("owns", ((340, 642), (650, 642)), (515, 535)),
            Relationship("extends", ((1270, 616), (1210, 616)), (1240, 535)),
            Relationship("implements", ((465, 744), (465, 700), (195, 700), (195, 852)), (310, 718)),
            Relationship("decorates", ((630, 804), (300, 804)), (464, 722)),
            Relationship("decorates", ((920, 804), (300, 804)), (628, 722)),
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
                1274,
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
            Box(240, 694, 1240, 86, "Flavor surface", ("C# PascalCase, Python/Rust snake_case methods, TypeScript/Swift camelCase - same shape, idiomatic surface only."), "generic"),
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
            Boundary(70, 630, 1580, 240, "Hub publication, transaction queue, and cross-VM coordination", "#a78bfa"),
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
            Box(90, 684, 220, 132, "Status messages", ("construction status", "2 / 4 lifecycle emissions", "hot FIFO delivery"), "bus"),
            Box(345, 684, 220, 132, "Property messages", ("IsCurrent / Model", "Snapshot / ActiveKey", "per-flavor names"), "bus"),
            Box(600, 684, 220, 132, "Collection + tree", ("collection changes", "tree structure changes", "batch Reset"), "bus"),
            Box(855, 684, 220, 132, "Transaction queue", ("nested scopes flatten", "lossless outer flush", "re-entrant append"), "bus"),
            Box(1110, 684, 220, 132, "Per-instance bindings", ("property change events", "single-VM adapters", "bypass shared hub"), "frontend"),
            Box(1365, 684, 220, 132, "Consumers", ("commands", "view adapters", "cross-VM observers"), "generic"),
        ),
        lines=(
            Polyline(((290, 217), (340, 217)), color="#22d3ee", label="construct()", label_xy=(318, 202)),
            Polyline(((520, 217), (570, 217)), color="#22d3ee"),
            Polyline(((750, 217), (800, 217)), color="#fb923c", label="destruct()", label_xy=(776, 202)),
            Polyline(((980, 217), (1030, 217)), color="#fb7185", label="dispose()", label_xy=(1006, 202)),
            Polyline(((660, 264), (660, 310), (430, 310), (430, 264)), color="#34d399", label="reconstruct()", label_xy=(548, 298)),
            Polyline(((1210, 217), (1300, 217)), color="#fbbf24", label="validated by", label_xy=(1256, 202)),
            Polyline(((225, 542), (200, 684)), color="#64748b"),
            Polyline(((515, 542), (455, 684)), color="#34d399", label="gates commands", label_xy=(548, 612)),
            Polyline(((820, 542), (965, 684)), color="#fb7185", label="serializes", label_xy=(914, 612)),
            Polyline(((1130, 542), (965, 684)), color="#fb7185", label="queues rollback", label_xy=(1072, 612)),
            Polyline(((1440, 542), (710, 684)), color="#22d3ee", label="drives children", label_xy=(1250, 612)),
            Polyline(((965, 816), (965, 840), (1475, 840), (1475, 816)), color="#a78bfa", label="iterative drain", label_xy=(1220, 836)),
            Polyline(((1330, 790), (1365, 790)), color="#22d3ee"),
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
                    "Hub transactions defer a lossless FIFO until the outer scope exits; re-entrant sends append to the same iterative drain.",
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
                    "Hub transactions preserve every typed message while deferring one iterative FIFO drain until the outermost scope exits.",
                    "Subscriber-generated messages append to the same queue instead of recursively re-entering the subject.",
                    "Per-instance propertyChanged surfaces exist so views do not need to filter the shared hub when they bind one VM.",
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
            Box(150, 398, 280, 162, "Selection semantics", ("Current is null or contained", "children update IsCurrent", "AsyncSelection is opt-in"), "security"),
            Box(490, 398, 280, 162, "Collection semantics", ("shared group/composite capability", "Move preserves child identity", "one Move or batched Reset"), "database"),
            Box(830, 398, 280, 162, "Construction semantics", ("Constructed after children settle", "reference implementations", "visit children sequentially"), "backend"),
            Box(1170, 398, 360, 162, "Tree semantics", ("HierarchicalVM rejects ancestor cycles", "InvalidateChildren refreshes the child cache", "lazy boundaries stay explicit"), "security"),
            Box(180, 810, 290, 120, "SearchableState", ("filter first", "debounced SearchTerm", "filtered view source"), "database"),
            Box(540, 810, 290, 120, "PagedComposition", ("finite page slice", "implements IPageable", "decorates iterable source"), "database"),
            Box(900, 810, 310, 120, "TokenPagedComposition", ("forward-only fetch_next(token)", "LoadMore / Refresh", "accumulated Items + HasMore"), "database"),
            Box(1280, 810, 290, 120, "ForwardingCompositeVM", ("wraps ICompositeVM<VM>", "override single behaviors", "still forwards disposal"), "frontend"),
        ),
        lines=(
            Polyline(((400, 250), (450, 250)), color="#94a3b8", label="same IList minus Current", label_xy=(432, 150)),
            Polyline(((740, 250), (790, 250)), color="#94a3b8", label="fixed heterogeneity", label_xy=(762, 150)),
            Polyline(((1090, 250), (1140, 250)), color="#94a3b8", label="recursive domain", label_xy=(1116, 150)),
            Polyline(((255, 338), (255, 398)), color="#fbbf24", label="selection", label_xy=(300, 370)),
            Polyline(((595, 338), (630, 398)), color="#a78bfa", label="events", label_xy=(650, 370)),
            Polyline(((940, 338), (970, 398)), color="#34d399", label="lifecycle", label_xy=(1000, 370)),
            Polyline(((1350, 338), (1350, 398)), color="#fb7185", label="structure", label_xy=(1400, 370)),
            Polyline(((325, 560), (325, 680), (685, 680), (685, 810)), color="#a78bfa", label="filter -> page", label_xy=(520, 664)),
            Polyline(((685, 930), (900, 930)), color="#94a3b8", label="finite vs token", label_xy=(794, 955)),
            Polyline(((1210, 870), (1280, 870)), color="#fb923c", label="wraps", label_xy=(1246, 854)),
        ),
        notes=(
            Note(
                1040,
                596,
                610,
                112,
                "Why separate primitives",
                (
                    "CompositeVM adds Current; both families share VMCollection.",
                    "AggregateVM owns fixed slots; HierarchicalVM owns trees.",
                    "Paging helpers sit beside containers, not under them.",
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


def component_family() -> Diagram:
    return Diagram(
        diagram_id="component-family",
        title="Component Family Map",
        subtitle="leaf viewmodels, modeled payloads, readonly projections, and the uniform lifecycle surface",
        width=1680,
        height=980,
        boundaries=(
            Boundary(70, 118, 1540, 266, "Leaf lineage", "#22d3ee"),
            Boundary(70, 414, 1540, 242, "Leaf behavior surface", "#34d399"),
            Boundary(70, 686, 1540, 166, "Host and parent seams", "#a78bfa"),
        ),
        boxes=(
            Box(120, 164, 260, 112, "ComponentVMBase", ("lifecycle state", "hub + dispatcher", "construct/destruct hooks"), "backend"),
            Box(450, 164, 260, 112, "ComponentVM", ("plain leaf", "no model payload", "addressable VM surface"), "frontend"),
            Box(780, 164, 300, 112, "ComponentVM<M>", ("mutable model payload", "ModeledHint recomputes", "model change notifications"), "frontend"),
            Box(1150, 164, 300, 112, "ReadonlyComponentVM<M>", ("immutable projection", "assignment rejected", "safe display leaf"), "frontend"),
            Box(150, 462, 260, 112, "Selection commands", ("Select / Deselect", "Toggle selection", "next/previous inert on leaf"), "bus"),
            Box(470, 462, 260, 112, "Parent back-reference", ("owned by container", "drives can_select()", "cleared on removal"), "security"),
            Box(790, 462, 260, 112, "Dual-channel helper", ("equality + assignment first", "hub message exactly once", "inert after disposal"), "bus"),
            Box(1110, 462, 310, 112, "Per-instance binding", ("local notification second", "view adapter subscribes once", "current value is observable"), "frontend"),
            Box(170, 724, 320, 94, "Used by containers", ("CompositeVM rows", "GroupVM peers", "AggregateVM slots"), "generic"),
            Box(590, 724, 320, 94, "Used by examples", ("NoteVM", "NotebookVM", "Status panels"), "generic"),
            Box(1010, 724, 360, 94, "Wrapped when needed", ("ForwardingComponentVM", "instrumentation without copying", "policy and host adapters"), "generic"),
        ),
        lines=(
            Polyline(((380, 220), (450, 220)), color="#22d3ee", label="extends", label_xy=(416, 204)),
            Polyline(((710, 220), (780, 220)), color="#22d3ee", label="modeled", label_xy=(746, 204)),
            Polyline(((1080, 220), (1150, 220)), color="#22d3ee", label="readonly", label_xy=(1116, 204)),
            Polyline(((580, 276), (280, 462)), color="#fb923c", label="commands", label_xy=(398, 366)),
            Polyline(((580, 276), (600, 462)), color="#34d399", label="parent context", label_xy=(668, 366)),
            Polyline(((710, 276), (920, 462)), color="#fb923c", label="hub first", label_xy=(842, 366)),
            Polyline(((1050, 518), (1110, 518)), color="#a78bfa", label="local second", label_xy=(1080, 500)),
            Polyline(((300, 574), (300, 724)), color="#64748b"),
            Polyline(((920, 574), (750, 724)), color="#64748b", label="example leaves", label_xy=(812, 650)),
            Polyline(((1265, 574), (1190, 724)), color="#fb923c", label="wraps", label_xy=(1250, 650)),
        ),
        notes=(
            Note(
                120,
                876,
                1420,
                68,
                "Decision rule",
                (
                    "Start with ComponentVM for a single addressable thing; move to a container only when the VM owns children.",
                ),
                "#22d3ee",
            ),
        ),
        cards=(
            (
                "Leaf ownership",
                (
                    "ComponentVM owns one addressable surface and no children.",
                    "Modeled variants add payload semantics without changing the lifecycle contract.",
                    "Readonly modeled leaves are projections for immutable state.",
                ),
            ),
            (
                "Uniform behavior",
                (
                    "Leaf VMs still expose lifecycle, selection, property, and command surfaces.",
                    "Selection is parent-aware, so a standalone leaf cannot accidentally select itself.",
                    "Model and hint updates are observable through hub and per-instance binding streams.",
                ),
            ),
            (
                "Best fit",
                (
                    "Use leaves for rows, panels, action bars, status blocks, and render-ready projections.",
                    "Wrap leaves with forwarding decorators when adapting behavior is cleaner than subclassing.",
                    "Promote to Composite, Group, Aggregate, or Hierarchical only when child ownership appears.",
                ),
            ),
        ),
    )


def aggregate_family() -> Diagram:
    return Diagram(
        diagram_id="aggregate-family",
        title="Aggregate Family Map",
        subtitle="fixed heterogeneous slots with lazy construction and stable semantic child roles",
        width=1700,
        height=1000,
        boundaries=(
            Boundary(70, 118, 1560, 292, "Arity and slot contract", "#22d3ee"),
            Boundary(70, 438, 1560, 244, "Construction and messaging", "#34d399"),
            Boundary(70, 710, 1560, 168, "Best-fit composition roots", "#fb923c"),
        ),
        boxes=(
            Box(120, 166, 300, 118, "AggregateVM1..6", ("component-shaped parent", "fixed arity", "heterogeneous child roles"), "frontend"),
            Box(500, 166, 250, 118, "Slot factories", ("Component1(...) through Component6(...)", "invoked during construct()", "stable semantic names"), "cloud"),
            Box(830, 166, 250, 118, "Typed slots", ("Component1..6", "property per slot", "no list indexing"), "frontend"),
            Box(1160, 166, 330, 118, "Compile-time contract", ("arity is explicit", "portable across five source flavors", "no variadic escape hatch"), "security"),
            Box(150, 486, 300, 112, "Construct cascade", ("populate slot", "construct child", "aggregate settles last"), "backend"),
            Box(520, 486, 300, 112, "Destruct cascade", ("children first", "parent settles after slots", "dispose remains terminal"), "backend"),
            Box(890, 486, 300, 112, "Property messages", ("slot property changed", "lifecycle status", "per-flavor casing"), "bus"),
            Box(1260, 486, 280, 112, "No collection surface", ("fixed children", "no Current", "no add/remove API"), "generic"),
            Box(160, 748, 330, 96, "Workspace shell", ("Notes Workspace root", "named panes and coordinators"), "generic"),
            Box(610, 748, 330, 96, "Dashboard root", ("heterogeneous panels", "stable layout contract"), "generic"),
            Box(1060, 748, 330, 96, "Service bundle", ("typed child VMs", "host adapter entry point"), "generic"),
        ),
        lines=(
            Polyline(((420, 225), (500, 225)), color="#fbbf24", label="configured by", label_xy=(462, 208)),
            Polyline(((750, 225), (830, 225)), color="#22d3ee", label="creates", label_xy=(792, 208)),
            Polyline(((1080, 225), (1160, 225)), color="#fb7185", label="preserves", label_xy=(1122, 208)),
            Polyline(((270, 284), (300, 486)), color="#34d399", label="construct()", label_xy=(352, 388)),
            Polyline(((625, 284), (670, 486)), color="#34d399"),
            Polyline(((955, 284), (1040, 486)), color="#fb923c", label="publish", label_xy=(1040, 388)),
            Polyline(((1325, 284), (1400, 486)), color="#94a3b8", label="not a list", label_xy=(1400, 388)),
            Polyline(((300, 598), (325, 748)), color="#64748b"),
            Polyline(((1040, 598), (775, 748)), color="#64748b", label="slot state drives UI", label_xy=(852, 684)),
            Polyline(((1400, 598), (1225, 748)), color="#64748b"),
        ),
        notes=(
            Note(
                130,
                902,
                1460,
                62,
                "Decision rule",
                (
                    "Choose AggregateVM when the parent contract names each child role; choose CompositeVM or GroupVM when the child set is list-like.",
                ),
                "#fb923c",
            ),
        ),
        cards=(
            (
                "Fixed roles",
                (
                    "AggregateVM1..6 encode semantic child slots instead of collection membership.",
                    "The arity appears in the type so cross-language examples stay honest.",
                    "Each child may have a different VM type.",
                ),
            ),
            (
                "Lifecycle",
                (
                    "Slot factories run during construction.",
                    "The aggregate reaches Constructed only after populated children settle.",
                    "Slot property changes are observable with idiomatic per-flavor names.",
                ),
            ),
            (
                "Best fit",
                (
                    "Use aggregates for workspace roots, dashboards, and composition shells.",
                    "Do not use aggregates as a substitute for variable-length child lists.",
                    "Wrap an aggregate in an app-specific VM when the host needs a narrower facade.",
                ),
            ),
        ),
    )


def group_family() -> Diagram:
    return Diagram(
        diagram_id="group-family",
        title="Group Family Map",
        subtitle="ordered homogeneous peer ownership without current-selection semantics",
        width=1680,
        height=980,
        boundaries=(
            Boundary(70, 118, 1540, 268, "Peer collection shape", "#22d3ee"),
            Boundary(70, 416, 1540, 246, "Mutation and lifecycle semantics", "#34d399"),
            Boundary(70, 692, 1540, 166, "Use cases", "#a78bfa"),
        ),
        boxes=(
            Box(120, 166, 300, 120, "GroupVM<VM>", ("homogeneous children", "ordered list surface", "parent is selectable"), "frontend"),
            Box(500, 166, 280, 120, "Peer children", ("no Current", "child select command disabled", "selection lives elsewhere"), "security"),
            Box(860, 166, 280, 120, "Collection API", ("shared VMCollection contract", "add / replace / remove / clear", "atomic identity-preserving move"), "database"),
            Box(1220, 166, 270, 120, "Collection messages", ("one Move with both indices", "BatchUpdate -> Reset", "same-index move is silent"), "bus"),
            Box(150, 466, 300, 112, "Construct children", ("wait for all children", "auto-construct on add is opt-in", "sequential reference flow"), "backend"),
            Box(520, 466, 300, 112, "Destruct children", ("wait for children", "clear parent context", "parent settles last"), "backend"),
            Box(890, 466, 300, 112, "Toolbar/action rows", ("capability action lists", "button groups", "visible peers"), "frontend"),
            Box(1260, 466, 280, 112, "Notification stacks", ("visible toast VMs", "no selected toast", "bounded peer set"), "security"),
            Box(170, 730, 330, 94, "Choose over Composite", ("when Current would lie", "peer list is enough"), "generic"),
            Box(610, 730, 330, 94, "Choose over Aggregate", ("child count varies", "roles are equivalent"), "generic"),
            Box(1050, 730, 330, 94, "Host adapter fit", ("renders repeaters", "stable collection bridge"), "generic"),
        ),
        lines=(
            Polyline(((420, 226), (500, 226)), color="#22d3ee", label="owns", label_xy=(462, 210)),
            Polyline(((780, 226), (860, 226)), color="#a78bfa", label="mutates", label_xy=(822, 210)),
            Polyline(((1140, 226), (1220, 226)), color="#fb923c", label="publishes", label_xy=(1182, 210)),
            Polyline(((270, 286), (300, 466)), color="#34d399", label="construct()", label_xy=(346, 376)),
            Polyline(((640, 286), (670, 466)), color="#34d399"),
            Polyline(((1000, 286), (1040, 466)), color="#64748b", label="render peers", label_xy=(1094, 376)),
            Polyline(((1360, 286), (1400, 466)), color="#fb7185"),
            Polyline(((1040, 578), (335, 730)), color="#64748b", label="selection avoided", label_xy=(676, 646)),
            Polyline(((1040, 578), (775, 730)), color="#64748b"),
            Polyline(((1040, 578), (1215, 730)), color="#64748b"),
        ),
        notes=(
            Note(
                130,
                882,
                1420,
                62,
                "Decision rule",
                (
                    "Use GroupVM when the parent owns children but no child should be treated as current.",
                ),
                "#22d3ee",
            ),
        ),
        cards=(
            (
                "Peer shape",
                (
                    "GroupVM preserves homogeneous collection behavior without Current.",
                    "Children are still owned and lifecycle-managed by the group.",
                    "The group itself may be selected by its own parent.",
                ),
            ),
            (
                "Events",
                (
                    "Groups and composites publish the same VM collection-change contract.",
                    "Move changes order without reconstructing, reparenting, or replacing the child.",
                    "Batch updates collapse many mutations to one Reset.",
                    "Lifecycle orchestration matches CompositeVM without selection work.",
                ),
            ),
            (
                "Best fit",
                (
                    "Use groups for toolbars, notification stacks, peer panels, and capability rows.",
                    "Use CompositeVM when current selection matters.",
                    "Use AggregateVM when child roles are fixed and heterogeneous.",
                ),
            ),
        ),
    )


def hierarchical_family() -> Diagram:
    return Diagram(
        diagram_id="hierarchical-family",
        title="Hierarchical Family Map",
        subtitle="recursive model ownership with parent/depth/path metadata and tree mutation messages",
        width=1720,
        height=1040,
        boundaries=(
            Boundary(70, 118, 1580, 286, "Recursive node contract", "#22d3ee"),
            Boundary(70, 434, 1580, 258, "Materialization and mutation", "#34d399"),
            Boundary(70, 722, 1580, 176, "Traversal and host rendering", "#a78bfa"),
        ),
        boxes=(
            Box(120, 166, 300, 122, "HierarchicalVM<TModel, TVM>", ("modeled recursive node", "children are same VM family", "root and leaf semantics"), "frontend"),
            Box(500, 166, 250, 122, "Structural metadata", ("Parent", "Depth / Path", "IsRoot / IsLeaf"), "database"),
            Box(830, 166, 250, 122, "Children cache", ("lazy by default", "eager option", "invalidate subtree"), "database"),
            Box(1160, 166, 330, 122, "Cycle protection", ("reject ancestor cycles", "stable parent links", "safe tree mutation"), "security"),
            Box(150, 482, 300, 116, "Materialize children", ("factory resolves child models", "TVM node projection", "lazy boundary stays explicit"), "backend"),
            Box(520, 482, 300, 116, "TreeStructureChangedMessage", ("add/remove/move", "invalidate children", "recursive observers"), "bus"),
            Box(890, 482, 300, 116, "ExpandableState", ("expanded/collapsed view state", "walk_expanded()", "view-owned display shape"), "frontend"),
            Box(1260, 482, 280, 116, "Lifecycle cascade", ("eager subtree participates", "lazy subtree waits", "disposed nodes stop mutating"), "backend"),
            Box(180, 762, 330, 98, "Explorer trees", ("folders", "notebooks", "taxonomies"), "generic"),
            Box(620, 762, 330, 98, "Walk utilities", ("walk()", "walk_expanded()", "flattened views"), "generic"),
            Box(1060, 762, 330, 98, "Adapters", ("tree widgets", "outline views", "virtualized renderers"), "generic"),
        ),
        lines=(
            Polyline(((420, 226), (500, 226)), color="#22d3ee", label="exposes", label_xy=(462, 210)),
            Polyline(((750, 226), (830, 226)), color="#a78bfa", label="owns", label_xy=(792, 210)),
            Polyline(((1080, 226), (1160, 226)), color="#fb7185", label="guards", label_xy=(1122, 210)),
            Polyline(((270, 288), (300, 482)), color="#34d399", label="materialize", label_xy=(354, 384)),
            Polyline(((955, 288), (670, 482)), color="#fb923c", label="publish structure", label_xy=(760, 384)),
            Polyline(((955, 288), (1040, 482)), color="#22d3ee", label="view state", label_xy=(1034, 384)),
            Polyline(((1325, 288), (1400, 482)), color="#34d399", label="cascade", label_xy=(1440, 384)),
            Polyline(((300, 598), (345, 762)), color="#64748b"),
            Polyline(((670, 598), (785, 762)), color="#64748b", label="flatten", label_xy=(760, 682)),
            Polyline(((1040, 598), (1225, 762)), color="#64748b", label="render", label_xy=(1180, 682)),
        ),
        notes=(
            Note(
                130,
                920,
                1460,
                68,
                "Decision rule",
                (
                    "Use HierarchicalVM when recursive structure is part of the VM contract; avoid rebuilding tree metadata with nested composites.",
                ),
                "#a78bfa",
            ),
        ),
        cards=(
            (
                "Recursive contract",
                (
                    "Each node owns its model and same-family child nodes.",
                    "Parent, depth, path, root, and leaf facts are built into the primitive.",
                    "Cycle protection keeps tree mutation safe.",
                ),
            ),
            (
                "Materialization",
                (
                    "Children are lazy unless eager construction is requested.",
                    "Invalidation and structural changes publish explicit tree messages.",
                    "Lazy subtrees do not participate in lifecycle until materialized.",
                ),
            ),
            (
                "Best fit",
                (
                    "Use it for explorer trees, notebooks, outlines, and taxonomies.",
                    "Pair with ExpandableState and walk utilities for renderable flattened views.",
                    "Use CompositeVM only when the domain is a list, not a recursive tree.",
                ),
            ),
        ),
    )


def forwarding_wrapper_family() -> Diagram:
    return Diagram(
        diagram_id="forwarding-wrapper-family",
        title="Forwarding Wrapper Family Map",
        subtitle="composition-first decorators for instrumentation, policy, and host adaptation",
        width=1700,
        height=1000,
        boundaries=(
            Boundary(70, 118, 1560, 282, "Wrapper contracts", "#22d3ee"),
            Boundary(70, 428, 1560, 250, "Override seams", "#34d399"),
            Boundary(70, 706, 1560, 168, "Best-fit wrapper use cases", "#fb923c"),
        ),
        boxes=(
            Box(120, 166, 300, 120, "ForwardingComponentVM<M>", ("wraps component contract", "delegates by default", "override selected members"), "frontend"),
            Box(500, 166, 300, 120, "ForwardingCompositeVM<VM>", ("wraps composite contract", "forwards Current + iteration", "decorates child access"), "frontend"),
            Box(880, 166, 270, 120, "Inner VM", ("canonical implementation", "owns real state", "publishes real messages"), "backend"),
            Box(1230, 166, 280, 120, "Public facade", ("same conceptual surface", "narrow host policy", "no copied VM logic"), "security"),
            Box(150, 476, 280, 112, "Lifecycle forwarding", ("construct/destruct/dispose", "usually delegate", "ownership remains explicit"), "backend"),
            Box(500, 476, 280, 112, "Property forwarding", ("model/current/name/hint", "per-instance propertyChanged", "hub messages unchanged"), "bus"),
            Box(850, 476, 280, 112, "Command wrapping", ("gate existing command", "log or meter execution", "policy before delegate"), "bus"),
            Box(1200, 476, 300, 112, "Selective override", ("small behavior patch", "adapter-specific shape", "test seam without fork"), "database"),
            Box(180, 744, 320, 96, "Instrumentation", ("logging", "metrics", "diagnostic traces"), "generic"),
            Box(610, 744, 320, 96, "Policy", ("authorization", "feature flags", "confirmation gates"), "generic"),
            Box(1040, 744, 320, 96, "Host adaptation", ("framework bridge", "narrow facade", "legacy integration"), "generic"),
        ),
        lines=(
            Polyline(((420, 226), (500, 226)), color="#22d3ee", label="same pattern", label_xy=(462, 210)),
            Polyline(((800, 226), (880, 226)), color="#fb923c", label="wraps", label_xy=(842, 210)),
            Polyline(((1150, 226), (1230, 226)), color="#34d399", label="exposes", label_xy=(1192, 210)),
            Polyline(((270, 286), (290, 476)), color="#34d399", label="delegate", label_xy=(340, 384)),
            Polyline(((650, 286), (640, 476)), color="#fb923c", label="mirror", label_xy=(704, 384)),
            Polyline(((1015, 286), (990, 476)), color="#fb923c", label="wrap calls", label_xy=(1060, 384)),
            Polyline(((1370, 286), (1350, 476)), color="#a78bfa", label="override", label_xy=(1420, 384)),
            Polyline(((290, 588), (340, 744)), color="#64748b"),
            Polyline(((990, 588), (770, 744)), color="#64748b", label="policy hooks", label_xy=(850, 674)),
            Polyline(((1350, 588), (1200, 744)), color="#64748b", label="host seam", label_xy=(1300, 674)),
        ),
        notes=(
            Note(
                130,
                900,
                1460,
                64,
                "Decision rule",
                (
                    "Use forwarding wrappers when composition can adapt one behavior without re-implementing a shipped VM family.",
                ),
                "#fb923c",
            ),
        ),
        cards=(
            (
                "Composition first",
                (
                    "Wrappers hold an inner VM and delegate by default.",
                    "The inner VM remains the source of state and messages.",
                    "Overrides stay local to the behavior being adapted.",
                ),
            ),
            (
                "Two contracts",
                (
                    "ForwardingComponentVM decorates component-shaped surfaces.",
                    "ForwardingCompositeVM decorates child-list and Current-selection surfaces.",
                    "Both preserve lifecycle ownership when dispose forwards.",
                ),
            ),
            (
                "Best fit",
                (
                    "Use wrappers for logging, policy, host adaptation, and compatibility seams.",
                    "Do not copy VM internals just to intercept one property or command.",
                    "Prefer a specialized VM only when the workflow is reusable in its own right.",
                ),
            ),
        ),
    )


def specialized_vm_family() -> Diagram:
    return Diagram(
        diagram_id="specialized-vm-family",
        title="Specialized ViewModel Coordinator Map",
        subtitle="workflow-specific VMs that compose with the core hierarchy instead of replacing it",
        width=1740,
        height=1040,
        boundaries=(
            Boundary(70, 118, 1600, 286, "Workflow primitives", "#22d3ee"),
            Boundary(70, 434, 1600, 258, "Coordinator services and messages", "#34d399"),
            Boundary(70, 722, 1600, 176, "Host-facing use cases", "#fb923c"),
        ),
        boxes=(
            Box(120, 166, 270, 122, "FormVM", ("snapshot + dirty state", "validation + approval", "deny restores model"), "frontend"),
            Box(460, 166, 270, 122, "DiscriminatorVM", ("ActiveKey", "case registry", "mode/pane coordination"), "frontend"),
            Box(800, 166, 270, 122, "NotificationVM", ("render-ready notification", "dismiss command", "auto-resolve by lifespan"), "security"),
            Box(1140, 166, 270, 122, "ConfirmationVM", ("inherits NotificationVM", "approve/reject commands", "no timeout auto-resolve"), "security"),
            Box(150, 482, 300, 116, "ModalVM", ("presented VM workflow", "completion state", "host dialog bridge"), "frontend"),
            Box(520, 482, 300, 116, "IDialogService", ("confirm / notify / pick file", "VM-backed modal seam", "safe null service"), "security"),
            Box(890, 482, 300, 116, "INotificationHub", ("post / resolve", "pending snapshot", "await user reaction"), "security"),
            Box(1260, 482, 300, 116, "Command adapters", ("ConfirmationDecoratorCommand", "make_confirm helper", "approve/deny wiring"), "bus"),
            Box(180, 762, 330, 98, "Editor workflows", ("FormVM + DiscriminatorVM", "edit/preview modes"), "generic"),
            Box(620, 762, 330, 98, "User decisions", ("dialog confirmations", "notification-backed confirms"), "generic"),
            Box(1060, 762, 330, 98, "Notification regions", ("toast lists", "queued actions", "host render VMs"), "generic"),
        ),
        lines=(
            Polyline(((390, 226), (460, 226)), color="#22d3ee", label="coordinates modes", label_xy=(426, 210)),
            Polyline(((1070, 226), (1140, 226)), color="#22d3ee", label="extends", label_xy=(1106, 210)),
            Polyline(((255, 288), (300, 482)), color="#fb923c", label="modal edit", label_xy=(360, 384)),
            Polyline(((595, 288), (670, 482)), color="#fbbf24", label="host decision", label_xy=(724, 384)),
            Polyline(((935, 288), (1040, 482)), color="#fb7185", label="posts", label_xy=(1010, 384)),
            Polyline(((1275, 288), (1410, 482)), color="#fb923c", label="commands", label_xy=(1404, 384)),
            Polyline(((300, 598), (345, 762)), color="#64748b"),
            Polyline(((670, 598), (785, 762)), color="#64748b", label="await", label_xy=(760, 682)),
            Polyline(((1040, 598), (1225, 762)), color="#64748b", label="render", label_xy=(1180, 682)),
            Polyline(((1410, 598), (785, 762)), color="#64748b"),
        ),
        notes=(
            Note(
                130,
                920,
                1480,
                68,
                "Decision rule",
                (
                    "Choose a specialized VM when the workflow is reusable; otherwise compose commands, capabilities, and core VMs directly.",
                ),
                "#fb923c",
            ),
        ),
        cards=(
            (
                "Workflow ownership",
                (
                    "FormVM owns edit lifecycle rather than container membership.",
                    "DiscriminatorVM coordinates active cases without becoming a child-list primitive.",
                    "ModalVM bridges a presented VM to host completion semantics.",
                ),
            ),
            (
                "Notification flow",
                (
                    "NotificationVM and ConfirmationVM render hub-posted notifications.",
                    "INotificationHub owns post/resolve and pending snapshot behavior.",
                    "Confirmation helpers adapt hub reactions to command confirmation delegates.",
                ),
            ),
            (
                "Best fit",
                (
                    "Use these primitives for recurring app workflows: forms, modes, modals, confirms, and toasts.",
                    "Keep leaf/container hierarchy choices separate from workflow coordination.",
                    "The Notes Workspace examples combine these with Aggregate, Composite, and Component families.",
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


def rust_tui_notes_showcase() -> Diagram:
    return Diagram(
        diagram_id="rust-tui-notes-showcase",
        title="Rust TUI Notes Showcase VM Layer",
        subtitle="Ratatui renders snapshots; VMx owns application state, commands, and lifecycle",
        width=1820,
        height=1160,
        boundaries=(
            Boundary(70, 118, 1680, 680, "Pure VMx MVVM layer", "#22d3ee"),
            Boundary(70, 830, 1680, 220, "Terminal host adapter", "#fb923c"),
        ),
        boxes=(
            Box(710, 160, 400, 108, "WorkspaceVm", ("AggregateVm6 composition root", "constructs/destructs child VMs", "exposes host-safe commands"), "frontend"),
            Box(120, 340, 235, 150, "NotebooksVm", ("ComponentVm lifecycle", "current notebook id", "selection command"), "frontend"),
            Box(390, 340, 270, 150, "NotesViewVm", ("CompositeVm<NoteVm>", "FilteredCompositeVm search", "PagedComposition pages"), "frontend"),
            Box(700, 340, 250, 150, "NoteFormVm", ("FormVm<NoteDraft>", "strict dirty tracking", "field + model validators"), "frontend"),
            Box(990, 340, 280, 150, "GlobalSearchVm", ("SearchableState", "TokenPagedComposition", "load-more command"), "database"),
            Box(1310, 340, 220, 150, "NotificationsVm", ("NotificationHub", "NotificationVm wrappers", "confirmation messages"), "security"),
            Box(1570, 340, 150, 150, "EditorModeVm", ("DiscriminatorVm", "edit", "preview"), "database"),
            Box(170, 565, 300, 120, "Repository + models", ("NotebookModel / NoteModel", "NoteDraft snapshots", "in-memory persistence"), "cloud"),
            Box(520, 565, 300, 120, "RelayCommand seams", ("save/revert", "delete request", "mode toggle"), "bus"),
            Box(870, 565, 300, 120, "Search and paging state", ("note search term", "global query", "current page/token"), "database"),
            Box(1220, 565, 300, 120, "Message surfaces", ("property changes", "collection reset", "pending notifications"), "security"),
            Box(220, 900, 360, 96, "Ratatui views.rs", ("pure render functions", "read VM getters", "own no domain state"), "generic"),
            Box(730, 900, 360, 96, "app.rs event shell", ("keyboard -> VM command", "smoke mode", "terminal lifecycle"), "generic"),
            Box(1240, 900, 360, 96, "crossterm terminal", ("input events", "alternate screen", "raw mode"), "generic"),
        ),
        lines=(
            Polyline(((780, 268), (238, 340)), color="#22d3ee", label="component1", label_xy=(472, 286)),
            Polyline(((850, 268), (525, 340)), color="#22d3ee", label="component2", label_xy=(640, 302)),
            Polyline(((910, 268), (825, 340)), color="#22d3ee", label="component3", label_xy=(880, 302)),
            Polyline(((975, 268), (1130, 340)), color="#22d3ee", label="component4", label_xy=(1064, 302)),
            Polyline(((1040, 268), (1420, 340)), color="#22d3ee", label="component5", label_xy=(1240, 286)),
            Polyline(((1090, 268), (1645, 340)), color="#22d3ee", label="component6", label_xy=(1390, 270)),
            Polyline(((525, 490), (525, 565), (320, 565)), color="#fbbf24", label="load notes", label_xy=(430, 548)),
            Polyline(((825, 490), (670, 565)), color="#fb923c", label="commands", label_xy=(720, 528)),
            Polyline(((1130, 490), (1020, 565)), color="#a78bfa", label="query/token", label_xy=(1100, 528)),
            Polyline(((1420, 490), (1370, 565)), color="#fb7185", label="post/resolve", label_xy=(1450, 528)),
            Polyline(((400, 685), (400, 900)), color="#64748b", label="snapshots", label_xy=(462, 812)),
            Polyline(((900, 685), (900, 900)), color="#64748b", label="execute", label_xy=(950, 812)),
            Polyline(((1410, 900), (1410, 812), (900, 812), (900, 900)), color="#64748b", label="events", label_xy=(1170, 798)),
        ),
        notes=(
            Note(
                120,
                708,
                1600,
                70,
                "MVVM rule",
                (
                    "The terminal shell may keep focus and quit state only.",
                    "Note data, filtering, paging, validation, notifications, and editor mode live in VMx view models.",
                ),
                "#fb923c",
            ),
        ),
        cards=(
            (
                "VMx-owned state",
                (
                    "The example uses ComponentVm, CompositeVm, FilteredCompositeVm, PagedComposition, FormVm, SearchableState, TokenPagedComposition, NotificationHub, and DiscriminatorVm.",
                    "WorkspaceVm composes the six child surfaces through AggregateVm6.",
                    "Tests target the VM layer before the TUI adapter.",
                ),
            ),
            (
                "Thin terminal adapter",
                (
                    "Ratatui only renders snapshots from view model getters.",
                    "crossterm events are translated into VM commands and methods.",
                    "The smoke path exercises the same VM commands without an interactive terminal.",
                ),
            ),
            (
                "Showcase behavior",
                (
                    "Notebook selection, note filtering, paging, edit validation, save/revert, global token search, delete confirmation, and notifications are all represented.",
                    "The app remains cross-platform and CI-friendly.",
                    "No TUI framework state model competes with VMx.",
                ),
            ),
        ),
    )


def example_app_diagram(
    *,
    diagram_id: str,
    title: str,
    subtitle: str,
    host: tuple[str, tuple[str, ...]],
    adapter: tuple[str, tuple[str, ...]],
    root: tuple[str, tuple[str, ...]],
    primary: tuple[str, tuple[str, ...]],
    support: tuple[str, tuple[str, ...]],
    model: tuple[str, tuple[str, ...]],
    verification: tuple[str, tuple[str, ...]],
    rule: tuple[str, tuple[str, ...]],
    cards: tuple[tuple[str, tuple[str, ...]], ...],
    footer: str,
) -> Diagram:
    return Diagram(
        diagram_id=diagram_id,
        title=title,
        subtitle=subtitle,
        width=1700,
        height=980,
        boundaries=(
            Boundary(70, 118, 1560, 248, "Host and adapter boundary", "#22d3ee"),
            Boundary(70, 396, 1560, 270, "VMx-owned application state", "#34d399"),
            Boundary(70, 696, 1560, 166, "Verification and modeling rule", "#fb923c"),
        ),
        boxes=(
            Box(120, 166, 300, 116, host[0], host[1], "frontend"),
            Box(510, 166, 300, 116, adapter[0], adapter[1], "security"),
            Box(900, 166, 300, 116, "User gestures", ("events become VM calls", "no domain state in host", "render from VM snapshots"), "bus"),
            Box(1290, 166, 260, 116, "Run surface", ("local example command", "smoke-friendly path", "documented README entry"), "cloud"),
            Box(120, 444, 300, 122, root[0], root[1], "frontend"),
            Box(510, 444, 300, 122, primary[0], primary[1], "database"),
            Box(900, 444, 300, 122, support[0], support[1], "bus"),
            Box(1290, 444, 260, 122, model[0], model[1], "backend"),
            Box(250, 738, 350, 90, verification[0], verification[1], "generic"),
            Box(760, 738, 620, 90, rule[0], rule[1], "generic"),
        ),
        lines=(
            Polyline(((420, 224), (510, 224)), color="#22d3ee", label="binds", label_xy=(466, 208)),
            Polyline(((810, 224), (900, 224)), color="#fb923c", label="routes", label_xy=(856, 208)),
            Polyline(((1200, 224), (1290, 224)), color="#fbbf24", label="runs", label_xy=(1246, 208)),
            Polyline(((270, 282), (270, 444)), color="#34d399", label="owns", label_xy=(326, 366)),
            Polyline(((660, 282), (660, 444)), color="#34d399", label="projects", label_xy=(724, 366)),
            Polyline(((1050, 282), (1050, 444)), color="#fb923c", label="executes", label_xy=(1116, 366)),
            Polyline(((1420, 282), (1420, 444)), color="#a78bfa", label="loads", label_xy=(1470, 366)),
            Polyline(((420, 505), (510, 505)), color="#22d3ee", label="children", label_xy=(466, 489)),
            Polyline(((810, 505), (900, 505)), color="#fb923c", label="commands", label_xy=(856, 489)),
            Polyline(((1200, 505), (1290, 505)), color="#34d399", label="data", label_xy=(1246, 489)),
            Polyline(((660, 566), (425, 738)), color="#64748b", label="tests", label_xy=(544, 660)),
            Polyline(((1050, 566), (1070, 738)), color="#64748b", label="boundary", label_xy=(1114, 660)),
        ),
        notes=(
            Note(
                120,
                884,
                1460,
                58,
                "Reading rule",
                (
                    "Follow arrows top to bottom: host input becomes VMx commands; VMx state publishes renderable projections back to the host.",
                ),
                "#22d3ee",
            ),
        ),
        cards=cards,
        footer=footer,
    )


def csharp_console_hello_vmx() -> Diagram:
    return example_app_diagram(
        diagram_id="csharp-console-hello-vmx",
        title="C# Console HelloVMx Example",
        subtitle="minimal .NET host for ComponentVM lifecycle, hub messages, and model equality",
        host=("Console program", ("Program.cs entrypoint", "net8.0 command", "stdout narrative")),
        adapter=("Message subscriptions", ("hub observers", "status/property logs", "no UI framework")),
        root=("ComponentVM<UserModel>", ("builder-created VM", "name + modeled hint", "construct/destruct/dispose")),
        primary=("UserModel projection", ("Alice -> Bob mutation", "equality guard", "modeled hint update")),
        support=("MessageHub", ("ConstructionStatusChanged", "PropertyChanged", "hot message stream")),
        model=("UserModel", ("name", "age", "value equality")),
        verification=("Manual smoke", ("dotnet run", "observable log sequence", "roll-forward note")),
        rule=("Best-fit use", ("Use this when learning the smallest VMx surface before adding host adapters or child containers.",)),
        cards=(
            ("Smallest surface", ("One modeled ComponentVM shows lifecycle and property messages.", "The host never owns domain behavior.")),
            ("Signal path", ("Model mutation publishes through the hub.", "Setting an equal model value stays silent.")),
            ("Next step", ("Move to WPF or Avalonia examples when bindings and child VMs matter.",)),
        ),
        footer="Generated for examples/csharp/console/HelloVMx.",
    )


def csharp_wpf_todo_app() -> Diagram:
    return example_app_diagram(
        diagram_id="csharp-wpf-todo-app",
        title="C# WPF Todo App Example",
        subtitle="Windows WPF host showing VMx commands with idiomatic XAML binding wrappers",
        host=("WPF window", ("MainWindow.xaml", "ListBox + buttons", "Windows-only launch")),
        adapter=("INPC wrappers", ("TodoItemVM forwards VMx", "ICommand bridge", "XAML data binding")),
        root=("MainWindowViewModel", ("ObservableCollection rows", "AddCommand", "selected item context")),
        primary=("TodoItemVM rows", ("ComponentVM<TodoItem>", "Title / Done projection", "ToggleDoneCommand")),
        support=("RelayCommand", ("add item", "toggle item", "CanExecute binding")),
        model=("TodoItem", ("title", "done flag", "simple value model")),
        verification=("Build + launch", ("dotnet build", "dotnet run on Windows", "cross-platform restore")),
        rule=("Best-fit use", ("Use this for wrapper-style integration where the UI toolkit expects INPC and ICommand surfaces.",)),
        cards=(
            ("Wrapper pattern", ("VMx stays inside row wrappers.", "WPF sees familiar binding contracts.")),
            ("Command ownership", ("Add and toggle behavior route through RelayCommand.", "The view only binds commands.")),
            ("Platform note", ("Build can succeed off Windows.", "Running WPF still requires Windows.")),
        ),
        footer="Generated for examples/csharp/wpf/TodoApp.",
    )


def csharp_avalonia_notes_showcase() -> Diagram:
    return example_app_diagram(
        diagram_id="csharp-avalonia-notes-showcase",
        title="C# Avalonia Notes Showcase Example",
        subtitle="flagship XAML host with AggregateVM6, FormVM, paging, dialogs, theme, and notifications",
        host=("Avalonia views", ("AXAML-only screens", "InitializeComponent code-behind", "cross-platform desktop")),
        adapter=("Avalonia adapters", ("BindableVm / Derived", "collection + command bridges", "dispatcher + dialogs")),
        root=("WorkspaceVM", ("AggregateVM6 shell", "async construct", "theme sibling")),
        primary=("Notebook + note VMs", ("tree projection", "paged notes list", "strict NoteFormVM")),
        support=("Workflow services", ("dialogs", "notifications", "global token search")),
        model=("Repository + models", ("in-memory notes", "seed notebooks", "theme model")),
        verification=("Pure-VM tests", ("dotnet test", "adapter tests", "code-behind checker")),
        rule=("Best-fit use", ("Use this as the C# reference for full VMx desktop composition with thin Avalonia views.",)),
        cards=(
            ("Full surface", ("Exercises the 19-row Notes Workspace contract.", "Uses specialized VMs where they reduce host glue.")),
            ("Adapter seam", ("Avalonia specifics live in Views/Adapter.", "VMs remain host-independent.")),
            ("Parity role", ("Matches Python Textual, TypeScript React, and SwiftUI flagship behavior.",)),
        ),
        footer="Generated for examples/csharp/avalonia/NotesShowcase.",
    )


def python_console_hello_vmx() -> Diagram:
    return example_app_diagram(
        diagram_id="python-console-hello-vmx",
        title="Python Console hello_vmx Example",
        subtitle="minimal uv-run script for ComponentVMOf lifecycle and reactivex-backed hub messages",
        host=("Python module", ("python -m hello_vmx", "uv-managed env", "stdout narrative")),
        adapter=("Reactive observers", ("hub.messages subscribe", "status/property printout", "no UI toolkit")),
        root=("ComponentVMOf[UserModel]", ("fluent builder", "name + hint", "construct/destruct/dispose")),
        primary=("UserModel projection", ("dataclass-like model", "Alice -> Bob mutation", "equality guard")),
        support=("MessageHub", ("ConstructionStatusChanged", "PropertyChanged", "reactivex stream")),
        model=("UserModel", ("name", "age", "typed payload")),
        verification=("Manual smoke", ("uv sync", "uv run python -m hello_vmx", "expected log trace")),
        rule=("Best-fit use", ("Use this as the shortest Python path before adding tkinter, Textual, or child containers.",)),
        cards=(
            ("Smallest Python path", ("One modeled VM demonstrates lifecycle and hub semantics.", "No view adapter is required.")),
            ("Signal path", ("Model changes publish property messages.", "Equal assignments are intentionally quiet.")),
            ("Next step", ("Move to tkinter Todo for CompositeVM or Textual Inspector for tree traversal.",)),
        ),
        footer="Generated for examples/python/console/hello_vmx.",
    )


def python_tk_todo_app() -> Diagram:
    return example_app_diagram(
        diagram_id="python-tk-todo-app",
        title="Python tkinter Todo App Example",
        subtitle="small GUI host using CompositeVM rows and RelayCommand-driven todo actions",
        host=("tkinter window", ("entry + listbox", "button callbacks", "display required")),
        adapter=("View callbacks", ("button -> command", "selection -> VM", "render from VM list")),
        root=("MainWindowViewModel", ("CompositeVM[TodoItemVM]", "add_command", "remove_command")),
        primary=("TodoItemVM rows", ("ComponentVMOf[TodoItem]", "toggle_done command", "row projection")),
        support=("RelayCommand", ("add", "remove", "toggle complete")),
        model=("TodoItem", ("title", "done flag", "simple payload")),
        verification=("Import + run", ("headless import check", "uv run python -m todo_app", "display-gated UI")),
        rule=("Best-fit use", ("Use this when a small Python UI needs VMx collection ownership without a heavier TUI stack.",)),
        cards=(
            ("Composite fit", ("Todo rows are homogeneous and selectable.", "CompositeVM is a better fit than manual list state.")),
            ("Thin host", ("tkinter callbacks translate gestures to commands.", "The VM owns collection mutations.")),
            ("Contrast", ("The C# WPF Todo app uses wrappers for toolkit idiom.", "Both preserve VMx command ownership.")),
        ),
        footer="Generated for examples/python/tk/todo_app.",
    )


def python_textual_inspector() -> Diagram:
    return example_app_diagram(
        diagram_id="python-textual-inspector",
        title="Python Textual Inspector Example",
        subtitle="live TUI for walking VMx hierarchies and observing hub message traffic",
        host=("Textual app", ("tree widget", "details panel", "message table")),
        adapter=("Inspector views", ("vmx.tree.walk", "highlighted node actions", "hub log sink")),
        root=("Sample hierarchy", ("ComponentVM nodes", "constructable tree", "selected node context")),
        primary=("Tree projection", ("walk output", "node metadata", "details view")),
        support=("Lifecycle actions", ("construct", "destruct", "reconstruct", "dispose / select")),
        model=("Hub stream", ("PropertyChanged", "ConstructionStatusChanged", "ordered log rows")),
        verification=("Smoke test", ("uv run project", "Textual import smoke", "sample hierarchy renders")),
        rule=("Best-fit use", ("Use this to inspect VMx runtime behavior before wiring a domain-specific application host.",)),
        cards=(
            ("Observability", ("The app makes lifecycle and property messages visible.", "It is intentionally general-purpose.")),
            ("Tree utilities", ("vmx.tree.walk drives the visual hierarchy.", "Highlighted nodes route lifecycle commands.")),
            ("Learning role", ("Best for understanding state flow and hub traffic.",)),
        ),
        footer="Generated for examples/python/textual/inspector.",
    )


def python_textual_notes_showcase() -> Diagram:
    return example_app_diagram(
        diagram_id="python-textual-notes-showcase",
        title="Python Textual Notes Showcase Example",
        subtitle="flagship terminal host with pure VMx state, Textual rendering, dialogs, search, and paging",
        host=("Textual screens", ("compose/on_mount views", "single-statement actions", "keyboard bindings")),
        adapter=("Textual adapters", ("property binders", "collection bridge", "dialog + dispatcher ports")),
        root=("WorkspaceVM", ("AggregateVM6 shell", "async construct", "theme sibling")),
        primary=("Notebook + note VMs", ("tree projection", "PagedComposition", "strict NoteFormVM")),
        support=("Workflow services", ("TokenPagedComposition", "NotificationVM", "DiscriminatorVM")),
        model=("Repository + models", ("in-memory notes", "seed notebooks", "theme model")),
        verification=("VM + view tests", ("uv run pytest", "Pure-VM contract", "adapter smoke tests")),
        rule=("Best-fit use", ("Use this as the Python reference for full VMx MVVM in a terminal UI.",)),
        cards=(
            ("Full surface", ("Exercises the same 19-row Notes Workspace contract.", "Textual owns rendering, not state.")),
            ("Adapter seam", ("View classes stay thin and route to VM commands.", "VM tests cover the domain behavior.")),
            ("Parity role", ("Matches the C#, TypeScript, and Swift flagship scenario.",)),
        ),
        footer="Generated for examples/python/textual/notes_showcase.",
    )


def typescript_console_hello_vmx() -> Diagram:
    return example_app_diagram(
        diagram_id="typescript-console-hello-vmx",
        title="TypeScript Console hello-vmx Example",
        subtitle="minimal Node script for ComponentVMOf lifecycle and rxjs-backed message observation",
        host=("Node script", ("tsx entrypoint", "npm start", "stdout narrative")),
        adapter=("rxjs subscriptions", ("hub.messages subscribe", "status/property logs", "no DOM host")),
        root=("ComponentVMOf<UserModel>", ("fluent builder", "name + hint", "construct/destruct/dispose")),
        primary=("UserModel projection", ("typed object model", "Alice -> Bob mutation", "equality guard")),
        support=("MessageHub", ("ConstructionStatusChanged", "PropertyChanged", "rxjs stream")),
        model=("UserModel", ("name", "age", "structural payload")),
        verification=("Manual smoke", ("npm ci", "npm start", "local VMx build first")),
        rule=("Best-fit use", ("Use this as the shortest TypeScript path before adding React adapters or child containers.",)),
        cards=(
            ("Smallest TS path", ("One modeled VM demonstrates lifecycle and hub semantics.", "The script stays framework-free.")),
            ("Signal path", ("Model updates publish property messages.", "Equal assignments produce no message.")),
            ("Next step", ("Move to the React showcase when host hooks and adapters matter.",)),
        ),
        footer="Generated for examples/typescript/console/hello-vmx.",
    )


def typescript_react_notes_showcase() -> Diagram:
    return example_app_diagram(
        diagram_id="typescript-react-notes-showcase",
        title="TypeScript React Notes Showcase Example",
        subtitle="flagship web host with hooks as VMx adapters and React components as pure renderers",
        host=("React components", ("Vite app shell", "pure render components", "hotkey hooks")),
        adapter=("React adapter hooks", ("useVm / useCommand", "collection + derived hooks", "dialog overlay")),
        root=("WorkspaceVM", ("AggregateVM6 shell", "async construct", "theme sibling")),
        primary=("Notebook + note VMs", ("tree projection", "PagedComposition", "strict NoteFormVM")),
        support=("Workflow services", ("TokenPagedComposition", "NotificationVM", "DiscriminatorVM")),
        model=("Repository + models", ("in-memory notes", "seed notebooks", "theme model")),
        verification=("Vitest + lint", ("npm test", "typecheck", "no useState/useReducer in views")),
        rule=("Best-fit use", ("Use this as the TypeScript reference for full VMx MVVM in a browser host.",)),
        cards=(
            ("Hook seam", ("Hooks adapt VMx streams to React rendering.", "Components do not own domain state.")),
            ("Full surface", ("Exercises the 19-row Notes Workspace contract.", "Specialized VMs keep wrapper code small.")),
            ("Parity role", ("Matches the C#, Python, and Swift flagship scenario.",)),
        ),
        footer="Generated for examples/typescript/react/notes-showcase.",
    )


def swift_notes_showcase() -> Diagram:
    return example_app_diagram(
        diagram_id="swift-notes-showcase",
        title="Swift Notes Showcase Example",
        subtitle="SwiftUI + Combine flagship with a pure NotesShowcaseCore VM layer",
        host=("SwiftUI views", ("RootView layout", "Combine subscriptions", "macOS app target")),
        adapter=("SwiftUI adapters", ("BindableVM", "BindableCollection", "command + derived bridges")),
        root=("WorkspaceVM", ("AggregateVM6 shell", "async construct", "theme sibling")),
        primary=("Notebook + note VMs", ("tree projection", "paged notes", "strict NoteFormVM")),
        support=("Workflow services", ("global token search", "notifications", "dialogs + theme")),
        model=("Core package", ("models", "repository", "ThemeChangedMessage")),
        verification=("Swift tests", ("swift build", "swift test with Xcode", "THEME-001..005")),
        rule=("Best-fit use", ("Use this as the Swift reference for keeping SwiftUI views bound to VMx-owned state.",)),
        cards=(
            ("Target split", ("NotesShowcaseCore owns models and VMs.", "NotesShowcase owns SwiftUI adapters and views.")),
            ("Combine bridge", ("Adapters expose VMx state to SwiftUI.", "Commands remain VM-owned.")),
            ("Parity role", ("Matches the C#, Python, and TypeScript flagship scenario.",)),
        ),
        footer="Generated for examples/swift/notes-showcase.",
    )


def rust_console_hello_vmx() -> Diagram:
    return example_app_diagram(
        diagram_id="rust-console-hello-vmx",
        title="Rust Console hello-vmx Example",
        subtitle="Cargo console demo using ComponentVm, CompositeVm, FilteredCompositeVm, and RelayCommand",
        host=("Cargo binary", ("src/main.rs", "cargo run", "stdout summary")),
        adapter=("Console projection", ("print current note", "print search count", "no TUI state")),
        root=("CompositeVm rows", ("modeled note rows", "initial current", "construct + dispose")),
        primary=("FilteredCompositeVm", ("live search result", "rust query", "selected note remains VM-owned")),
        support=("RelayCommand", ("command execution", "VMx services", "hub + dispatcher")),
        model=("Note models", ("3 seeded notes", "slug/title/body", "search text")),
        verification=("Manual smoke", ("cargo run", "expected four-line output", "builds local vmx crate")),
        rule=("Best-fit use", ("Use this as the Rust stepping stone from modeled rows to filtered collections before the Ratatui showcase.",)),
        cards=(
            ("Rust primitives", ("The example shows the Rust flavor beyond a single leaf VM.", "Composite and filtered projections stay VMx-owned.")),
            ("Command path", ("RelayCommand demonstrates executable VM behavior.", "Console output is only a projection.")),
            ("Next step", ("Move to Ratatui Notes Showcase for full MVVM terminal composition.",)),
        ),
        footer="Generated for examples/rust/console/hello-vmx.",
    )


def build_diagrams() -> dict[str, Diagram]:
    return {
        "system-architecture": system_architecture(),
        "class-architecture": class_architecture(),
        "viewmodel-families": viewmodel_families(),
        "lifecycle-messaging": lifecycle_messaging(),
        "component-family": component_family(),
        "aggregate-family": aggregate_family(),
        "group-family": group_family(),
        "composite-family": composite_family(),
        "hierarchical-family": hierarchical_family(),
        "forwarding-wrapper-family": forwarding_wrapper_family(),
        "specialized-vm-family": specialized_vm_family(),
        "commands-capabilities": commands_capabilities(),
        "forms-dialogs-notifications": forms_dialogs_notifications(),
        "examples-vm-layer": examples_vm_layer(),
        "csharp-console-hello-vmx": csharp_console_hello_vmx(),
        "csharp-wpf-todo-app": csharp_wpf_todo_app(),
        "csharp-avalonia-notes-showcase": csharp_avalonia_notes_showcase(),
        "python-console-hello-vmx": python_console_hello_vmx(),
        "python-tk-todo-app": python_tk_todo_app(),
        "python-textual-inspector": python_textual_inspector(),
        "python-textual-notes-showcase": python_textual_notes_showcase(),
        "typescript-console-hello-vmx": typescript_console_hello_vmx(),
        "typescript-react-notes-showcase": typescript_react_notes_showcase(),
        "swift-notes-showcase": swift_notes_showcase(),
        "rust-console-hello-vmx": rust_console_hello_vmx(),
        "rust-tui-notes-showcase": rust_tui_notes_showcase(),
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
