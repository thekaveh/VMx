from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.docs import build_docs
from scripts.docs.links import find_links, is_forbidden
from scripts.docs.manifest import load_manifest

PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|FIXME)\b")
ATX_HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$")
NUMBER_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)(\.)?\s+")
HTML_HREF_RE = re.compile(r'href="(?P<target>[^"]+)"')
HTML_HEADING_RE = re.compile(r"<\s*h[1-6](?:\s|>)", re.IGNORECASE)
WIKI_LINK_RE = re.compile(r"\[\[(?P<label>[^\]\r\n]+)\|(?P<target>[^\]\r\n]+)\]\]")
DECORATIVE_STATUS_ICON_RE = re.compile(r"[✓✔✅❌✗✘]")

STANDALONE_NUMBERED_DOCS = (
    Path("langs/rust/README.md"),
    Path("examples/DIAGRAMS.md"),
)


@dataclass(frozen=True)
class Finding:
    severity: str
    message: str


def _scan_markdown(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def _scan_repo_surface_markdown(repo_root: Path) -> list[Path]:
    files = [
        repo_root / name
        for name in (
            "README.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CODE_OF_CONDUCT.md",
            "compatibility-matrix.md",
        )
        if (repo_root / name).is_file()
    ]
    excluded_parts = {
        ".build",
        ".venv",
        "_build",
        "audit",
        "bin",
        "generated",
        "node_modules",
        "obj",
        "superpowers",
        "target",
    }
    for root_name in ("docs/content", "docs/maintenance", "examples", "langs", "tools"):
        for path in _scan_markdown(repo_root / root_name):
            if excluded_parts.intersection(path.relative_to(repo_root).parts):
                continue
            files.append(path)
    return sorted(set(files))


def check_self_containment(repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for surface, root in (
        ("site", repo_root / "generated/site"),
        ("wiki", repo_root / "generated/wiki"),
    ):
        for path in _scan_markdown(root):
            text = path.read_text(encoding="utf-8")
            for link in find_links(text):
                if is_forbidden(link.target, surface):
                    findings.append(
                        Finding("error", f"{path}: forbidden {surface} link {link.target}")
                    )
    for path in _scan_repo_surface_markdown(repo_root):
        for link in find_links(path.read_text(encoding="utf-8")):
            if is_forbidden(link.target, "repo"):
                findings.append(
                    Finding(
                        "error",
                        f"{path.relative_to(repo_root)}: forbidden repo-surface link {link.target}",
                    )
                )
    return findings


def _relative_target_exists(source: Path, target: str) -> bool:
    clean = target.split("#", 1)[0].split("?", 1)[0]
    if not clean or clean.startswith(("#", "http://", "https://", "mailto:")):
        return True
    candidate = (source.parent / clean).resolve()
    if candidate.exists():
        return True
    if clean.endswith("/"):
        sibling_page = (source.parent / f"{clean.rstrip('/')}.md").resolve()
        return sibling_page.exists()
    return False


def _without_fenced_code(markdown: str) -> str:
    output: list[str] = []
    fence: str | None = None
    for line in markdown.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            output.append("\n")
        elif fence is None:
            output.append(line)
        else:
            output.append("\n")
    return "".join(output)


def check_canonical_links(repo_root: Path) -> list[Finding]:
    """Reject relative canonical-doc links whose repository target is absent."""
    findings: list[Finding] = []
    for path in _scan_markdown(repo_root / "docs/content"):
        text = _without_fenced_code(path.read_text(encoding="utf-8"))
        targets = [link.target for link in find_links(text)]
        targets.extend(match.group("target") for match in HTML_HREF_RE.finditer(text))
        for target in targets:
            if not _relative_target_exists(path, target):
                findings.append(
                    Finding(
                        "error",
                        f"{path.relative_to(repo_root)}: target does not exist: {target}",
                    )
                )
    return findings


def check_generated_wiki_links(repo_root: Path) -> list[Finding]:
    """Reject malformed wiki links and links to absent generated pages."""
    wiki_root = repo_root / "generated/wiki"
    pages = {path.stem for path in wiki_root.glob("*.md")}
    findings: list[Finding] = []
    for path in _scan_markdown(wiki_root):
        text = _without_fenced_code(path.read_text(encoding="utf-8"))
        for line_number, line in enumerate(text.splitlines(), start=1):
            scrubbed = WIKI_LINK_RE.sub("", line)
            if ("[[" in scrubbed or "]]" in scrubbed) and "|" in scrubbed:
                findings.append(Finding("error", f"{path}:{line_number}: malformed wiki link"))
            for match in WIKI_LINK_RE.finditer(line):
                target = match.group("target").split("#", 1)[0]
                if target and target not in pages:
                    findings.append(
                        Finding(
                            "error",
                            f"{path}:{line_number}: wiki target does not exist: {target}",
                        )
                    )
            for match in HTML_HREF_RE.finditer(line):
                target = match.group("target").split("#", 1)[0].rstrip("/")
                if target and not target.startswith(("http://", "https://", "mailto:")):
                    target_exists = (
                        (path.parent / target).resolve().is_file()
                        if "/" in target or "." in Path(target).name
                        else target in pages
                    )
                    if not target_exists:
                        findings.append(
                            Finding(
                                "error",
                                f"{path}:{line_number}: wiki target does not exist: {target}",
                            )
                        )
    return findings


def check_raw_html_headings(repo_root: Path) -> list[Finding]:
    """Keep heading hierarchy in Markdown where numbering can be validated."""
    findings: list[Finding] = []
    for path in _scan_markdown(repo_root / "docs/content"):
        text = _without_fenced_code(path.read_text(encoding="utf-8"))
        for line_number, line in enumerate(text.splitlines(), start=1):
            if HTML_HEADING_RE.search(line):
                findings.append(
                    Finding(
                        "error",
                        f"{path.relative_to(repo_root)}:{line_number}: "
                        "raw HTML heading bypasses hierarchy checks",
                    )
                )
    return findings


def check_professional_markdown(repo_root: Path) -> list[Finding]:
    """Reject decorative pass/fail glyphs in maintained public Markdown."""
    findings: list[Finding] = []
    for path in _scan_repo_surface_markdown(repo_root):
        text = _without_fenced_code(path.read_text(encoding="utf-8"))
        for line_number, line in enumerate(text.splitlines(), start=1):
            if DECORATIVE_STATUS_ICON_RE.search(line):
                findings.append(
                    Finding(
                        "error",
                        f"{path.relative_to(repo_root)}:{line_number}: "
                        "decorative status icon in public documentation",
                    )
                )
    return findings


def check_completeness(repo_root: Path) -> list[Finding]:
    manifest = load_manifest(repo_root / "docs/manifest.yaml", repo_root)
    manifest_sources = {section.source for section in manifest.pages()}
    content_sources = {
        path.relative_to(repo_root)
        for path in (repo_root / "docs/content").rglob("*.md")
        if "stylesheets" not in path.parts
    }
    missing = sorted(content_sources - manifest_sources)
    return [
        Finding("error", f"{path}: content file is not listed in docs/manifest.yaml")
        for path in missing
    ]


def check_heading_numbers(repo_root: Path) -> list[Finding]:
    manifest = load_manifest(repo_root / "docs/manifest.yaml", repo_root)
    findings: list[Finding] = []
    for section in manifest.pages():
        assert section.source is not None
        path = repo_root / section.source
        text = path.read_text(encoding="utf-8")
        first_line = text.splitlines()[0].strip()
        expected = f"# {section.label}"
        if first_line != expected:
            findings.append(
                Finding(
                    "error",
                    f"{section.source}: expected H1 {expected!r}, found {first_line!r}",
                )
            )
        findings.extend(_check_descendant_heading_numbers(text, section.number, section.source))
    for relative_path in STANDALONE_NUMBERED_DOCS:
        path = repo_root / relative_path
        findings.extend(
            _check_descendant_heading_numbers(path.read_text(encoding="utf-8"), None, relative_path)
        )
    return findings


def _check_descendant_heading_numbers(
    markdown: str, page_number: str | None, path: Path
) -> list[Finding]:
    """Validate baked H2-H6 numbering while ignoring fenced examples."""
    findings: list[Finding] = []
    counters = [0, 0, 0, 0, 0]
    fence: str | None = None

    for line_number, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is not None:
            continue

        match = ATX_HEADING_RE.match(line)
        if match is None:
            continue
        level = len(match.group(1))
        depth = level - 2
        if depth > 0 and counters[depth - 1] == 0:
            findings.append(
                Finding(
                    "error",
                    f"{path}:{line_number}: H{level} skips its H{level - 1} parent",
                )
            )
            continue

        counters[depth] += 1
        for index in range(depth + 1, len(counters)):
            counters[index] = 0
        page_prefix = f"{page_number}." if page_number else ""
        expected_number = (
            page_prefix + ".".join(str(value) for value in counters[: depth + 1]) + "."
        )
        title = match.group(2)
        actual = NUMBER_PREFIX_RE.match(title)
        if (
            actual is None
            or actual.group(1) != expected_number.removesuffix(".")
            or actual.group(2) != "."
        ):
            findings.append(
                Finding(
                    "error",
                    f"{path}:{line_number}: expected heading number {expected_number!r}",
                )
            )

    return findings


def check_placeholders(repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for root in (
        repo_root / "docs/content",
        repo_root / "generated/site",
        repo_root / "generated/wiki",
    ):
        for path in _scan_markdown(root):
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if PLACEHOLDER_RE.search(line):
                    findings.append(
                        Finding("error", f"{path}:{line_number}: placeholder text leaked")
                    )
    return findings


def check(repo_root: Path) -> list[Finding]:
    build_docs.build(site=True, wiki=True, check=True, repo_root=repo_root)
    findings: list[Finding] = []
    findings.extend(check_self_containment(repo_root))
    findings.extend(check_canonical_links(repo_root))
    findings.extend(check_generated_wiki_links(repo_root))
    findings.extend(check_raw_html_headings(repo_root))
    findings.extend(check_professional_markdown(repo_root))
    findings.extend(check_completeness(repo_root))
    findings.extend(check_heading_numbers(repo_root))
    findings.extend(check_placeholders(repo_root))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    findings = check(Path(args.root).resolve())
    for finding in findings:
        print(f"{finding.severity.upper()}: {finding.message}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
