import json
import struct
import zlib
from pathlib import Path

from docs.validate_diagrams import main, png_size, validate


def write_png(path: Path, width: int, height: int) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(data)


def write_truncated_png(path: Path) -> None:
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR")


def write_registry(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_png_size_reads_dimensions(tmp_path: Path) -> None:
    png = tmp_path / "x.png"
    write_png(png, 3200, 1800)

    assert png_size(png) == (3200, 1800)


def test_validate_accepts_complete_landscape_triplet(tmp_path: Path) -> None:
    diagrams = tmp_path / "docs" / "assets" / "diagrams"
    diagrams.mkdir(parents=True)
    (diagrams / "one.html").write_text("<html></html>", encoding="utf-8")
    (diagrams / "one.svg").write_text("<svg></svg>", encoding="utf-8")
    write_png(diagrams / "one.png", 3200, 1800)
    ref = tmp_path / "docs" / "site" / "page.md"
    ref.parent.mkdir(parents=True)
    ref.write_text("![One](../assets/diagrams/one.svg)", encoding="utf-8")
    registry = diagrams / "diagram-registry.json"
    write_registry(
        registry,
        [
            {
                "id": "one",
                "title": "One",
                "html": "one.html",
                "svg": "one.svg",
                "png": "one.png",
                "referencedBy": ["docs/site/page.md"],
            }
        ],
    )

    assert validate(tmp_path, registry) == []
    assert validate(tmp_path, registry, assets_only=True) == []


def test_validate_reports_missing_diagram_assets(tmp_path: Path) -> None:
    diagrams = tmp_path / "docs" / "assets" / "diagrams"
    diagrams.mkdir(parents=True)
    registry = diagrams / "diagram-registry.json"
    write_registry(
        registry,
        [
            {
                "id": "one",
                "title": "One",
                "html": "one.html",
                "svg": "one.svg",
                "png": "one.png",
                "referencedBy": [],
            }
        ],
    )

    assert validate(tmp_path, registry, assets_only=True) == [
        f"one: missing {diagrams / 'one.html'}",
        f"one: missing {diagrams / 'one.svg'}",
        f"one: missing {diagrams / 'one.png'}",
    ]


def test_validate_reports_non_landscape_png(tmp_path: Path) -> None:
    diagrams = tmp_path / "docs" / "assets" / "diagrams"
    diagrams.mkdir(parents=True)
    (diagrams / "one.html").write_text("<html></html>", encoding="utf-8")
    (diagrams / "one.svg").write_text("<svg></svg>", encoding="utf-8")
    write_png(diagrams / "one.png", 1800, 3200)
    ref = tmp_path / "docs" / "site" / "page.md"
    ref.parent.mkdir(parents=True)
    ref.write_text("![One](../assets/diagrams/one.svg)", encoding="utf-8")
    registry = diagrams / "diagram-registry.json"
    write_registry(
        registry,
        [
            {
                "id": "one",
                "title": "One",
                "html": "one.html",
                "svg": "one.svg",
                "png": "one.png",
                "referencedBy": ["docs/site/page.md"],
            }
        ],
    )

    assert validate(tmp_path, registry) == [
        "one: PNG is not landscape (1800x3200)",
        "one: PNG width 1800 is below 2400px",
    ]


def test_validate_reports_truncated_png(tmp_path: Path) -> None:
    diagrams = tmp_path / "docs" / "assets" / "diagrams"
    diagrams.mkdir(parents=True)
    (diagrams / "one.html").write_text("<html></html>", encoding="utf-8")
    (diagrams / "one.svg").write_text("<svg></svg>", encoding="utf-8")
    write_truncated_png(diagrams / "one.png")
    registry = diagrams / "diagram-registry.json"
    write_registry(
        registry,
        [
            {
                "id": "one",
                "title": "One",
                "html": "one.html",
                "svg": "one.svg",
                "png": "one.png",
                "referencedBy": [],
            }
        ],
    )

    assert validate(tmp_path, registry, assets_only=True) == ["one: truncated PNG"]


def test_validate_reports_missing_reference_file(tmp_path: Path) -> None:
    diagrams = tmp_path / "docs" / "assets" / "diagrams"
    diagrams.mkdir(parents=True)
    (diagrams / "one.html").write_text("<html></html>", encoding="utf-8")
    (diagrams / "one.svg").write_text("<svg></svg>", encoding="utf-8")
    write_png(diagrams / "one.png", 3200, 1800)
    registry = diagrams / "diagram-registry.json"
    write_registry(
        registry,
        [
            {
                "id": "one",
                "title": "One",
                "html": "one.html",
                "svg": "one.svg",
                "png": "one.png",
                "referencedBy": ["docs/site/page.md"],
            }
        ],
    )

    assert validate(tmp_path, registry) == ["one: missing reference file docs/site/page.md"]


def test_validate_reports_site_diagram_link_that_resolves_to_wrong_output_path(
    tmp_path: Path,
) -> None:
    diagrams = tmp_path / "docs" / "assets" / "diagrams"
    diagrams.mkdir(parents=True)
    (diagrams / "one.html").write_text("<html></html>", encoding="utf-8")
    (diagrams / "one.svg").write_text("<svg></svg>", encoding="utf-8")
    write_png(diagrams / "one.png", 3200, 1800)
    ref = tmp_path / "docs" / "site" / "primitives" / "command-families.md"
    ref.parent.mkdir(parents=True)
    ref.write_text('<img src="../assets/diagrams/one.svg" />', encoding="utf-8")
    registry = diagrams / "diagram-registry.json"
    write_registry(
        registry,
        [
            {
                "id": "one",
                "title": "One",
                "html": "one.html",
                "svg": "one.svg",
                "png": "one.png",
                "referencedBy": ["docs/site/primitives/command-families.md"],
            }
        ],
    )

    assert validate(tmp_path, registry) == [
        "docs/site/primitives/command-families.md: diagram link ../assets/diagrams/one.svg "
        "resolves to site/primitives/assets/diagrams/one.svg, "
        "expected site/assets/diagrams/one.svg"
    ]


def test_main_reports_malformed_registry_errors(tmp_path: Path, capsys, monkeypatch) -> None:
    registry = tmp_path / "docs" / "assets" / "diagrams" / "diagram-registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        (
            '[{"id": 1, "title": "One", "html": "one.html", '
            '"png": "one.png", "referencedBy": "docs/site/page.md"}]'
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "validate_diagrams.py",
            "--root",
            str(tmp_path),
            "--registry",
            str(registry),
        ],
    )

    assert main() == 1
    assert capsys.readouterr().out == (
        "ERROR: registry[0].id: expected string, got int\n"
        "ERROR: registry[0]: missing required key 'svg'\n"
        "ERROR: registry[0].referencedBy: expected list[str], got str\n"
    )
