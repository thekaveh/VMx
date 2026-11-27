"""Export contracts of the TypeScript public declarations (#1888, Part 1).

Each ``// ==== <file> ====`` section of ``langs/typescript/api/vmx.api.txt`` is
one declaration file. A top-level declared name in a section must be listed by
that section's local ``export { ... };`` statement, which has no ``from``. A
name that is declared but not exported is reachable only through another
type's signature, so a consumer cannot name it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "langs/typescript/api/vmx.api.txt"

# Declared names that Part 1 leaves unexported. Part 2 (TypeScript 4.0) strips the
# @internal declarations and removes these names from the baseline.
DEFERRED_TO_4_0 = frozenset({"IOwningParentVM", "ParentTransfer"})
# Module-private option symbols that the bundler emits once per entry point, for
# example ``optionHub$1``. Consumers cannot name them, and they stay as they are.
PRIVATE_OPTION_SYMBOL = re.compile(r"^option(?:Hub|Dispatcher)(?:\$\d+)?$")
# Public types that the root index must export (#1888, Part 1).
ROOT_PUBLIC_TYPES = frozenset(
    {"AsyncTask", "ContainerRollbackError", "FieldValidator", "ModelEquals", "ModelValidator"}
)

SECTION = re.compile(r"^// ==== (?P<name>.+) ====$", re.MULTILINE)
DECLARED = re.compile(
    r"^(?:declare (?:abstract )?(?:class|enum|function|const)|interface|type)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
EXPORT_LIST = re.compile(r"^export \{(?P<items>[^}]*)\}(?P<tail>[^\n]*)$", re.MULTILINE)


def sections(text: str) -> dict[str, str]:
    """Return the body of each ``// ==== <file> ====`` section, keyed by file name."""
    matches = list(SECTION.finditer(text))
    bodies: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        bodies[match.group("name")] = text[match.end() : end]
    return bodies


def declared_names(body: str) -> list[str]:
    """Return the top-level names that a section declares."""
    return [match.group("name") for match in DECLARED.finditer(body)]


def export_items(body: str, *, local: bool) -> set[str]:
    """Return the public names of the export lists in a section.

    ``local=True`` reads only the lists without ``from``, which name the
    section's own declarations. ``local=False`` reads only the re-export lists
    that name another section's declarations. The result is the public name:
    the part after ``as``, or the item itself when it has no rename.
    """
    names: set[str] = set()
    for match in EXPORT_LIST.finditer(body):
        is_reexport = match.group("tail").strip().startswith("from")
        if is_reexport == local:
            continue
        for item in match.group("items").split(","):
            item = item.strip()
            if item.startswith("type "):
                item = item[len("type ") :].strip()
            if item:
                names.add(item.split(" as ")[-1].strip())
    return names


def unexported_names(body: str) -> list[str]:
    """Return the declared names that the section's local export lists do not list.

    An item ``Local as Public`` lists ``Local``, the declared name, so the match
    uses the name before ``as``.
    """
    listed: set[str] = set()
    for match in EXPORT_LIST.finditer(body):
        if match.group("tail").strip().startswith("from"):
            continue
        for item in match.group("items").split(","):
            item = item.strip()
            if item.startswith("type "):
                item = item[len("type ") :].strip()
            if item:
                listed.add(item.split(" as ")[0].strip())
    return [name for name in declared_names(body) if name not in listed]


def test_every_declared_name_is_exported_or_deferred_to_4_0():
    violations: dict[str, list[str]] = {}
    for section, body in sections(BASELINE.read_text(encoding="utf-8")).items():
        missing = [
            name
            for name in unexported_names(body)
            if name not in DEFERRED_TO_4_0 and not PRIVATE_OPTION_SYMBOL.match(name)
        ]
        if missing:
            violations[section] = missing
    assert not violations, (
        "declared in the API baseline but not exported by their section "
        f"(export them from src/index.ts, or make them private): {violations}"
    )


def test_root_index_exports_the_public_types():
    index_body = sections(BASELINE.read_text(encoding="utf-8"))["index.d.ts"]
    exported = export_items(index_body, local=True) | export_items(index_body, local=False)
    missing = sorted(ROOT_PUBLIC_TYPES - exported)
    assert not missing, f"the root declarations do not export: {missing}"


def test_no_private_hub_interface_copy_remains():
    text = BASELINE.read_text(encoding="utf-8")
    assert not re.search(r"\bIHubLike(?:\$\d+)?\b", text), (
        'the hub parameter has a private interface copy; type it as Pick<IMessageHub, "messages">'
    )


def test_rule_flags_a_declared_name_missing_from_the_local_export_list():
    body = "declare class Shown {\n}\ndeclare class Hidden {\n}\nexport { Shown };\n"

    assert unexported_names(body) == ["Hidden"]


def test_rule_reads_renames_and_ignores_re_exports():
    body = (
        "declare class Inner {\n}\n"
        "export { type Inner as Outer };\n"
        "export { Elsewhere } from './other.js';\n"
    )

    assert unexported_names(body) == []
    assert export_items(body, local=True) == {"Outer"}
    assert export_items(body, local=False) == {"Elsewhere"}


@pytest.mark.parametrize(
    "declaration",
    [
        "declare abstract class Hidden {\n}",
        "declare enum Hidden {\n}",
        "declare function Hidden(): void;",
        "declare const Hidden: number;",
        "interface Hidden {\n}",
        "type Hidden<T> = T;",
    ],
)
def test_rule_reads_every_declaration_kind(declaration: str):
    assert unexported_names(f"{declaration}\nexport {{ }};\n") == ["Hidden"]


def test_rule_reads_hashed_dollar_names():
    body = "interface IHubLike$1 {\n}\nexport { };\n"

    assert unexported_names(body) == ["IHubLike$1"]
    assert PRIVATE_OPTION_SYMBOL.match("optionDispatcher$3")
    assert not PRIVATE_OPTION_SYMBOL.match("optionDispatcherFactory")
