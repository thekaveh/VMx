"""Entry point — ``python -m vmx_inspector``."""

from __future__ import annotations

from vmx_inspector.app import VMxInspectorApp


def main() -> None:
    VMxInspectorApp().run()


if __name__ == "__main__":
    main()
