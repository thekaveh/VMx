"""ThemeModel — pure-data record for the active app theme.

See ``spec/proposals/2026-06-02-theme-vm-scenario.md`` §3 for the canonical
model shape. ``ThemeModel`` is the Textual-flavor implementation of that
contract: a frozen ``dataclass`` with the four colour / scale fields plus the
``follows_system`` flag.

Three canonical presets are exposed as module-level constants:
:data:`DARK_PRESET`, :data:`LIGHT_PRESET`, :data:`HIGH_CONTRAST_PRESET`. The
``DARK_PRESET`` mirrors the palette baked into ``views/theme.tcss`` today
(``#0E1320`` bg / ``#E6EAF2`` text / ``#4F8CD9`` accent / ``#141B2D`` panel /
``#7A86A1`` muted text); the light preset flips the background to ``#F4F7FC``
and the foreground to ``#1A1F2E`` while keeping the accent for brand
consistency; the high-contrast preset uses pure black/white with a bright
yellow accent for AA-contrast conformance.

The full preset registry is exposed via :data:`PRESETS` so the VM layer can
look presets up by name without re-encoding the table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

# Font-scale clamp range — per scenario §3 (``[0.75..1.75]``).
FONT_SCALE_MIN: Final[float] = 0.75
FONT_SCALE_MAX: Final[float] = 1.75

# Named preset string-literal type — re-used by ``ThemeVM`` command APIs.
ThemeName = Literal["dark", "light", "high-contrast", "system"]


@dataclass(frozen=True, slots=True)
class ThemeModel:
    """Immutable theme record.

    Parameters
    ----------
    name:
        Preset identifier — one of ``"dark"``, ``"light"``, ``"high-contrast"``,
        ``"system"``. ``"system"`` is the deferred-to-host pseudo-preset; the
        adapter resolves it at apply-time.
    accent_color:
        Brand accent colour, encoded as a ``#RRGGBB`` hex string. The VM does
        no normalisation — colour parsing happens in the adapter.
    bg_color:
        Screen background colour, ``#RRGGBB``.
    text_color:
        Default foreground / text colour, ``#RRGGBB``.
    panel_color:
        Surface colour for panes (notebooks / notes / form), ``#RRGGBB``. Maps
        to the ``$panel`` CSS variable in the Textual adapter.
    muted_text_color:
        De-emphasised label colour (pane titles, status bar dim labels), maps
        to the ``$text-muted`` CSS variable.
    font_scale_factor:
        Multiplier on the baseline font size. ``1.0`` is the baseline; the VM
        clamps to ``[FONT_SCALE_MIN..FONT_SCALE_MAX]``.
    high_contrast:
        ``True`` when the high-contrast adjustment is active. Independent of
        ``name``: a user may toggle high-contrast on top of either the dark or
        light preset.
    follows_system:
        ``True`` when the active theme mirrors the host's system theme. Mutated
        only by :meth:`ThemeVM.follow_system_command` /
        :meth:`ThemeVM.set_theme_command` per scenario §4.
    """

    name: ThemeName
    accent_color: str
    bg_color: str
    text_color: str
    panel_color: str
    muted_text_color: str
    font_scale_factor: float = 1.0
    high_contrast: bool = False
    follows_system: bool = False


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

# Mirrors the palette currently baked into ``views/theme.tcss``. The four
# values that the ThemeAdapter rewrites at runtime (``$bg`` / ``$accent`` /
# ``$panel`` / ``$text-muted``) live on the model so a future Light/HC swap
# becomes a no-CSS-edit operation.
DARK_PRESET: Final[ThemeModel] = ThemeModel(
    name="dark",
    accent_color="#4F8CD9",
    bg_color="#0E1320",
    text_color="#E6EAF2",
    panel_color="#141B2D",
    muted_text_color="#7A86A1",
)

# Flips bg → light, text → dark; keeps the accent so brand identity carries
# across presets. Panel / muted are tuned for the lighter surface.
LIGHT_PRESET: Final[ThemeModel] = ThemeModel(
    name="light",
    accent_color="#4F8CD9",
    bg_color="#F4F7FC",
    text_color="#1A1F2E",
    panel_color="#FFFFFF",
    muted_text_color="#5A6178",
)

# Pure black / white with a bright yellow accent — AA-contrast safe.
HIGH_CONTRAST_PRESET: Final[ThemeModel] = ThemeModel(
    name="high-contrast",
    accent_color="#FFD600",
    bg_color="#000000",
    text_color="#FFFFFF",
    panel_color="#000000",
    muted_text_color="#FFFFFF",
    high_contrast=True,
)


# Public registry — name → preset. The ``"system"`` pseudo-preset is not
# included: it is resolved at command-execution time by ``ThemeVM`` from the
# host-current snapshot (per scenario §3 / §4 ``follow_system_command``).
PRESETS: Final[dict[str, ThemeModel]] = {
    "dark": DARK_PRESET,
    "light": LIGHT_PRESET,
    "high-contrast": HIGH_CONTRAST_PRESET,
}
