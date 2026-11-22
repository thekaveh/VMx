"""ADR release records agree with the spec tags and spec/HISTORY.md (#1814).

Rule A: an ADR whose ``Spec version`` label names a tagged release is a file of
that tag. The tag trees are read with read-only ``git ls-tree`` calls.

Rule B: each HISTORY section for a release at or after FIRST_ENFORCED_RELEASE
names the ADRs labelled with that release and the conformance IDs that the
release adds to the catalog. A release with no tag yet is read from the working
tree, and a section whose previous release has no tag is checked for ADRs only.

Each rule returns findings keyed by a stable string. An exemption names one
finding and the issue that owns it. An exemption that matches no finding fails
the real-tree test, so it is removed when its issue lands.

Status back-links and preamble field names (rules C and D of #1814) are not
checked here; they are a follow-up. This module is tools-only and needs no ADR.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "spec" / "ADRs"
HISTORY = ROOT / "spec" / "HISTORY.md"
CATALOG = ROOT / "spec" / "12-conformance.md"

# Rule B checks HISTORY sections for releases at or after this version. It stays
# here until the #1809 backfill of sections 1 to 38 lands.
FIRST_ENFORCED_RELEASE = "3.30.0"

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
_SPEC_VERSION_RE = re.compile(r"^(?:- )?\*\*Spec version:\*\*\s*(.*)$")
_ADR_FILE_RE = re.compile(r"^(\d{4})-[^/]*\.md$")
_HISTORY_HEADING_RE = re.compile(r"^## (\d+)\. ([^\n]*)")
_ADR_CITE_RE = re.compile(r"ADR-(\d{4})(?:\s+(?:through|to)\s+ADR-(\d{4}))?")
_ID_RE = re.compile(r"(?<![A-Za-z0-9-])([A-Z]+)-(\d{3})(?:\.\.(\d{3}))?(?!\d)")
_BACKTICK_RANGE_RE = re.compile(r"`([A-Z]+)-(\d{3})`\.\.`([A-Z]+)-(\d{3})`")
_CATALOG_HEADING_RE = re.compile(r"^### ([A-Z]+-\d{3})\b", re.MULTILINE)

# Findings that another issue owns. Each entry names the owner and the reason.
RULE_A_EXEMPTIONS: dict[str, str] = {
    "ADR-0146": "#1809 owner item (untagged label): labelled 3.29.0 and in no spec tag",
    "ADR-0147": "#1809 owner item (untagged label): labelled 3.29.0 and in no spec tag",
    "ADR-0148": "#1809 owner item (untagged label): labelled 3.29.0 and in no spec tag",
    "ADR-0149": "#1809 owner item (untagged label): labelled 3.29.0 and in no spec tag",
    "ADR-0150": "#1809 owner item (untagged label): labelled 3.29.0 and in no spec tag",
}
RULE_B_EXEMPTIONS: dict[str, str] = {
    "HISTORY 39: ADR-0233": "#1478 owner item: HISTORY section 39 does not name this ADR yet",
    "HISTORY 39: ADR-0239": "#1478 owner item: HISTORY section 39 does not name this ADR yet",
    "HISTORY 39: ADR-0240": "#1478 owner item: HISTORY section 39 does not name this ADR yet",
    "HISTORY 39: ADR-0241": "#1478 owner item: HISTORY section 39 does not name this ADR yet",
    "HISTORY 39: ADR-0242": "#1478 owner item: HISTORY section 39 does not name this ADR yet",
    "HISTORY 39: ADR-0244": "#1478 owner item: HISTORY section 39 does not name this ADR yet",
    "HISTORY 39: ADR-0245": "#1478 owner item: HISTORY section 39 does not name this ADR yet",
    "HISTORY 39: COL-073": "#1478 owner item: HISTORY section 39 does not name this ID yet",
    "HISTORY 39: CVM-011": "#1478 owner item: HISTORY section 39 does not name this ID yet",
    "HISTORY 39: FWD-007": "#1478 owner item: HISTORY section 39 does not name this ID yet",
}


def release_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True, timeout=60
    ).stdout


def spec_tags() -> dict[str, str]:
    """Return {version: tag name} for each spec-vX.Y.Z tag in the checkout."""
    names = _git("tag", "--list", "spec-v*").split()
    return {name.removeprefix("spec-v"): name for name in names}


def tag_adr_numbers(tag: str) -> frozenset[str]:
    """Return the ADR numbers whose files the tag's tree contains."""
    listing = _git("ls-tree", "-r", "--name-only", tag, "spec/ADRs")
    return frozenset(
        match.group(1)
        for path in listing.split()
        if (match := _ADR_FILE_RE.match(Path(path).name)) is not None
    )


def adr_label(text: str) -> str | None:
    """Return the first X.Y.Z of the Spec version field in an ADR preamble."""
    for line in text.splitlines():
        if line.startswith("## "):
            break
        match = _SPEC_VERSION_RE.match(line)
        if match is not None:
            version = _VERSION_RE.search(match.group(1))
            return version.group(0) if version is not None else None
    return None


def adr_labels(adr_dir: Path) -> dict[str, str | None]:
    """Return {ADR number: label} for each ADR file in adr_dir."""
    labels: dict[str, str | None] = {}
    for path in sorted(adr_dir.glob("*.md")):
        match = _ADR_FILE_RE.match(path.name)
        if match is not None:
            labels[match.group(1)] = adr_label(path.read_text(encoding="utf-8"))
    return labels


def rule_a_findings(
    labels: Mapping[str, str | None], tag_adrs: Mapping[str, frozenset[str]]
) -> dict[str, str]:
    """Return {key: message} for each ADR that its tagged label's tag does not contain."""
    findings: dict[str, str] = {}
    for number, label in labels.items():
        if label is None or label not in tag_adrs:
            continue  # no label, or a release with no tag to compare with
        if number not in tag_adrs[label]:
            findings[f"ADR-{number}"] = (
                f"ADR-{number} is labelled {label}, but spec-v{label} does not contain it"
            )
    return findings


@dataclass(frozen=True)
class HistorySection:
    number: int
    release: str | None
    previous: str | None
    text: str


def history_sections(text: str) -> list[HistorySection]:
    """Split HISTORY into sections. The heading's last X.Y.Z is the release it adds."""
    sections: list[HistorySection] = []
    for part in re.split(r"(?m)^(?=## \d+\. )", text):
        match = _HISTORY_HEADING_RE.match(part)
        if match is None:
            continue
        versions = _VERSION_RE.findall(match.group(2))
        sections.append(
            HistorySection(
                number=int(match.group(1)),
                release=versions[-1] if versions else None,
                previous=versions[0] if len(versions) > 1 else None,
                text=part,
            )
        )
    return sections


def cited_adrs(text: str) -> set[str]:
    """Return the ADR numbers a text names, expanding `through` and `to` ranges."""
    cited: set[str] = set()
    for first, last in _ADR_CITE_RE.findall(text):
        end = int(last) if last else int(first)
        cited.update(f"{n:04d}" for n in range(int(first), end + 1))
    return cited


def named_ids(text: str) -> set[str]:
    """Return the conformance IDs a text names, expanding both range notations."""
    named: set[str] = set()
    for first_prefix, first, last_prefix, last in _BACKTICK_RANGE_RE.findall(text):
        if first_prefix == last_prefix:
            named.update(f"{first_prefix}-{n:03d}" for n in range(int(first), int(last) + 1))
    for prefix, first, last in _ID_RE.findall(text):
        named.update(f"{prefix}-{n:03d}" for n in range(int(first), int(last or first) + 1))
    return named


def catalog_ids(text: str) -> frozenset[str]:
    return frozenset(_CATALOG_HEADING_RE.findall(text))


def release_catalogs(
    sections: Sequence[HistorySection], tags: Mapping[str, str]
) -> dict[str, frozenset[str]]:
    """Return {release: catalog IDs} for the releases that rule B compares.

    A tagged release reads its tag. The release that a checked section adds
    reads the working tree while it has no tag. Any other untagged release is
    absent, so the section is checked for ADRs only.
    """
    catalogs: dict[str, frozenset[str]] = {}
    for section in sections:
        if section.release is None or _is_before_enforcement(section.release):
            continue
        for release in (section.previous, section.release):
            if release is None or release in catalogs:
                continue
            if release in tags:
                text = _git("show", f"{tags[release]}:spec/12-conformance.md")
                catalogs[release] = catalog_ids(text)
            elif release == section.release:
                catalogs[release] = catalog_ids(CATALOG.read_text(encoding="utf-8"))
    return catalogs


def _is_before_enforcement(release: str) -> bool:
    return release_key(release) < release_key(FIRST_ENFORCED_RELEASE)


def rule_b_findings(
    sections: Sequence[HistorySection],
    labels: Mapping[str, str | None],
    catalogs: Mapping[str, frozenset[str]],
) -> dict[str, str]:
    """Return {key: message} for each ADR or ID that a checked section does not name."""
    findings: dict[str, str] = {}
    for section in sections:
        release = section.release
        if release is None or _is_before_enforcement(release):
            continue
        cited = cited_adrs(section.text)
        for number, label in labels.items():
            if label == release and number not in cited:
                findings[f"HISTORY {section.number}: ADR-{number}"] = (
                    f"HISTORY section {section.number} does not name ADR-{number}, "
                    f"which is labelled {release}"
                )
        after = catalogs.get(release)
        before = catalogs.get(section.previous) if section.previous is not None else None
        if after is None or before is None:
            continue  # no catalog to compare: the section is checked for ADRs only
        named = named_ids(section.text)
        for cid in sorted(after - before - named):
            findings[f"HISTORY {section.number}: {cid}"] = (
                f"HISTORY section {section.number} does not name {cid}, which {release} adds"
            )
    return findings


def problems(
    findings: Mapping[str, str], exemptions: Mapping[str, str], *, check_stale: bool = True
) -> list[str]:
    """Return the findings that no exemption covers, and the exemptions no finding matches."""
    issues = [message for key, message in findings.items() if key not in exemptions]
    if check_stale:
        issues += [
            f"exemption {key} matches no finding; remove it"
            for key in exemptions
            if key not in findings
        ]
    return issues


def test_rule_a_fixture_passes() -> None:
    labels = {"0001": "2.0.0", "0002": "3.30.0", "0003": None}
    tag_adrs = {"2.0.0": frozenset({"0001"})}
    assert rule_a_findings(labels, tag_adrs) == {}


def test_rule_a_fixture_fails_when_the_named_tag_lacks_the_adr() -> None:
    labels = {"0001": "2.0.0", "0002": "2.0.0"}
    tag_adrs = {"2.0.0": frozenset({"0001"})}
    assert list(rule_a_findings(labels, tag_adrs)) == ["ADR-0002"]


_FIXTURE_CATALOG_BEFORE = frozenset({"LIFE-001"})
_FIXTURE_CATALOG_AFTER = frozenset({"LIFE-001", "LIFE-016", "LIFE-017", "LIFE-018"})
_FIXTURE_HISTORY = (
    "# History\n\n"
    "## 38. v3.28.0 → v3.29.0 changes\n\n"
    "Adds no ID. Section 38 is before the enforced release.\n\n"
    "## 39. v3.29.0 → v3.30.0 changes\n\n"
    "Adds `LIFE-016`..`LIFE-018` and the helper of ADR-0001 through ADR-0002.\n"
)
_FIXTURE_LABELS = {"0001": "3.30.0", "0002": "3.30.0", "0009": "3.29.0"}


def test_rule_b_fixture_passes_when_the_section_names_each_adr_and_id() -> None:
    catalogs = {"3.29.0": _FIXTURE_CATALOG_BEFORE, "3.30.0": _FIXTURE_CATALOG_AFTER}
    sections = history_sections(_FIXTURE_HISTORY)
    assert rule_b_findings(sections, _FIXTURE_LABELS, catalogs) == {}


def test_rule_b_fixture_fails_on_an_unnamed_adr_and_id_of_the_release() -> None:
    history = _FIXTURE_HISTORY.replace(
        "`LIFE-016`..`LIFE-018` and the helper of ADR-0001 through ADR-0002.",
        "`LIFE-016`..`LIFE-017` and the helper of ADR-0001.",
    )
    catalogs = {"3.29.0": _FIXTURE_CATALOG_BEFORE, "3.30.0": _FIXTURE_CATALOG_AFTER}
    findings = rule_b_findings(history_sections(history), _FIXTURE_LABELS, catalogs)
    assert set(findings) == {"HISTORY 39: ADR-0002", "HISTORY 39: LIFE-018"}


def test_stale_exemption_is_a_problem() -> None:
    findings = {"HISTORY 39: ADR-0002": "not named"}
    exemptions = {"HISTORY 39: ADR-0002": "#1478", "HISTORY 39: ADR-0009": "#1478"}
    assert problems(findings, exemptions) == [
        "exemption HISTORY 39: ADR-0009 matches no finding; remove it"
    ]


def test_rule_a_holds_on_the_real_tree() -> None:
    tags = spec_tags()
    if not tags:
        pytest.skip("no spec-v* tags in this checkout (run git fetch --tags); rule A not checked")
    tag_adrs = {version: tag_adr_numbers(tag) for version, tag in tags.items()}
    findings = rule_a_findings(adr_labels(ADR_DIR), tag_adrs)
    assert problems(findings, RULE_A_EXEMPTIONS) == []


def test_rule_b_holds_on_the_real_tree() -> None:
    tags = spec_tags()
    sections = history_sections(HISTORY.read_text(encoding="utf-8"))
    catalogs = release_catalogs(sections, tags)
    findings = rule_b_findings(sections, adr_labels(ADR_DIR), catalogs)
    # Without spec tags, rule B cannot compare the IDs of a release with its
    # previous one, so exemptions are judged only when the tags are present.
    assert problems(findings, RULE_B_EXEMPTIONS, check_stale=bool(tags)) == []
