#!/usr/bin/env python3
"""Build and run VMx from a local .crate or the public crates.io registry."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

PACKAGE_NAME = "vmx-rs"
LIBRARY_NAME = "vmx"
USER_AGENT = "VMx-release-verifier/1.0 (https://github.com/thekaveh/VMx)"
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_RUST_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")


def _require_version(version: str) -> None:
    if _SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"expected an X.Y.Z release version, received {version!r}")


def _require_rust_version(version: str) -> None:
    if _RUST_VERSION_RE.fullmatch(version) is None:
        raise ValueError(f"invalid Rust version {version!r}")


def render_manifest(dependency: str, rust_version: str) -> str:
    """Render the disposable consumer manifest."""
    _require_rust_version(rust_version)
    return f'''[package]
name = "vmx-crates-smoke"
version = "0.0.0"
edition = "2021"
rust-version = "{rust_version}"
publish = false

[dependencies]
{dependency}
'''


def render_smoke(version: str) -> str:
    """Render lifecycle, command, namespace, and package-version probes."""
    _require_version(version)
    return f'''use std::sync::{{
    atomic::{{AtomicUsize, Ordering}},
    Arc,
}};

use vmx::{{Command, ComponentVm, MessageHub, NullDispatcher, RelayCommand, VmxResult, VERSION}};

fn main() -> VmxResult<()> {{
    assert_eq!(VERSION, "{version}");

    let vm = ComponentVm::with_services("crates-smoke", MessageHub::new(), NullDispatcher::new());
    vm.construct()?;
    assert!(vm.is_constructed());
    vm.destruct()?;
    assert!(!vm.is_constructed());
    vm.construct()?;

    let executions = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&executions);
    let command = RelayCommand::new(move || {{
        observed.fetch_add(1, Ordering::SeqCst);
    }});
    assert!(command.can_execute());
    command.execute();
    assert_eq!(executions.load(Ordering::SeqCst), 1);

    vm.dispose()?;
    println!("VMx crates.io smoke passed");
    Ok(())
}}
'''


def public_add_command(cargo: str, version: str) -> list[str]:
    """Return the exact-version cargo-add command used for public consumers."""
    _require_version(version)
    return [cargo, "add", f"{PACKAGE_NAME}@={version}"]


def _request_json(url: str) -> object | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _registry_has_version(version: str) -> bool:
    payload = _request_json(f"https://crates.io/api/v1/crates/{PACKAGE_NAME}/{version}")
    if not isinstance(payload, dict):
        return False
    released = payload.get("version")
    return isinstance(released, dict) and released.get("num") == version


def _docs_has_version(version: str) -> bool:
    request = urllib.request.Request(
        f"https://docs.rs/{PACKAGE_NAME}/{version}/{LIBRARY_NAME}/",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status == 200
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return False


def wait_for_public(
    version: str,
    timeout_seconds: float,
    *,
    interval_seconds: float = 10,
    crate_lookup: Callable[[str], bool] = _registry_has_version,
    docs_lookup: Callable[[str], bool] = _docs_has_version,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Poll until both the exact crate and its docs.rs build are available."""
    _require_version(version)
    deadline = clock() + timeout_seconds
    while True:
        crate_ready = crate_lookup(version)
        docs_ready = docs_lookup(version)
        if crate_ready and docs_ready:
            return
        if clock() >= deadline:
            missing = ", ".join(
                name
                for name, ready in (("crates.io", crate_ready), ("docs.rs", docs_ready))
                if not ready
            )
            raise TimeoutError(f"timed out waiting for {PACKAGE_NAME} {version} on {missing}")
        sleeper(interval_seconds)


def _run(args: list[str], *, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def _package(package_dir: Path, version: str, cargo: str) -> Path:
    tarball = package_dir / "target" / "package" / f"{PACKAGE_NAME}-{version}.crate"
    tarball.unlink(missing_ok=True)
    _run(
        [cargo, "package", "--locked", "--manifest-path", str(package_dir / "Cargo.toml")],
        cwd=package_dir,
    )
    if not tarball.is_file():
        raise ValueError(f"cargo package did not create {tarball}")
    return tarball


def _safe_extract(tarball: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(tarball, mode="r:gz") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root) or member.issym() or member.islnk():
                raise ValueError(f"unsafe crate archive member: {member.name}")
        archive.extractall(destination)


def find_extracted_crate(destination: Path, version: str) -> Path:
    """Return the exact extracted crate root or fail clearly."""
    _require_version(version)
    expected = destination / f"{PACKAGE_NAME}-{version}"
    if not expected.is_dir():
        raise ValueError(f"crate archive did not contain {expected.name}")
    return expected


def _toml_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def run_smoke(
    version: str,
    *,
    package_dir: Path | None = None,
    cargo: str = "cargo",
    rust_version: str = "1.88",
    poll_timeout: float = 1800,
    keep_directory: bool = False,
) -> Path | None:
    """Create, build, and run a disposable packaged or public consumer."""
    _require_version(version)
    _require_rust_version(rust_version)
    workdir = Path(tempfile.mkdtemp(prefix="vmx-rust-smoke-"))
    try:
        (workdir / "src").mkdir()
        if package_dir is None:
            wait_for_public(version, poll_timeout)
            (workdir / "Cargo.toml").write_text(render_manifest("", rust_version), encoding="utf-8")
            _run(public_add_command(cargo, version), cwd=workdir)
        else:
            package_dir = package_dir.resolve()
            tarball = _package(package_dir, version, cargo)
            extracted = workdir / "package"
            extracted.mkdir()
            _safe_extract(tarball, extracted)
            crate_root = find_extracted_crate(extracted, version)
            dependency = f'{PACKAGE_NAME} = {{ path = "{_toml_path(crate_root)}" }}'
            (workdir / "Cargo.toml").write_text(
                render_manifest(dependency, rust_version), encoding="utf-8"
            )

        (workdir / "src" / "main.rs").write_text(render_smoke(version), encoding="utf-8")
        _run([cargo, "tree", "-p", f"{PACKAGE_NAME}@{version}"], cwd=workdir)
        _run([cargo, "run", "--locked", "--quiet"], cwd=workdir)
        print(
            f"OK: Rust consumer verified {PACKAGE_NAME} {version} "
            f"with library namespace {LIBRARY_NAME}"
        )
        if keep_directory:
            print(f"Kept smoke consumer at {workdir}")
            return workdir
        return None
    finally:
        if not keep_directory:
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--rust-version", default="1.88")
    parser.add_argument("--poll-timeout", type=float, default=1800)
    parser.add_argument("--keep-directory", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_smoke(
            args.version,
            package_dir=args.package_dir,
            cargo=args.cargo,
            rust_version=args.rust_version,
            poll_timeout=args.poll_timeout,
            keep_directory=args.keep_directory,
        )
    except (
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"ERROR: Rust consumer smoke failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
