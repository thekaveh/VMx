#!/usr/bin/env python3
"""Verify the exact allowlisted contents of the Rust crate package."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REQUIRED_PATHS = frozenset(
    """.cargo_vcs_info.json
CHANGELOG.md
Cargo.lock
Cargo.toml
Cargo.toml.orig
LICENSE
README.md
src/aggregate_change_stream.rs
src/aggregates.rs
src/async_resource_vm.rs
src/async_value.rs
src/capabilities.rs
src/discriminator.rs
src/dialogs.rs
src/fixtures/lifecycle-transitions.json
src/forms.rs
src/forwarding.rs
src/hierarchical.rs
src/lib.rs
src/notifications.rs
src/specialized_vms.rs
src/token_paging.rs
tests/conformance.rs
tests/conformance/aggregate_change_stream.rs
tests/conformance/aggregate_vm.rs
tests/conformance/async_resource_vm.rs
tests/conformance/builders.rs
tests/conformance/capabilities.rs
tests/conformance/collections.rs
tests/conformance/command_decorators.rs
tests/conformance/commands.rs
tests/conformance/component_vm.rs
tests/conformance/composite_vm.rs
tests/conformance/derived_properties.rs
tests/conformance/dialogs.rs
tests/conformance/discriminator.rs
tests/conformance/expandable.rs
tests/conformance/filtered_composite.rs
tests/conformance/form_model_hub_publication.rs
tests/conformance/forms.rs
tests/conformance/forwarding.rs
tests/conformance/group_vm.rs
tests/conformance/hierarchical.rs
tests/conformance/hierarchical_batch.rs
tests/conformance/lifecycle.rs
tests/conformance/localization.rs
tests/conformance/message_hub.rs
tests/conformance/modeled_crud.rs
tests/conformance/notifications.rs
tests/conformance/null_services.rs
tests/conformance/observable_list_replace_all.rs
tests/conformance/owned_resources.rs
tests/conformance/post_dispose_modeled_assignment.rs
tests/conformance/property_change.rs
tests/conformance/search_filter.rs
tests/conformance/subscribe_value.rs
tests/conformance/threading.rs
tests/conformance/tree_utils.rs
tests/conformance/vm_collection_move.rs""".splitlines()
)


def validate_paths(paths: set[str]) -> list[str]:
    """Return deterministic errors for missing or unexpected package paths."""
    errors = [f"missing required package file: {path}" for path in sorted(REQUIRED_PATHS - paths)]
    errors.extend(f"unexpected package file: {path}" for path in sorted(paths - REQUIRED_PATHS))
    return errors


def package_paths(package_dir: Path) -> set[str]:
    """Run Cargo's real package listing and return every included path."""
    result = subprocess.run(
        [
            "cargo",
            "package",
            "--manifest-path",
            str(package_dir / "Cargo.toml"),
            "--locked",
            "--list",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(paths) != len(set(paths)):
        raise ValueError("cargo package listed duplicate paths")
    return set(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "langs" / "rust",
    )
    args = parser.parse_args(argv)

    try:
        paths = package_paths(args.package_dir.resolve())
        errors = validate_paths(paths)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: unable to inspect Rust crate package: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.rstrip(), file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"OK: Rust crate package contains {len(paths)} allowlisted files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
