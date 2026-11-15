"""ADR spec-version labels and HISTORY sections follow the spec tags (#1809).

A spec tag ``spec-vX.Y.Z`` freezes a spec release. An ADR whose ``Spec version``
label names a tag must name the first tag whose tree contains the ADR file,
because that tag is the release that carries the decision (ADR-0230). A label
that names a version with no tag is outside that rule. ADRs with no containing
tag yet are owner items. The registry cell must repeat the label, and
``spec/HISTORY.md`` must cite each ADR in the section of its label's version.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "spec" / "ADRs"
REGISTRY = ADR_DIR / "README.md"
HISTORY = ROOT / "spec" / "HISTORY.md"

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
_LABEL_RE = re.compile(r"^(?:- )?\*\*Spec version:\*\*\s*(.*)$")
_REGISTRY_ROW_RE = re.compile(r"^\| \[(\d{4})\]\(([^)]+)\)\s*\|")
_HISTORY_HEADING_RE = re.compile(r"^## (\d+)\. ([^\n]*)")
_ADR_CITE_RE = re.compile(r"ADR-(\d{4})(?:\s+(?:through|to)\s+ADR-(\d{4}))?")

# Issue #1809 covers HISTORY sections 1 to 38, which span the tagged releases
# from spec-v2.1.0 to spec-v3.29.0. Section 39 (3.30.0) belongs to #1478.
FIRST_HISTORY_TAG = "2.1.0"  # HISTORY §1 is the v2.1.0 release
FIRST_CHECKED = "2.2.0"  # ADR placement, as issue #1809 states it
LAST_CHECKED = "3.29.0"


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
    ).stdout


def spec_tags() -> dict[str, str]:
    """Return ``{version: tag name}`` for every ``spec-vX.Y.Z`` tag."""
    tags = {name.removeprefix("spec-v"): name for name in _git("tag", "-l", "spec-v*").split()}
    assert tags, "no spec-v tags are visible; run `git fetch --tags`"
    return tags


def first_tag_by_adr(tags: dict[str, str]) -> dict[str, str]:
    """Return ``{ADR file name: first tag version whose tree contains it}``."""
    first: dict[str, str] = {}
    for version in sorted(tags, key=_key):
        listing = _git("ls-tree", "--name-only", tags[version], "spec/ADRs/")
        for path in listing.split():
            first.setdefault(Path(path).name, version)
    return first


def adr_files() -> dict[str, Path]:
    return {p.name[:4]: p for p in sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))}


def adr_label(path: Path) -> str | None:
    """Return the version named by the ADR preamble's Spec version field."""
    for line in path.read_text(encoding="utf-8").splitlines()[:15]:
        match = _LABEL_RE.match(line)
        if match:
            version = _VERSION_RE.search(match.group(1))
            return version.group(0) if version else None
    return None


def history_sections() -> dict[int, tuple[str | None, str]]:
    """Return ``{section number: (target version, section text)}``."""
    text = HISTORY.read_text(encoding="utf-8")
    sections: dict[int, tuple[str | None, str]] = {}
    for part in re.split(r"(?m)^(?=## \d+\. )", text):
        match = _HISTORY_HEADING_RE.match(part)
        if match is None:
            continue
        versions = _VERSION_RE.findall(match.group(2))
        sections[int(match.group(1))] = (versions[-1] if versions else None, part)
    return sections


def cited_adrs(section: str) -> set[str]:
    """Return the ADR numbers a HISTORY section cites, expanding ranges."""
    cited: set[str] = set()
    for first, last in _ADR_CITE_RE.findall(section):
        end = int(last) if last else int(first)
        cited.update(f"{n:04d}" for n in range(int(first), end + 1))
    return cited


def test_label_naming_a_tag_names_the_first_tag_containing_the_adr() -> None:
    tags = spec_tags()
    first = first_tag_by_adr(tags)
    failures = []
    for number, path in adr_files().items():
        label = adr_label(path)
        if label not in tags:
            continue  # no label, or a version that no tag names
        if path.name not in first:
            continue  # no tag contains it yet: owner item, no tag evidence
        if first[path.name] != label:
            failures.append(
                f"ADR-{number} is labelled {label}, but the first spec tag "
                f"containing it is spec-v{first[path.name]}"
            )
    assert not failures, "\n".join(failures)


def test_registry_cell_repeats_the_adr_label() -> None:
    cells: dict[str, str] = {}
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        match = _REGISTRY_ROW_RE.match(line)
        if match:
            fields = [c.strip() for c in line.strip().strip("|").split("|")]
            cells[match.group(1)] = fields[2]
    failures = []
    for number, path in adr_files().items():
        label = adr_label(path)
        if label is None:
            continue
        if cells.get(number) != label:
            failures.append(f"ADR-{number}: preamble {label}, registry {cells.get(number)}")
    assert not failures, "\n".join(failures)


def test_history_headings_name_each_tagged_release_once() -> None:
    tags = spec_tags()
    targets = {n: t for n, (t, _) in history_sections().items() if n <= 38}
    tagged = [v for v in tags if _key(FIRST_HISTORY_TAG) <= _key(v) <= _key(LAST_CHECKED)]
    for version in tagged:
        matches = [n for n, t in targets.items() if t == version]
        assert len(matches) == 1, (
            f"spec-v{version} needs one HISTORY section 1 to 38, found {matches}"
        )
    ordered = [targets[n] for n in sorted(targets)]
    assert ordered == sorted(ordered, key=_key), "HISTORY sections 1 to 38 are out of version order"


def test_history_cites_each_adr_under_its_label_version() -> None:
    tags = spec_tags()
    first = first_tag_by_adr(tags)
    sections = history_sections()
    section_for = {t: n for n, (t, _) in sections.items() if n <= 38}
    failures = []
    for number, path in adr_files().items():
        label = adr_label(path)
        if label is None or not (_key(FIRST_CHECKED) <= _key(label) <= _key(LAST_CHECKED)):
            continue
        if label in tags and path.name not in first:
            continue  # owner item: no tag contains the ADR yet
        section = section_for.get(label)
        if section is None:
            failures.append(f"ADR-{number}: no HISTORY section 1 to 38 for {label}")
        elif number not in cited_adrs(sections[section][1]):
            failures.append(
                f"ADR-{number}: labelled {label}, not cited in HISTORY section {section}"
            )
    assert not failures, "\n".join(failures)


def test_adr_moved_by_the_tag_rule_leaves_its_old_history_section() -> None:
    # ADR-0080 and ADR-0081 were cited under v3.0.0 to v3.1.0, but spec-v3.1.0
    # does not contain them; the first tag containing them is spec-v3.23.0.
    section_8 = history_sections()[8][1]
    assert not ({"0080", "0081"} & cited_adrs(section_8))
