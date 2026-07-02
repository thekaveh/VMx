import struct
import zlib
from pathlib import Path

from docs.validate_diagrams import png_size, validate


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
    registry.write_text(
        '[{"id":"one","title":"One","html":"one.html","svg":"one.svg","png":"one.png","referencedBy":["docs/site/page.md"]}]',
        encoding="utf-8",
    )

    assert validate(tmp_path, registry) == []
    assert validate(tmp_path, registry, assets_only=True) == []


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
    registry.write_text(
        '[{"id":"one","title":"One","html":"one.html","svg":"one.svg","png":"one.png","referencedBy":["docs/site/page.md"]}]',
        encoding="utf-8",
    )

    assert validate(tmp_path, registry) == [
        "one: PNG is not landscape (1800x3200)",
        "one: PNG width 1800 is below 2400px",
    ]


def test_validate_reports_missing_reference_file(tmp_path: Path) -> None:
    diagrams = tmp_path / "docs" / "assets" / "diagrams"
    diagrams.mkdir(parents=True)
    (diagrams / "one.html").write_text("<html></html>", encoding="utf-8")
    (diagrams / "one.svg").write_text("<svg></svg>", encoding="utf-8")
    write_png(diagrams / "one.png", 3200, 1800)
    registry = diagrams / "diagram-registry.json"
    registry.write_text(
        '[{"id":"one","title":"One","html":"one.html","svg":"one.svg","png":"one.png","referencedBy":["docs/site/page.md"]}]',
        encoding="utf-8",
    )

    assert validate(tmp_path, registry) == ["one: missing reference file docs/site/page.md"]
