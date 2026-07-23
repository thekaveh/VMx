from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

from scripts.docs import build_docs
from scripts.docs.links import find_html_link_attributes, find_links, is_forbidden
from scripts.docs.manifest import load_manifest

PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|FIXME)\b")
# CommonMark backslash-escapes any ASCII punctuation; mdformat forces `C#` at the
# end of an ATX heading to `C\#` (a trailing `#` would otherwise read as a closing
# sequence). Unescape before comparing an H1 to its manifest label so the label can
# stay clean (`C#`) on every rendered surface while the on-disk heading keeps the
# escape mdformat requires.
MD_ESCAPE_RE = re.compile(r"\\([!-/:-@\[-`{-~])")
ATX_HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$")
NUMBER_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)(\.)?\s+")
HTML_HEADING_RE = re.compile(r"<\s*h[1-6](?:\s|>)", re.IGNORECASE)
ANY_ATX_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
HTML_ID_RE = re.compile(r'<(?:a|h[1-6])\b[^>]*\bid=["\']([^"\']+)["\']', re.IGNORECASE)
WIKI_LINK_RE = re.compile(r"\[\[(?P<label>[^\]\r\n]+)\|(?P<target>[^\]\r\n]+)\]\]")
DECORATIVE_STATUS_ICON_RE = re.compile(r"[✓✔✅❌✗✘]")
HISTORICAL_AUDIT_NOTICE = (
    "> Historical audit record. This document captures a point-in-time review and may "
    "contain superseded paths, versions, findings, or conclusions. For current behavior, "
    "use the specification and current documentation."
)

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
            targets = [link.target for link in find_links(text)]
            targets.extend(attribute.target for attribute in find_html_link_attributes(text))
            for target in targets:
                if is_forbidden(target, surface):
                    findings.append(Finding("error", f"{path}: forbidden {surface} link {target}"))
    for path in _scan_repo_surface_markdown(repo_root):
        text = path.read_text(encoding="utf-8")
        targets = [link.target for link in find_links(text)]
        targets.extend(attribute.target for attribute in find_html_link_attributes(text))
        for target in targets:
            if is_forbidden(target, "repo"):
                findings.append(
                    Finding(
                        "error",
                        f"{path.relative_to(repo_root)}: forbidden repo-surface link {target}",
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
    return False


def _relative_target_path(source: Path, target: str) -> Path | None:
    clean = target.split("#", 1)[0].split("?", 1)[0]
    if clean.startswith(("http://", "https://", "mailto:")):
        return None
    if not clean:
        return source
    candidate = (source.parent / clean).resolve()
    if candidate.is_file():
        return candidate
    return None


def _github_heading_slug(title: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]+>", "", title))
    plain = re.sub(r"[`*_~]", "", plain).strip().lower()
    plain = re.sub(r"[^\w\- ]", "", plain)
    return re.sub(r"\s+", "-", plain)


def _heading_anchors(path: Path) -> set[str]:
    text = _without_fenced_code(path.read_text(encoding="utf-8"))
    anchors = set(HTML_ID_RE.findall(text))
    occurrences: dict[str, int] = {}
    for match in ANY_ATX_HEADING_RE.finditer(text):
        base = _github_heading_slug(match.group(1).rstrip("#").rstrip())
        count = occurrences.get(base, 0)
        occurrences[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


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
        targets.extend(attribute.target for attribute in find_html_link_attributes(text))
        for target in targets:
            if not _relative_target_exists(path, target):
                findings.append(
                    Finding(
                        "error",
                        f"{path.relative_to(repo_root)}: target does not exist: {target}",
                    )
                )
                continue
            if "#" not in target or target.startswith(("http://", "https://", "mailto:")):
                continue
            fragment = unquote(target.split("#", 1)[1].split("?", 1)[0])
            target_path = _relative_target_path(path, target)
            if (
                fragment
                and target_path is not None
                and fragment not in _heading_anchors(target_path)
            ):
                findings.append(
                    Finding(
                        "error",
                        f"{path.relative_to(repo_root)}: heading fragment does not exist: {target}",
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
    return findings


def _site_base_path(repo_root: Path) -> str:
    config = repo_root / "mkdocs.yml"
    if not config.is_file():
        return ""
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    site_url = data.get("site_url", "")
    return urlparse(site_url).path.rstrip("/") if isinstance(site_url, str) else ""


def _generated_site_target(
    source: Path,
    root: Path,
    target: str,
    site_base_path: str,
) -> Path | None:
    clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if any(ord(character) < 32 or ord(character) == 127 for character in clean):
        return None
    base = source.parent if source.name == "index.md" else source.with_suffix("")
    if not clean:
        return source
    if clean.startswith("/"):
        if site_base_path:
            if clean != site_base_path and not clean.startswith(f"{site_base_path}/"):
                return None
            clean = clean.removeprefix(site_base_path).lstrip("/")
            if not clean:
                index = root / "index.md"
                return index if index.is_file() else None
        else:
            clean = clean.lstrip("/")
        try:
            route = (root / clean).resolve()
        except (OSError, ValueError):
            return None
    else:
        try:
            route = (base / clean).resolve()
        except (OSError, ValueError):
            return None
    try:
        route.relative_to(root.resolve())
    except ValueError:
        return None
    if route.is_file():
        return route
    if clean.endswith("/"):
        page = route.with_suffix(".md")
        if page.is_file():
            return page
        index = route / "index.md"
        if index.is_file():
            return index
    return None


def _generated_wiki_target(source: Path, root: Path, target: str) -> Path | None:
    clean = target.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if not clean:
        return source
    if Path(clean).is_absolute():
        return None
    resolved_root = root.resolve()
    try:
        candidate = (source.parent / clean).resolve()
        candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    if candidate.is_file():
        return candidate
    try:
        page = (root / f"{clean}.md").resolve()
        page.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return page if page.is_file() else None


def check_generated_html_links(repo_root: Path) -> list[Finding]:
    """Reject broken raw-HTML routes and fragments on generated surfaces."""
    findings: list[Finding] = []
    site_base_path = _site_base_path(repo_root)
    for surface, root in (
        ("site", repo_root / "generated/site"),
        ("wiki", repo_root / "generated/wiki"),
    ):
        for path in _scan_markdown(root):
            text = _without_fenced_code(path.read_text(encoding="utf-8"))
            for attribute in find_html_link_attributes(text):
                target = html.unescape(attribute.target)
                if target.startswith(("http://", "https://", "mailto:", "data:")):
                    continue
                target_path = (
                    _generated_site_target(path, root, target, site_base_path)
                    if surface == "site"
                    else _generated_wiki_target(path, root, target)
                )
                if target_path is None:
                    findings.append(
                        Finding(
                            "error",
                            f"{path}: {surface} target does not exist: {target}",
                        )
                    )
                    continue
                if "#" not in target or target_path.suffix != ".md":
                    continue
                fragment = unquote(target.split("#", 1)[1].split("?", 1)[0])
                if fragment and fragment not in _heading_anchors(target_path):
                    findings.append(
                        Finding(
                            "error",
                            f"{path}: {surface} heading fragment does not exist: {target}",
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


def check_historical_audits(repo_root: Path) -> list[Finding]:
    """Keep point-in-time audit reports visibly archival and discoverable."""
    audit_root = repo_root / "docs/audit"
    index = audit_root / "README.md"
    reports = sorted(path for path in _scan_markdown(audit_root) if path != index)
    findings: list[Finding] = []
    if reports and not index.is_file():
        findings.append(Finding("error", "docs/audit/README.md: historical audit index is missing"))
        index_text = ""
    else:
        index_text = index.read_text(encoding="utf-8") if index.is_file() else ""

    for path in reports:
        relative = path.relative_to(repo_root)
        text = path.read_text(encoding="utf-8")
        if HISTORICAL_AUDIT_NOTICE not in "\n".join(text.splitlines()[:12]):
            findings.append(
                Finding(
                    "error",
                    f"{relative}: standardized historical audit notice is missing",
                )
            )
        if f"({path.name})" not in index_text:
            findings.append(
                Finding("error", f"{relative}: report is not listed in docs/audit/README.md")
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
        first_line = MD_ESCAPE_RE.sub(r"\1", text.splitlines()[0].strip())
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
    findings.extend(check_generated_html_links(repo_root))
    findings.extend(check_raw_html_headings(repo_root))
    findings.extend(check_professional_markdown(repo_root))
    findings.extend(check_historical_audits(repo_root))
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
