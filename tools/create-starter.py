#!/usr/bin/env python3
"""Generate a VMx application starter outside the checkout and verify it.

The generator copies the version-free template files from
``starters/<channel>/``, renders the version-bearing files (``package.json``
and ``README.md``), installs the exact public package from the registry, and
checks the result:

* the lockfile has no ``file:`` or ``link:`` references and resolves every
  package from the intended registry;
* ``npm ls`` reports the pinned VMx version;
* the tree holds exactly one copy of each deduplicated peer;
* the starter's smoke test and entry point exit 0.

It never publishes anything. The README is written last, after every check
passes, so its "verified" line is true.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STARTERS_ROOT = REPO_ROOT / "starters"
PACKAGE_NAME = "@thekaveh/vmx"
DEFAULT_REGISTRY = "https://registry.npmjs.org/"
UPGRADE_GUIDE_URL = (
    "https://github.com/thekaveh/VMx/blob/main/docs/content/getting-started/upgrading-typescript.md"
)
# Packages that must resolve to one physical copy. VMx declares rxjs as a peer;
# a second copy splits Observable identity between VMx and the app.
DEDUPLICATED_PACKAGES = (PACKAGE_NAME, "rxjs")
CHANNELS = ("typescript-node",)
# The tracked template files per channel. Only these are copied, so build
# output or a stale lockfile from a local run can never reach a starter.
TEMPLATE_FILES = {
    "typescript-node": (
        ".gitignore",
        "src/main.ts",
        "src/notes.ts",
        "test/smoke.test.ts",
        "tsconfig.json",
    ),
}
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_LOCAL_SPEC_RE = re.compile(r"^(?:file|link):")


class StarterError(RuntimeError):
    """A starter check failed."""


def require_version(version: str) -> None:
    """Reject anything except an exact X.Y.Z release version."""
    if _SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"expected an exact X.Y.Z release version, received {version!r}")


def template_dir(channel: str) -> Path:
    """Return the tracked template directory for a channel."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown starter channel {channel!r}; expected one of {CHANNELS}")
    return STARTERS_ROOT / channel


def template_files(channel: str) -> list[Path]:
    """Return the allowlisted template files, relative to the channel directory.

    Raise if a listed file is missing or if the directory holds any other file.
    """
    root = template_dir(channel)
    expected = {Path(name) for name in TEMPLATE_FILES[channel]}
    present = {path.relative_to(root) for path in root.rglob("*") if path.is_file()}
    missing = sorted(path.as_posix() for path in expected - present)
    extra = sorted(path.as_posix() for path in present - expected)
    if missing or extra:
        raise StarterError(
            f"template {root} does not match its allowlist: "
            f"missing {missing or 'nothing'}, unexpected {extra or 'nothing'}"
        )
    return sorted(expected)


def _is_inside(path: Path, root: Path) -> bool:
    """Report whether `path` or an existing ancestor is the same directory as `root`.

    The check compares file identity, not strings, so a case-insensitive file
    system cannot hide the checkout behind a differently cased path.
    """
    try:
        root_status = root.stat()
    except OSError:
        return False
    root_id = (root_status.st_dev, root_status.st_ino)
    for candidate in (path, *path.parents):
        try:
            status = candidate.stat()
        except OSError:
            continue
        if (status.st_dev, status.st_ino) == root_id:
            return True
    return False


def validate_target(target: Path, repo_root: Path = REPO_ROOT) -> Path:
    """Return the resolved target, or raise if it is unsafe to generate into.

    The target must lie outside the checkout and must be empty or absent, so
    no workspace, path dependency or stray file can leak into the starter.
    """
    resolved = target.expanduser().resolve()
    root = repo_root.resolve()
    if resolved == root or resolved.is_relative_to(root) or _is_inside(resolved, root):
        raise StarterError(f"target {resolved} is inside the VMx checkout {root}")
    if resolved.exists():
        if not resolved.is_dir():
            raise StarterError(f"target {resolved} exists and is not a directory")
        if any(resolved.iterdir()):
            raise StarterError(f"target {resolved} is not empty")
    return resolved


def render_package_json(version: str) -> str:
    """Render the starter manifest with the exact VMx pin."""
    require_version(version)
    manifest = {
        "name": "vmx-starter-typescript-node",
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "engines": {"node": ">=22"},
        "scripts": {
            "build": "tsc -p tsconfig.json",
            "start": "npm run build && node dist/src/main.js",
            "test": "npm run build && node --test dist/test/smoke.test.js",
        },
        "dependencies": {
            PACKAGE_NAME: version,
            "rxjs": "^7.8.0",
        },
        "devDependencies": {
            "@types/node": "^22.0.0",
            "typescript": "^6.0.3",
        },
    }
    return json.dumps(manifest, indent=2) + "\n"


def render_readme(version: str, *, node_version: str, npm_version: str, platform_name: str) -> str:
    """Render the starter README that names the verified version."""
    require_version(version)
    return f"""# VMx TypeScript Node starter

A small Node application on `{PACKAGE_NAME}`. It builds a notebook of notes,
edits a note, saves it with a command, recovers from a store error and disposes
everything in order.

## Verified version

This starter was generated and verified with `{PACKAGE_NAME}` **{version}**
from the public npm registry on Node {node_version}, npm {npm_version}
({platform_name}).

## Prerequisites

- Node.js 22 or later. The VMx package itself supports Node 20.5 or later,
  but Node 20 is past its end of life.
- npm 10 or later.

## Commands

```bash
npm install   # already run by the generator
npm test      # compile, then run test/smoke.test.ts
npm start     # compile, then run src/main.ts
```

## Layout

| Path                  | Purpose                                                    |
| --------------------- | ---------------------------------------------------------- |
| `src/notes.ts`        | Note model, in-memory store, notebook VM and save command  |
| `src/main.ts`         | Runs the flow once and prints each step                    |
| `test/smoke.test.ts`  | Asserts construct, edit, command, error and dispose        |

## Dependencies

- `{PACKAGE_NAME}` is pinned to the exact version `{version}`.
- `rxjs` is a peer dependency of VMx. Keep one copy in the tree:
  `npm ls rxjs` must show a single version.
- Commit `package-lock.json` so every install resolves the same tree.

## Upgrading

1. Read the upgrade guide: {UPGRADE_GUIDE_URL}
1. Change the `{PACKAGE_NAME}` pin in `package.json` to the new exact version.
1. Run `npm install`, then `npm test`. The smoke test fails if the installed
   version differs from the pin.
"""


def _which(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise StarterError(f"{name} is not on PATH")
    return path


def _remaining(deadline: float, maximum: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("starter generation exceeded its end-to-end timeout")
    return min(maximum, remaining)


def _run(args: list[str], *, cwd: Path, timeout: float) -> str:
    """Run a command, echo its output, and return stdout."""
    print(f"$ {' '.join([Path(args[0]).name, *args[1:]])}", flush=True)
    result = subprocess.run(
        args, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if result.returncode != 0:
        raise StarterError(f"{' '.join(args)} exited {result.returncode}")
    return result.stdout


def latest_version(npm: str, registry: str, *, timeout: float) -> str:
    """Return the version behind the registry's ``latest`` dist-tag."""
    result = subprocess.run(
        [npm, "view", PACKAGE_NAME, "version", "--json", "--registry", registry],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise StarterError(f"npm view {PACKAGE_NAME} failed: {result.stderr.strip()}")
    version = json.loads(result.stdout)
    if not isinstance(version, str):
        raise StarterError(f"npm view {PACKAGE_NAME} returned {version!r}")
    require_version(version)
    return version


def scan_lockfile(lock: Mapping[str, object], registry: str = DEFAULT_REGISTRY) -> list[str]:
    """Return every local or foreign reference in an npm v2/v3 lockfile."""
    issues: list[str] = []
    packages = lock.get("packages")
    if not isinstance(packages, dict) or "" not in packages:
        return ["package-lock.json has no lockfile v2/v3 'packages' map"]
    for key, entry in packages.items():
        if not isinstance(entry, dict):
            issues.append(f"{key or '<root>'}: entry is not an object")
            continue
        label = key or "<root>"
        if entry.get("link") is True:
            issues.append(f"{label}: is a link to {entry.get('resolved')!r}")
        for field in ("dependencies", "devDependencies", "optionalDependencies"):
            specs = entry.get(field)
            if isinstance(specs, dict):
                issues.extend(
                    f"{label}: {field}.{name} uses {spec!r}"
                    for name, spec in specs.items()
                    if isinstance(spec, str) and _LOCAL_SPEC_RE.match(spec)
                )
        if key == "":
            continue
        resolved = entry.get("resolved")
        version = entry.get("version")
        if isinstance(version, str) and _LOCAL_SPEC_RE.match(version):
            issues.append(f"{label}: version {version!r} is a local reference")
        if not isinstance(resolved, str):
            if entry.get("link") is not True:
                issues.append(f"{label}: has no resolved registry URL")
        elif not resolved.startswith(registry):
            issues.append(f"{label}: resolved from {resolved!r}, not {registry}")
    return issues


def count_copies(lock: Mapping[str, object], name: str) -> list[str]:
    """Return every install location of a package in an npm v2/v3 lockfile."""
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        return []
    suffix = f"node_modules/{name}"
    return sorted(key for key in packages if key == suffix or key.endswith(f"/{suffix}"))


def resolved_version(npm_ls: Mapping[str, object], name: str) -> str | None:
    """Return the top-level resolved version from ``npm ls --json`` output."""
    dependencies = npm_ls.get("dependencies")
    if not isinstance(dependencies, dict):
        return None
    entry = dependencies.get(name)
    if not isinstance(entry, dict):
        return None
    version = entry.get("version")
    return version if isinstance(version, str) else None


def write_template(channel: str, version: str, target: Path) -> list[Path]:
    """Copy the template files and render the manifest into ``target``."""
    source = template_dir(channel)
    written: list[Path] = []
    for relative in template_files(channel):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
        written.append(relative)
    (target / "package.json").write_text(render_package_json(version), encoding="utf-8")
    written.append(Path("package.json"))
    return sorted(written)


def verify_typescript_node(
    target: Path, version: str, *, npm: str, registry: str, deadline: float
) -> dict[str, list[str]]:
    """Install the starter from the registry and run every clean-room check."""
    _run(
        [npm, "install", "--registry", registry, "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=target,
        timeout=_remaining(deadline, 300),
    )
    lock = json.loads((target / "package-lock.json").read_text(encoding="utf-8"))
    issues = scan_lockfile(lock, registry)
    if issues:
        raise StarterError("lockfile is not clean-room:\n- " + "\n- ".join(issues))

    listing = json.loads(_run([npm, "ls", "--json"], cwd=target, timeout=_remaining(deadline, 120)))
    installed = resolved_version(listing, PACKAGE_NAME)
    if installed != version:
        raise StarterError(f"npm ls resolved {PACKAGE_NAME}@{installed}, expected {version}")

    copies = {name: count_copies(lock, name) for name in DEDUPLICATED_PACKAGES}
    duplicated = {name: paths for name, paths in copies.items() if len(paths) != 1}
    if duplicated:
        raise StarterError(f"expected exactly one copy of each peer, found {duplicated}")

    _run([npm, "test"], cwd=target, timeout=_remaining(deadline, 300))
    _run([npm, "start"], cwd=target, timeout=_remaining(deadline, 120))
    return copies


def create_starter(
    channel: str,
    *,
    version: str | None = None,
    target: Path | None = None,
    registry: str = DEFAULT_REGISTRY,
    timeout_seconds: float = 900,
) -> Path:
    """Generate and verify a starter; return its directory."""
    deadline = time.monotonic() + timeout_seconds
    template_dir(channel)
    # Reject bad arguments before any tool lookup or network access.
    if version is not None:
        require_version(version)
    if target is not None:
        target = validate_target(target)
    npm = _which("npm")
    node = _which("node")
    if version is None:
        version = latest_version(npm, registry, timeout=_remaining(deadline, 120))
    if target is None:
        target = validate_target(Path(tempfile.mkdtemp(prefix=f"vmx-starter-{channel}-")))
    target.mkdir(parents=True, exist_ok=True)
    print(f"Generating {channel} starter for {PACKAGE_NAME}@{version} in {target}", flush=True)

    written = write_template(channel, version, target)
    print("Wrote " + ", ".join(path.as_posix() for path in written))
    copies = verify_typescript_node(target, version, npm=npm, registry=registry, deadline=deadline)

    node_version = _run([node, "--version"], cwd=target, timeout=_remaining(deadline, 30))
    npm_version = _run([npm, "--version"], cwd=target, timeout=_remaining(deadline, 30))
    (target / "README.md").write_text(
        render_readme(
            version,
            node_version=node_version.strip().removeprefix("v"),
            npm_version=npm_version.strip(),
            platform_name=f"{platform.system()} {platform.machine()}",
        ),
        encoding="utf-8",
    )
    print(f"OK: npm ls resolved {PACKAGE_NAME}@{version}, equal to the pin")
    for name, paths in copies.items():
        print(f"OK: one copy of {name}: {paths[0]}")
    print("OK: lockfile has no file:/link: references and resolves only from " + registry)
    print(f"OK: npm test and npm start exited 0; starter kept at {target}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--channel", choices=CHANNELS, default=CHANNELS[0])
    parser.add_argument(
        "--version", help="exact @thekaveh/vmx version (default: the npm latest tag)"
    )
    parser.add_argument(
        "--target",
        type=Path,
        help="empty directory outside the checkout (default: a new temporary directory)",
    )
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--timeout", type=float, default=900, dest="timeout_seconds")
    args = parser.parse_args(argv)
    try:
        create_starter(
            args.channel,
            version=args.version,
            target=args.target,
            registry=args.registry,
            timeout_seconds=args.timeout_seconds,
        )
    except (
        OSError,
        StarterError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"ERROR: starter generation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
