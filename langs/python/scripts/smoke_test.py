"""Smoke test for the installed vmx package.

Run from a clean venv that has only `vmx` and its runtime deps installed:

    pip install vmx==<expected_version>
    python langs/python/scripts/smoke_test.py [<expected_version>]

If <expected_version> is provided, the script asserts the installed
`vmx.__version__` matches it; otherwise it just prints the version.

Exit code 0 on success, non-zero on any failure.
"""

from __future__ import annotations

import sys


def main() -> int:
    from vmx import (
        ComponentVMBuilder,
        ConstructionStatus,
        MessageHub,
        NullDispatcher,
    )
    from vmx.__about__ import __min_spec_version__, __version__

    expected = sys.argv[1] if len(sys.argv) > 1 else None

    print(f"vmx.__version__ = {__version__}")
    print(f"vmx.__min_spec_version__ = {__min_spec_version__}")

    if expected is not None and __version__ != expected:
        print(
            f"FAIL: expected version {expected}, got {__version__}",
            file=sys.stderr,
        )
        return 1

    # Trivial ComponentVM lifecycle round-trip — Destructed → Constructed → Destructed → Disposed.
    hub = MessageHub()
    dispatcher = NullDispatcher()
    vm = (
        ComponentVMBuilder()
        .name("smoke")
        .hint("PyPI install smoke test")
        .services(hub, dispatcher)
        .build()
    )
    assert vm.status == ConstructionStatus.DESTRUCTED, (
        f"expected DESTRUCTED initial, got {vm.status}"
    )
    vm.construct()
    assert vm.status == ConstructionStatus.CONSTRUCTED, f"expected CONSTRUCTED, got {vm.status}"
    vm.destruct()
    assert vm.status == ConstructionStatus.DESTRUCTED, f"expected DESTRUCTED, got {vm.status}"
    vm.dispose()
    assert vm.status == ConstructionStatus.DISPOSED, f"expected DISPOSED, got {vm.status}"

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
