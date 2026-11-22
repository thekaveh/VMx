"""ADR release records agree with the spec tags, spec/HISTORY.md and the catalog (#1814).

Rule A: an ADR whose ``Spec version`` label names a tagged release is a file of
that tag. Rule B: each HISTORY section from ``FIRST_ENFORCED_RELEASE`` on names
the ADRs labelled with its release and the catalog IDs that the release adds.
Rule C: a body sentence in which ``supersedes``, ``replaces`` or ``retires``
precedes an earlier ADR needs a back-link to the later ADR in that earlier ADR's
``Status``, with a verb that registry section 2.3 defines.

The rules read the spec files and the ``spec-v*`` tags. Git runs read-only
commands only. Rule D (preamble field names and back-link verbs) and the generic
back-link check are in ``test_registry_and_changelog_records.py`` (#1810).

Findings that come from records outside this change (#1478 and #1809), and the
false positives of rule C, are listed with a reason in
``adr_release_records_allowlist.json`` next to this module. Each key is the
rule letter, a space and the finding. An entry that no longer matches a finding
fails its test, so the list shrinks as the records are corrected.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.test_registry_and_changelog_records import adr_status

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "spec"
ADR_DIR = SPEC / "ADRs"
REGISTRY = ADR_DIR / "README.md"
HISTORY = SPEC / "HISTORY.md"
CATALOG_PATH = "spec/12-conformance.md"
ALLOWLIST = Path(__file__).with_name("adr_release_records_allowlist.json")

# Rule B checks a HISTORY section only from this release on. The sections of
# earlier releases wait for the spec/HISTORY.md backfill in #1809.
FIRST_ENFORCED_RELEASE = "3.30.0"

# A finding is (allowlist key, message). The key starts with the rule letter.
Finding = tuple[str, str]

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
_LABEL_RE = re.compile(r"^(?:- )?\*\*Spec version:\*\*[ \t]*(.*)$", re.MULTILINE)
_SECTION_RE = re.compile(r"^## (\d+)\. (.*)$", re.MULTILINE)
_CATALOG_HEADING_RE = re.compile(r"^### ([A-Z]+-\d{3})\b", re.MULTILINE)
_ADR_CITE_RE = re.compile(r"ADR-(\d{4})(?:\s+(?:through|to)\s+ADR-(\d{4}))?")
# An ID, or a range such as `DLY-001`..`DLY-005` or NOTIF-011..016.
_ID_CITE_RE = re.compile(
    r"(?<![A-Za-z0-9-])([A-Z]+)-(\d{3})(?:(?:`\.\.`|\.\.)(?:([A-Z]+)-)?(\d{3}))?(?!\d)"
)
# A sentence ends at a full stop followed by a space, at a semicolon or at a blank
# line. A full stop inside a token, such as "§2.5", does not end it.
_SUPERSESSION_RE = re.compile(
    r"\b(supersedes|replaces|retires)\b((?:[^.;\n]|\n(?=[^\n])|\.(?=\S))*?)\bADR-(\d{4})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Section:
    """One HISTORY section: its number, its release range and its text."""

    number: int
    previous: str | None
    target: str | None
    text: str


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def adr_label(text: str) -> str | None:
    """Return the first X.Y.Z of the ADR preamble's Spec version field."""
    preamble = text.split("\n## ", 1)[0]
    match = _LABEL_RE.search(preamble)
    if match is None:
        return None
    version = _VERSION_RE.search(match.group(1))
    return version.group(0) if version else None


def adr_texts(adr_dir: Path) -> dict[str, str]:
    """Return {file name: text} for each numbered ADR file."""
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    }


def history_sections(text: str) -> list[Section]:
    """Split HISTORY into sections. A heading ``vA → vB`` gives previous A and target B."""
    headings = list(_SECTION_RE.finditer(text))
    sections = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        versions = _VERSION_RE.findall(heading.group(2))
        sections.append(
            Section(
                number=int(heading.group(1)),
                previous=versions[0] if len(versions) > 1 else None,
                target=versions[-1] if versions else None,
                text=text[heading.start() : end],
            )
        )
    return sections


def cited_adrs(text: str) -> set[str]:
    """Return the ADR numbers a text names, expanding ranges such as ADR-0184 through ADR-0226."""
    cited: set[str] = set()
    for first, last in _ADR_CITE_RE.findall(text):
        cited.update(f"{n:04d}" for n in range(int(first), int(last or first) + 1))
    return cited


def cited_ids(text: str) -> set[str]:
    """Return the catalog IDs a text names, expanding ranges such as `DLY-001`..`DLY-005`."""
    named: set[str] = set()
    for prefix, first, _, last in _ID_CITE_RE.findall(text):
        named.update(f"{prefix}-{n:03d}" for n in range(int(first), int(last or first) + 1))
    return named


def back_link_verbs(registry_text: str) -> set[str]:
    """Return the back-link verbs that registry section 2.3 defines, lower-cased."""
    start = registry_text.index("### 2.3")
    end = registry_text.index("### 2.4")
    return {verb.lower() for verb in re.findall(r"`([A-Za-z]+) by`", registry_text[start:end])}


def _git(root: Path, *args: str) -> str | None:
    """Run one read-only git command. Return its output, or None when it fails."""
    done = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, timeout=60
    )
    return done.stdout if done.returncode == 0 else None


def spec_tags(root: Path) -> dict[str, str]:
    """Return {version: tag name} for each spec-vX.Y.Z tag in the checkout."""
    names = (_git(root, "tag", "--list", "spec-v*") or "").split()
    return {
        name.removeprefix("spec-v"): name
        for name in names
        if _VERSION_RE.fullmatch(name.removeprefix("spec-v"))
    }


def tag_adr_names(root: Path, tag: str) -> set[str]:
    """Return the ADR file names that the tag's tree contains."""
    listing = _git(root, "ls-tree", "-r", "--name-only", tag, "--", "spec/ADRs") or ""
    names = (Path(path).name for path in listing.split())
    return {name for name in names if re.fullmatch(r"\d{4}-.+\.md", name)}


def release_new_ids(
    root: Path, tags: dict[str, str], previous: str | None, target: str | None
) -> set[str] | None:
    """Return the catalog IDs that the target release adds over the previous tag.

    A tagged target is read from its tag. An untagged target, the release in
    progress, is read from the working tree. None means the IDs cannot be
    compared, because the previous tag or a catalog is missing.
    """
    if target is None or previous not in tags:
        return None
    before = _git(root, "show", f"{tags[previous]}:{CATALOG_PATH}")
    if target in tags:
        after = _git(root, "show", f"{tags[target]}:{CATALOG_PATH}")
    else:
        after = (root / CATALOG_PATH).read_text(encoding="utf-8")
    if before is None or after is None:
        return None
    return set(_CATALOG_HEADING_RE.findall(after)) - set(_CATALOG_HEADING_RE.findall(before))


def label_issues(labels: dict[str, str | None], tag_members: dict[str, set[str]]) -> list[Finding]:
    """Rule A. Each ADR labelled with a tagged release must be a file of that tag.

    ``labels`` maps an ADR file name to its label. ``tag_members`` maps a
    version to the ADR file names of ``spec-v<version>``. A label that no tag
    names is outside this rule.
    """
    findings: list[Finding] = []
    for name, label in sorted(labels.items()):
        if label in tag_members and name not in tag_members[label]:
            number = name[:4]
            findings.append(
                (
                    f"A ADR-{number}",
                    f"ADR-{number} is labelled {label}, but spec-v{label} does not contain it",
                )
            )
    return findings


def release_record_issues(
    sections: list[Section],
    labels: dict[str, str | None],
    new_ids: dict[str, set[str]],
    first: str = FIRST_ENFORCED_RELEASE,
) -> list[Finding]:
    """Rule B. A HISTORY section names the ADRs and the new IDs of its target release.

    Only sections whose target is ``first`` or later are checked. ``new_ids``
    maps a target to the catalog IDs it adds, and a target absent from it is
    checked for ADRs only.
    """
    findings: list[Finding] = []
    for section in sections:
        target = section.target
        if target is None or _key(target) < _key(first):
            continue
        cited = cited_adrs(section.text)
        for name, label in sorted(labels.items()):
            number = name[:4]
            if label == target and number not in cited:
                findings.append(
                    (
                        f"B {target} ADR-{number}",
                        f"HISTORY §{section.number} ({target}) does not name ADR-{number}",
                    )
                )
        named = cited_ids(section.text)
        for ident in sorted(new_ids.get(target, set()) - named):
            findings.append(
                (
                    f"B {target} {ident}",
                    f"HISTORY §{section.number} ({target}) does not name {ident}",
                )
            )
    return findings


def supersession_issues(texts: dict[str, str], verbs: set[str]) -> list[Finding]:
    """Rule C. A body sentence that supersedes an earlier ADR needs its back-link.

    Only the body (text from the first ``## `` heading on) is read, and only an
    earlier ADR number counts. The earlier ADR's ``Status`` must name the later
    ADR with one of the back-link ``verbs``.
    """
    by_number = {name[:4]: text for name, text in texts.items()}
    verb_re = "|".join(re.escape(verb) for verb in sorted(verbs))
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for name, text in sorted(texts.items()):
        later = name[:4]
        body = text.partition("\n## ")[2]
        for match in _SUPERSESSION_RE.finditer(body):
            verb, earlier = match.group(1).lower(), match.group(3)
            if int(earlier) >= int(later) or earlier not in by_number:
                continue
            if (later, earlier) in seen:
                continue
            seen.add((later, earlier))
            status = adr_status(by_number[earlier])
            back_link = rf"\b(?:{verb_re})\s+by\b[^;)]*\bADR-{later}\b"
            if not re.search(back_link, status, re.IGNORECASE):
                findings.append(
                    (
                        f"C ADR-{later} -> ADR-{earlier}",
                        f"ADR-{later} says it {verb} ADR-{earlier}, but ADR-{earlier} "
                        f"Status has no back-link to ADR-{later}",
                    )
                )
    return findings


def _load_allowlist() -> dict[str, str]:
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))


def _unlisted_and_stale(
    findings: list[Finding], rule: str, judged: Callable[[str], bool] = lambda key: True
) -> list[str]:
    """Return the findings of one rule that the allowlist does not cover, and stale entries.

    ``judged`` says whether this run could produce an allowlist key. An entry the
    run cannot judge is neither stale nor a failure.
    """
    allowlist = _load_allowlist()
    keys = {key for key, _ in findings}
    problems = [message for key, message in findings if key not in allowlist]
    problems.extend(
        f"allowlist entry no longer matches a finding: {key!r}"
        for key in sorted(allowlist)
        if key.startswith(f"{rule} ") and key not in keys and judged(key)
    )
    return problems


# Rule A, rule B and rule C tests on the repository (real tree).


def test_adr_label_naming_a_tag_is_a_file_of_that_tag() -> None:
    tags = spec_tags(ROOT)
    if not tags:
        pytest.skip("no spec-v tags in this checkout; run `git fetch --tags` to check rule A")
    members = {version: tag_adr_names(ROOT, tag) for version, tag in tags.items()}
    labels = {name: adr_label(text) for name, text in adr_texts(ADR_DIR).items()}
    problems = _unlisted_and_stale(label_issues(labels, members), "A")
    assert problems == [], "\n".join(problems)


def test_history_section_names_the_adrs_and_ids_of_its_release() -> None:
    tags = spec_tags(ROOT)
    sections = history_sections(HISTORY.read_text(encoding="utf-8"))
    labels = {name: adr_label(text) for name, text in adr_texts(ADR_DIR).items()}
    new_ids: dict[str, set[str]] = {}
    for section in sections:
        if section.target is None or _key(section.target) < _key(FIRST_ENFORCED_RELEASE):
            continue
        ids = release_new_ids(ROOT, tags, section.previous, section.target)
        if ids is not None:
            new_ids[section.target] = ids

    # Without tags, the new IDs of a release are unknown, so only ADR keys are judged.
    def judged(key: str) -> bool:
        _, target, name = key.split(" ", 2)
        return name.startswith("ADR-") or target in new_ids

    findings = release_record_issues(sections, labels, new_ids)
    problems = _unlisted_and_stale(findings, "B", judged)
    assert problems == [], "\n".join(problems)


def test_supersession_sentence_has_a_back_link_in_the_earlier_adr() -> None:
    texts = adr_texts(ADR_DIR)
    verbs = back_link_verbs(REGISTRY.read_text(encoding="utf-8"))
    problems = _unlisted_and_stale(supersession_issues(texts, verbs), "C")
    assert problems == [], "\n".join(problems)


def test_allowlist_entries_have_a_known_rule_and_a_reason() -> None:
    for key, reason in _load_allowlist().items():
        assert key[:2] in {"A ", "B ", "C "}, f"{key!r} does not start with a rule letter"
        assert len(reason.split()) >= 8, f"{key!r} needs a reason of its own: {reason!r}"


# Fixtures: one passing and one failing case for each rule.

_FIXTURE_TAGS = {"3.0.0": {"0001-a.md"}, "3.1.0": {"0003-c.md"}}


def test_label_fixture_passes_when_each_labelled_adr_is_in_its_tag() -> None:
    labels = {"0001-a.md": "3.0.0", "0002-b.md": None, "0003-c.md": "3.1.0", "0004-d.md": "3.9.0"}
    assert label_issues(labels, _FIXTURE_TAGS) == []


def test_label_fixture_reports_an_adr_missing_from_its_labelled_tag() -> None:
    labels = {"0001-a.md": "3.1.0", "0003-c.md": "3.1.0"}
    assert [key for key, _ in label_issues(labels, _FIXTURE_TAGS)] == ["A ADR-0001"]


_HISTORY_FIXTURE = (
    "# History\n\n## 1. v3.30.0 → v3.31.0 changes\n\n"
    "Adds ADR-0005 and `NOTIF-011`..`NOTIF-013` (ADR-0006 through ADR-0007).\n\n"
    "## 2. v3.28.0 → v3.29.0 changes\n\nNames nothing from the record checks.\n"
)


def test_history_fixture_passes_when_the_section_names_its_release() -> None:
    sections = history_sections(_HISTORY_FIXTURE)
    labels = {"0005-e.md": "3.31.0", "0006-f.md": "3.31.0", "0007-g.md": "3.31.0"}
    new_ids = {"3.31.0": {"NOTIF-011", "NOTIF-012", "NOTIF-013"}}
    # Section 2 targets 3.29.0, below FIRST_ENFORCED_RELEASE, so its unnamed ADR is not checked.
    labels["0008-h.md"] = "3.29.0"
    assert release_record_issues(sections, labels, new_ids) == []


def test_history_fixture_reports_a_missing_adr_and_a_missing_id() -> None:
    sections = history_sections(_HISTORY_FIXTURE)
    labels = {"0005-e.md": "3.31.0", "0009-i.md": "3.31.0"}
    new_ids = {"3.31.0": {"NOTIF-011", "NOTIF-014"}}
    keys = [key for key, _ in release_record_issues(sections, labels, new_ids)]
    assert keys == ["B 3.31.0 ADR-0009", "B 3.31.0 NOTIF-014"]


_SUPERSESSION_VERBS = {"superseded", "amended", "extended", "clarified"}


def test_supersession_fixture_passes_when_the_earlier_status_links_back() -> None:
    texts = {
        "0001-a.md": "# ADR 0001\n\n- **Status:** Superseded by ADR-0002\n\n## 1. Context\n",
        "0002-b.md": (
            "# ADR 0002\n\n- **Status:** Accepted\n- **Supersedes:** [ADR-0001](0001-a.md).\n\n"
            "## 1. Context\n\nThis ADR supersedes ADR-0001 for the whole decision.\n"
        ),
    }
    assert supersession_issues(texts, _SUPERSESSION_VERBS) == []


def test_supersession_fixture_reports_an_earlier_status_without_a_back_link() -> None:
    texts = {
        "0001-a.md": "# ADR 0001\n\n- **Status:** Accepted\n\n## 1. Context\n",
        "0002-b.md": (
            "# ADR 0002\n\n- **Status:** Accepted\n\n## 1. Context\n\n"
            "This ADR replaces ADR-0001 in full.\n"
        ),
    }
    assert [key for key, _ in supersession_issues(texts, _SUPERSESSION_VERBS)] == [
        "C ADR-0002 -> ADR-0001"
    ]
