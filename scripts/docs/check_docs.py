from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.docs import build_docs
from scripts.docs.links import find_links, is_forbidden
from scripts.docs.manifest import load_manifest

PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|FIXME)\b")


@dataclass(frozen=True)
class Finding:
    severity: str
    message: str


def _scan_markdown(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file())


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
                    findings.append(Finding("error", f"{path}: forbidden {surface} link {link.target}"))
    readme = repo_root / "README.md"
    if readme.exists():
        for link in find_links(readme.read_text(encoding="utf-8")):
            if is_forbidden(link.target, "repo"):
                findings.append(Finding("error", f"README.md: forbidden repo-surface link {link.target}"))
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
    return [Finding("error", f"{path}: content file is not listed in docs/manifest.yaml") for path in missing]


def check_heading_numbers(repo_root: Path) -> list[Finding]:
    manifest = load_manifest(repo_root / "docs/manifest.yaml", repo_root)
    findings: list[Finding] = []
    for section in manifest.pages():
        assert section.source is not None
        path = repo_root / section.source
        first_line = path.read_text(encoding="utf-8").splitlines()[0].strip()
        expected = f"# {section.label}"
        if first_line != expected:
            findings.append(Finding("error", f"{section.source}: expected H1 {expected!r}, found {first_line!r}"))
    return findings


def check_placeholders(repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for root in (repo_root / "docs/content", repo_root / "generated/site", repo_root / "generated/wiki"):
        for path in _scan_markdown(root):
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if PLACEHOLDER_RE.search(line):
                    findings.append(Finding("error", f"{path}:{line_number}: placeholder text leaked"))
    return findings


def check(repo_root: Path) -> list[Finding]:
    build_docs.build(site=True, wiki=True, check=True, repo_root=repo_root)
    findings: list[Finding] = []
    findings.extend(check_self_containment(repo_root))
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
