#!/usr/bin/env python3
"""Compare the public API of the ``vmx`` Python package with its recorded baseline.

The public surface is every importable module of the package that declares
``__all__`` (packages and the few public modules that list their exports);
modules without ``__all__`` are implementation modules. The tool imports each
such module and renders, for every name in its ``__all__``:

* a class: its bases and each public member (methods with their signatures,
  properties, enum members, and attributes), including members inherited from
  VMx classes that are not themselves exported;
* a function: its signature;
* any other object: its type.

An object exported from several modules is rendered in full once, under the
first module in sorted order, and as an alias elsewhere. Annotations are
rendered as written in the source (``from __future__ import annotations``),
but a few reprs (generic bases, union aliases) differ between Python
versions, so the tool renders on one pinned version, ``PYTHON_VERSION``.

Run it from ``langs/python`` so the project environment provides ``vmx``::

    uv run --python 3.12 python ../../tools/check-python-api.py            # check
    uv run --python 3.12 python ../../tools/check-python-api.py --update   # rewrite

Exit codes: 0 when the API matches the baseline, 1 on any difference (the
unified diff is printed), 2 on a usage or import error.
"""

from __future__ import annotations

import argparse
import difflib
import enum
import importlib
import inspect
import pkgutil
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

DEFAULT_PACKAGE = "vmx"
DEFAULT_BASELINE = Path(__file__).resolve().parents[1] / "langs/python/api/vmx.api.txt"
PYTHON_VERSION = (3, 12)
UPDATE_HINT = "uv run --python 3.12 python ../../tools/check-python-api.py --update"

_ADDRESS = re.compile(r" at 0x[0-9A-Fa-f]+")
# Dunder members that are part of a class's usable surface when the class
# body defines them. Interpreter-managed dunders (__dict__, __slots__,
# __static_attributes__, ...) vary by Python version and are never recorded.
_PROTOCOL_DUNDERS = frozenset(
    {
        "__init__",
        "__call__",
        "__enter__",
        "__exit__",
        "__aenter__",
        "__aexit__",
        "__iter__",
        "__aiter__",
        "__next__",
        "__anext__",
        "__len__",
        "__contains__",
        "__getitem__",
        "__setitem__",
        "__delitem__",
        "__bool__",
    }
)


def _clean(text: str) -> str:
    """Remove memory addresses so default-value reprs are deterministic."""
    return _ADDRESS.sub("", text)


def _signature(obj: Any) -> str:
    try:
        return _clean(str(inspect.signature(obj)))
    except (TypeError, ValueError):
        return "(...)"


def public_modules(package_name: str) -> list[ModuleType]:
    """Return the package and each submodule that declares ``__all__``, sorted by name."""
    package = importlib.import_module(package_name)
    modules = [package]
    for info in pkgutil.walk_packages(package.__path__, f"{package_name}."):
        if any(part.startswith("_") for part in info.name.split(".")):
            continue
        modules.append(importlib.import_module(info.name))
    return sorted(
        (module for module in modules if "__all__" in vars(module)),
        key=lambda module: module.__name__,
    )


def _is_package_class(cls: type, package_name: str) -> bool:
    module = getattr(cls, "__module__", "") or ""
    return module == package_name or module.startswith(f"{package_name}.")


def _member_lines(name: str, value: Any, owner: type) -> list[str]:
    if isinstance(value, staticmethod):
        return [f"    static def {name}{_signature(value.__func__)}"]
    if isinstance(value, classmethod):
        return [f"    classmethod def {name}{_signature(value.__func__)}"]
    if isinstance(value, property):
        mode = "get/set" if value.fset is not None else "get"
        returns = inspect.signature(value.fget).return_annotation if value.fget else None
        annotation = "" if returns in (None, inspect.Signature.empty) else f" -> {returns}"
        return [f"    property {name} [{mode}]{_clean(annotation)}"]
    if inspect.iscoroutinefunction(value):
        return [f"    async def {name}{_signature(value)}"]
    if inspect.isfunction(value):
        return [f"    def {name}{_signature(value)}"]
    if isinstance(value, enum.Enum):
        return [f"    member {name} = {_clean(repr(value.value))}"]
    if isinstance(value, type):
        return [f"    class {name}"]
    annotations = vars(owner).get("__annotations__", {})
    if name in annotations:
        return [f"    attribute {name}: {_clean(str(annotations[name]))}"]
    return [f"    attribute {name}: {type(value).__qualname__}"]


def render_class(cls: type, package_name: str, exported: set[int]) -> list[str]:
    bases = getattr(cls, "__orig_bases__", None) or cls.__bases__
    rendered_bases = ", ".join(
        base.__qualname__ if isinstance(base, type) else _clean(repr(base)) for base in bases
    )
    lines = [f"  class {cls.__qualname__}({rendered_bases})"]
    members: dict[str, tuple[Any, type]] = {}
    for owner in cls.__mro__:
        if owner is not cls and (
            not _is_package_class(owner, package_name) or id(owner) in exported
        ):
            continue
        for name, value in vars(owner).items():
            if name in members:
                continue
            if name.startswith("_") and name not in _PROTOCOL_DUNDERS:
                continue
            if name in _PROTOCOL_DUNDERS:
                function = getattr(value, "__func__", value)
                qualname = getattr(function, "__qualname__", "")
                if not qualname.startswith(f"{owner.__qualname__}."):
                    continue  # generated by typing/abc machinery, not by VMx
            members[name] = (value, owner)
    # Annotated attributes without a class-level value (dataclass fields,
    # protocol members) are still part of the declared surface.
    for owner in cls.__mro__:
        if owner is not cls and (
            not _is_package_class(owner, package_name) or id(owner) in exported
        ):
            continue
        for name in vars(owner).get("__annotations__", {}):
            if not name.startswith("_") and name not in members:
                members[name] = (inspect.Parameter.empty, owner)
    for name in sorted(members):
        value, owner = members[name]
        if value is inspect.Parameter.empty:
            annotation = vars(owner)["__annotations__"][name]
            lines.append(f"    attribute {name}: {_clean(str(annotation))}")
        else:
            lines.extend(_member_lines(name, value, owner))
    return lines


def render_object(name: str, obj: Any, package_name: str, exported: set[int]) -> list[str]:
    if isinstance(obj, type):
        return render_class(obj, package_name, exported)
    if inspect.iscoroutinefunction(obj):
        return [f"  async def {name}{_signature(obj)}"]
    if inspect.isfunction(obj) or inspect.isbuiltin(obj):
        return [f"  def {name}{_signature(obj)}"]
    if isinstance(obj, ModuleType):
        return [f"  module {name}"]
    if type(obj).__module__ in ("typing", "types"):
        return [f"  alias {name} = {_clean(repr(obj))}"]
    return [f"  {name}: {type(obj).__qualname__}"]


def render_api(package_name: str) -> str:
    modules = public_modules(package_name)
    exported: set[int] = {
        id(getattr(module, name))
        for module in modules
        for name in module.__all__
        if isinstance(getattr(module, name, None), type)
    }
    first_home: dict[int, str] = {}
    lines: list[str] = [
        f"# Public API of the {package_name} Python package.",
        "# Generated by tools/check-python-api.py; do not edit by hand.",
    ]
    for module in modules:
        lines.append("")
        lines.append(f"module {module.__name__}")
        for name in sorted(set(module.__all__)):
            if not hasattr(module, name):
                raise AttributeError(f"{module.__name__}.__all__ names missing {name!r}")
            obj = getattr(module, name)
            shareable = isinstance(obj, type) or inspect.isfunction(obj)
            if shareable and id(obj) in first_home:
                lines.append(f"  {name} = {first_home[id(obj)]}")
                continue
            if shareable:
                first_home[id(obj)] = f"{module.__name__}.{name}"
            lines.extend(render_object(name, obj, package_name, exported))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--update", action="store_true", help="rewrite the baseline")
    args = parser.parse_args(argv)
    if sys.version_info[:2] != PYTHON_VERSION:
        pinned = ".".join(map(str, PYTHON_VERSION))
        print(
            f"ERROR: render the API on Python {pinned}, not "
            f"{sys.version_info.major}.{sys.version_info.minor}: "
            f"uv run --python {pinned} python ../../tools/check-python-api.py",
            file=sys.stderr,
        )
        return 2
    try:
        current = render_api(args.package)
    except (ImportError, AttributeError) as error:
        print(f"ERROR: cannot render the {args.package} API: {error}", file=sys.stderr)
        return 2
    if args.update:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(current, encoding="utf-8")
        print(f"Updated {args.baseline}")
        return 0
    if not args.baseline.is_file():
        print(f"FAIL: missing API baseline {args.baseline}; run {UPDATE_HINT}", file=sys.stderr)
        return 1
    recorded = args.baseline.read_text(encoding="utf-8")
    if recorded == current:
        print(f"OK: the {args.package} public API matches {args.baseline.name}")
        return 0
    sys.stdout.writelines(
        difflib.unified_diff(
            recorded.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=f"baseline/{args.baseline.name}",
            tofile="current",
        )
    )
    print(
        f"FAIL: the {args.package} public API differs from {args.baseline}. "
        f"For an intended change, run `{UPDATE_HINT}` in langs/python and commit the "
        "baseline; a removed or changed member needs a major version bump "
        "(CONTRIBUTING.md).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
