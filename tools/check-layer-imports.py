#!/usr/bin/env python3
"""Phase 6 cross-layer import check (C#, Python, and TypeScript showcases).

Enforces the Pure-VM layering of spec §6.1:

* Models → may import Models only.
* ViewModels → may import Models + ViewModels (and the *adapter sub-layer*
  of Views, but never plain Views).
* Views → may import anywhere.

Each flavor is scanned for every reference to another layer, in every form
the language allows:

* Python: ``import`` and ``from ... import`` statements, parsed with ``ast``.
  Relative imports resolve against the importing file's package, and
  ``from notes_showcase import views`` names the ``views`` layer. A file that
  fails to parse is a violation.
* C#: ``using`` (plain, ``static``, ``global`` and alias forms) and every
  namespace-qualified reference such as ``NotesShowcase.Views.Foo`` or
  ``Views.Foo`` in code. A member access such as ``this.Views.Count`` is not a
  layer reference. Comments and string literals are ignored.
* TypeScript: ``import``, ``export ... from``, side-effect ``import "x"`` and
  dynamic ``import("x")``, including forms that span several lines. Comments
  are ignored; string specifiers are kept.

Why the adapter exception:

The C# Avalonia flavor places its INPC sidecars (``BindableDerived<T>``,
``BindableVm``, etc.) under ``Views/Adapter/`` because they're framework-
specific binding helpers, but the VM layer references them directly (the
WPF/Avalonia binding model requires INPC-aware properties to live on the
VM, not on the view). The Python and TypeScript flavors avoid this with
adapter-side helpers (``bind_derived_property`` / ``useDerivedProperty``)
because their binding models don't require an INPC sidecar.

To stay symmetric *and* faithful to the Pure-VM contract, the adapter
sub-layer (``Views.Adapter`` / ``views.adapter`` / ``views/adapter``) is
treated as a peer of the VM layer for import purposes. Plain Views (and
Views.Modals, etc.) are still off-limits.

Swift is enforced by SwiftPM target boundaries instead of this text-import scan.

Run from repo root:

    python3 tools/check-layer-imports.py
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# Each flavor describes its layer roots and the adapter sub-layer exception.
FLAVORS = {
    "csharp": {
        "root": "examples/csharp/avalonia/NotesShowcase",
        "suffixes": {".cs"},
        "layers": ["Models", "ViewModels", "Views"],
        "adapter_segment": "Views.Adapter",
    },
    "python": {
        "root": "examples/python/textual/notes_showcase/src/notes_showcase",
        "suffixes": {".py"},
        "layers": ["models", "viewmodels", "views"],
        "adapter_segment": "views.adapter",
    },
    "typescript": {
        "root": "examples/typescript/react/notes-showcase/src",
        "suffixes": {".ts", ".tsx"},
        "layers": ["models", "viewmodels", "views"],
        "adapter_segment": "views/adapter",
    },
}

_PY_PACKAGE = "notes_showcase"

# C#: `Views.Foo` or `NotesShowcase.Views.Foo` (at least one member after the
# layer). A preceding `.` means a member access on some other object, such as
# `this.Views.Count`, so it is not a layer reference.
_CSHARP_QUALIFIED_RE = re.compile(
    r"(?<![\w.])(?:NotesShowcase\.)?((?:Models|ViewModels|Views)\.\w+(?:\.\w+)*)"
)
# C#: the namespace on its own, as in `using NotesShowcase.Views;`.
_CSHARP_NAMESPACE_RE = re.compile(
    r"(?<![\w.])NotesShowcase\.((?:Models|ViewModels|Views))(?![\w.])"
)

# TypeScript: the module specifier of a static import or re-export (the
# clause may span lines), a side-effect import, or a dynamic import.
_TS_SPECIFIER_RE = re.compile(
    r"""\b(?:import|export)\b[\w\s{},*$]*?\bfrom\s*["']([^"'\n]+)["']"""
    r"""|\bimport\b\s*["']([^"'\n]+)["']"""
    r"""|\bimport\s*\(\s*["']([^"'\n]+)["']"""
)


def _blank(text: str) -> str:
    """Replace every character except newlines with a space."""
    return re.sub(r"[^\n]", " ", text)


def _string_end(text: str, start: int) -> int:
    """Return the offset just past the string literal that opens at ``start``."""
    n = len(text)
    quote = text[start]
    if quote == '"' and start > 0 and text[start - 1] == "@":
        # C# verbatim string: no backslash escapes, `""` is a quote.
        j = start + 1
        while j < n:
            if text[j] == '"':
                if j + 1 < n and text[j + 1] == '"':
                    j += 2
                    continue
                return j + 1
            j += 1
        return n
    j = start + 1
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == quote:
            return j + 1
        if c == "\n" and quote != "`":
            # An unterminated single-line string ends at the newline.
            return j
        j += 1
    return n


def _mask_source(text: str, *, keep_strings: bool) -> str:
    """Blank comments, and string literals unless ``keep_strings``.

    Every masked character becomes a space and newlines are kept, so offsets
    and line numbers in the result match the source.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            end = text.find("\n", i)
            end = n if end == -1 else end
            out.append(_blank(text[i:end]))
        elif ch == "/" and nxt == "*":
            close = text.find("*/", i + 2)
            end = n if close == -1 else close + 2
            out.append(_blank(text[i:end]))
        elif ch in "\"'`" or (ch == "@" and nxt == '"'):
            quote_at = i + 1 if ch == "@" else i
            end = _string_end(text, quote_at)
            if keep_strings:
                out.append(text[i:end])
            else:
                out.append(_blank(text[i:end]))
        else:
            out.append(ch)
            i += 1
            continue
        i = end
    return "".join(out)


def _layer_of(path_parts: tuple[str, ...], layers: list[str]) -> str | None:
    """Return the first matching layer name found in the path parts (case-insensitive)."""
    lower = [p.lower() for p in path_parts]
    layer_lower = [layer.lower() for layer in layers]
    for p in lower:
        if p in layer_lower:
            return layers[layer_lower.index(p)]
    return None


def _ts_resolved_layer(
    importing: Path, specifier: str, base: Path, layers: list[str]
) -> str | None:
    """Resolve a TS relative/absolute import to the layer it targets.

    Returns the layer name (``models`` / ``viewmodels`` / ``views``) or ``None``
    if the specifier resolves outside the layered src tree (e.g. an npm package
    or ``vmx``).
    """
    if not specifier.startswith(("./", "../")):
        return None
    try:
        target = (importing.parent / specifier).resolve()
    except (OSError, RuntimeError):
        return None
    try:
        rel = target.relative_to(base)
    except ValueError:
        return None
    return _layer_of(rel.parts, layers)


def _ts_in_adapter(importing: Path, specifier: str, base: Path, adapter_segment: str) -> bool:
    """True when a TS specifier resolves inside the anchored ``views/adapter`` segment."""
    try:
        resolved = (importing.parent / specifier).resolve().relative_to(base)
    except (ValueError, OSError, RuntimeError):
        return False
    # Anchored: "views/adapter" must appear as whole segments, not as a prefix
    # of e.g. "views/adapterx".
    return f"/{adapter_segment}/" in f"/{resolved.as_posix()}/"


def _csharp_layer_from_import(ns: str, layers: list[str]) -> str | None:
    """`Models.Foo` → 'Models'; `Views.Adapter.Foo` → 'Views' (adapter handled separately)."""
    head = ns.split(".", 1)[0]
    return head if head in layers else None


def _python_layer_from_import(module: str, layers: list[str]) -> str | None:
    head = module.split(".", 1)[0]
    return head if head in layers else None


def _below_package(name: str) -> str | None:
    """Return a dotted name relative to the ``notes_showcase`` root.

    ``""`` names the root itself. ``None`` means the name is outside the package.
    """
    if name == _PY_PACKAGE:
        return ""
    prefix = _PY_PACKAGE + "."
    if name.startswith(prefix):
        return name[len(prefix) :]
    return None


def _python_import_targets(
    node: ast.Import | ast.ImportFrom, pkg_dir: tuple[str, ...]
) -> list[str]:
    """Return the dotted names below the package root that one import statement names.

    ``pkg_dir`` is the importing file's directory relative to the package root.
    A name of ``""`` (the root) is never returned, so the root's own names are
    returned instead: ``from notes_showcase import views`` names ``views``.
    """
    if isinstance(node, ast.Import):
        targets: list[str] = []
        for alias in node.names:
            below = _below_package(alias.name)
            if below:
                targets.append(below)
        return targets

    if node.level:
        up = node.level - 1
        if up > len(pkg_dir):
            return []  # relative import escapes the package
        parts = list(pkg_dir[: len(pkg_dir) - up])
        if node.module:
            parts.extend(node.module.split("."))
        dotted = ".".join(parts)
    else:
        resolved = _below_package(node.module or "")
        if resolved is None:
            return []  # not a notes_showcase import
        dotted = resolved

    if dotted:
        return [dotted]
    return [alias.name for alias in node.names if alias.name != "*"]


def _is_adapter(target: str, adapter_segment: str, sep: str) -> bool:
    """Anchored adapter-exception check (whole segments only)."""
    return target == adapter_segment or target.startswith(adapter_segment + sep)


def _refs(flavor: str, src: Path, base: Path, text: str) -> list[tuple[int, str]]:
    """Return (line, target) for each reference to another module in one file.

    Raises SyntaxError when a Python file does not parse.
    """
    if flavor == "python":
        tree = ast.parse(text, filename=str(src))
        pkg_dir = src.relative_to(base).parts[:-1]
        refs: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                for target in _python_import_targets(node, pkg_dir):
                    refs.append((node.lineno, target))
        return refs

    if flavor == "csharp":
        masked = _mask_source(text, keep_strings=False)
        csharp_refs: list[tuple[int, str]] = []
        for regex in (_CSHARP_QUALIFIED_RE, _CSHARP_NAMESPACE_RE):
            for m in regex.finditer(masked):
                csharp_refs.append((masked.count("\n", 0, m.start()) + 1, m.group(1)))
        return csharp_refs

    masked = _mask_source(text, keep_strings=True)
    ts_refs: list[tuple[int, str]] = []
    for m in _TS_SPECIFIER_RE.finditer(masked):
        specifier = next(g for g in m.groups() if g is not None)
        ts_refs.append((masked.count("\n", 0, m.start()) + 1, specifier))
    return ts_refs


def _target_layer(flavor: str, cfg: dict, src: Path, base: Path, target: str) -> str | None:
    """Return the layer a reference targets, or None when it is allowed or unrelated."""
    layers: list[str] = cfg["layers"]
    adapter_segment: str = cfg["adapter_segment"]

    if flavor == "typescript":
        tgt_layer = _ts_resolved_layer(src, target, base, layers)
        if tgt_layer == "views" and _ts_in_adapter(src, target, base, adapter_segment):
            return None
        return tgt_layer

    # C# and Python names are dotted namespaces or modules.
    if flavor == "csharp":
        tgt_layer = _csharp_layer_from_import(target, layers)
    else:
        tgt_layer = _python_layer_from_import(target, layers)
    if tgt_layer is None or _is_adapter(target, adapter_segment, "."):
        return None
    return tgt_layer


def check_flavor(flavor: str, cfg: dict, repo_root: Path) -> list[str]:
    base = repo_root / cfg["root"]
    if not base.exists():
        return [f"{flavor}: source root not found: {base}"]

    layers: list[str] = cfg["layers"]
    violations: list[str] = []

    for src in base.rglob("*"):
        if src.suffix not in cfg["suffixes"]:
            continue
        if not src.is_file():
            continue
        # Skip build artefacts.
        if any(part in {"bin", "obj", "node_modules", "dist", "__pycache__"} for part in src.parts):
            continue

        rel = src.relative_to(base)
        own_layer = _layer_of(rel.parts, layers)
        if own_layer is None:
            continue

        own_idx = layers.index(own_layer)
        forbidden_layers = layers[own_idx + 1 :]  # everything strictly above

        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        try:
            refs = _refs(flavor, src, base, text)
        except (SyntaxError, ValueError) as exc:
            line_no = getattr(exc, "lineno", None) or 1
            violations.append(f"{flavor}: {rel}:{line_no}: syntax error: {exc}")
            continue

        lines = text.split("\n")
        for line_no, target in sorted(refs):
            tgt_layer = _target_layer(flavor, cfg, src, base, target)
            if tgt_layer is None or tgt_layer not in forbidden_layers:
                continue
            snippet = lines[line_no - 1].strip() if line_no <= len(lines) else target
            violations.append(
                f"{flavor}: {rel}:{line_no}: forbidden import of {tgt_layer} "
                f"from {own_layer}: {snippet}"
            )

    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root (default: current dir)")
    args = ap.parse_args()
    repo_root = Path(args.root).resolve()

    failures: list[str] = []
    checked = 0
    for flavor, cfg in FLAVORS.items():
        base = repo_root / cfg["root"]
        if base.exists():
            checked += 1
        failures.extend(check_flavor(flavor, cfg, repo_root))

    if failures:
        print("\n".join(failures), file=sys.stderr)
        print(
            f"\n[FAIL] {len(failures)} layer violation(s) across {checked} flavors",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] cross-layer imports clean across {checked} flavors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
