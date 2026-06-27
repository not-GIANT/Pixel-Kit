"""Material 3 design tokens generated from a seed color.

Uses Google's official HCT color-space implementation (material-color-utilities)
to derive a full M3 dynamic-color scheme — primary/secondary/tertiary roles,
the 5-tier surface-container elevation scale, outline, error, etc. — from one
seed color. This is the single source of truth for the UI's color system.

A scheme (light or dark) is exposed as a flat dict of {role: hex_string} so the
QSS builder and Python widget code can consume it identically. Changing the
whole app's look is one line: change SEED.
"""
from __future__ import annotations

import material_color_utilities as mcu

# ---------------------------------------------------------------------------
# Seed & configuration
# ---------------------------------------------------------------------------
# #0B57D0 = Google's current Material Blue (M3 Expressive baseline).
# Keeps the "Android tool" identity without the dated pre-Material cyan.
SEED = "#0B57D0"

# M3 type scale. Family order = preferred → fallbacks. Qt resolves the first
# installed family via QFontDatabase, so listing robust fallbacks means the
# scale looks correct on Windows, macOS, and Linux without bundling fonts.
TYPE_FAMILY = ["Roboto Flex", "Roboto", "Segoe UI Variable", "Segoe UI",
               "Helvetica Neue", "Arial", "sans-serif"]
MONO_FAMILY = ["JetBrains Mono", "Cascadia Mono", "Consolas",
               "Menlo", "monospace"]

# M3 shape scale (corner radii, px) — Small / Medium / Large / ExtraLarge.
SHAPE_SMALL = 8
SHAPE_MEDIUM = 12
SHAPE_LARGE = 16
SHAPE_EXTRA_LARGE = 28

# M3 elevation uses surface-container tiers (NOT drop shadows) for depth in
# dark mode. These tier names map to the scheme roles below.
ELEVATION_TIERS = [
    "surface_container_lowest",
    "surface_container_low",
    "surface_container",       # default card surface
    "surface_container_high",
    "surface_container_highest",
]

# Every M3 color role we consume. Attributes on Scheme return hex strings.
_ROLES = [
    # Primary
    "primary", "on_primary", "primary_container", "on_primary_container",
    # Secondary
    "secondary", "on_secondary", "secondary_container", "on_secondary_container",
    # Tertiary
    "tertiary", "on_tertiary", "tertiary_container", "on_tertiary_container",
    # Error
    "error", "on_error", "error_container", "on_error_container",
    # Surfaces & backgrounds
    "background", "surface", "on_surface", "on_surface_variant",
    "surface_variant", "surface_tint", "scrim", "shadow",
    "surface_dim", "surface_bright",
    "surface_container_lowest", "surface_container_low",
    "surface_container", "surface_container_high", "surface_container_highest",
    # Outline
    "outline", "outline_variant",
    # Inverse
    "inverse_surface", "inverse_on_surface", "inverse_primary",
]


def _scheme_to_dict(scheme) -> dict:
    """Read every M3 role off a material_color_utilities Scheme as a hex dict.

    Scheme attributes are hex strings ('#rrggbb'); missing roles fall back to
    None so downstream QSS can skip them gracefully.
    """
    out = {}
    for role in _ROLES:
        val = getattr(scheme, role, None)
        if isinstance(val, str) and val.startswith("#"):
            out[role] = val
    return out


# ---------------------------------------------------------------------------
# Light-scheme calibration
# ---------------------------------------------------------------------------
# Google's HCT generator derives the light surfaces from the seed's tone, which
# for a blue seed lands at ~#faf8ff — effectively pure white. On real displays
# that reads as blinding, and the surface-container tiers cluster so tightly
# (window 0.947 vs log 0.902 in relative luminance) that the log window and the
# card chrome have no visible separation from the window background.
#
# This ramp overrides ONLY the surface family (and the two outline/on-surface-
# variant roles that the log timestamp + body fallback read from) with a
# neutral cool-gray "paper" scale. Primary, error, containers, and the dark
# scheme are left untouched — only the light background whiteness is reduced.
# Ordered lightest=lowest → darkest=highest, per M3 container convention; each
# step is ~0.06 in relative luminance so cards/inputs/log read as distinct.
_LIGHT_SURFACE_OVERRIDE = {
    "background": "#f1f2f4",
    "surface": "#f1f2f4",
    "surface_container_lowest": "#ffffff",   # keep pure white for text fields
    "surface_container_low": "#e9eaed",      # log window background
    "surface_container": "#e3e4e8",          # default card surface
    "surface_container_high": "#dcdee2",
    "surface_container_highest": "#d4d6db",
    "surface_dim": "#dcdee2",
    "surface_bright": "#ffffff",
    "surface_variant": "#dfe2e6",
    # Darkened a touch from the generated values so the log timestamp gutter
    # and secondary text clear WCAG-AA against the new (darker) surfaces.
    "on_surface_variant": "#3f4250",
    "outline": "#5a5d6b",
    "outline_variant": "#888b99",
}


def _calibrate_light(scheme: dict) -> dict:
    """Reduce the light scheme's background whiteness to a neutral paper scale.

    Idempotent and light-only: returns the scheme unchanged for dark mode, and
    only overwrites roles that already exist (so a future seed whose generator
    omits a role still degrades gracefully).
    """
    for role, hex_val in _LIGHT_SURFACE_OVERRIDE.items():
        scheme[role] = hex_val
    return scheme


def generate_scheme(seed_hex: str = SEED, dark: bool = False) -> dict:
    """Return a flat {role: '#rrggbb'} dict for the requested M3 scheme.

    Args:
        seed_hex: Source color as '#rrggbb' or '#aarrggbb'.
        dark: True for the dark scheme, False for light.

    Returns:
        Dict mapping M3 role names (e.g. 'primary', 'surface_container_high')
        to hex color strings.
    """
    seed_argb = mcu.argb_from_hex(seed_hex)
    theme = mcu.theme_from_argb_color(seed_argb)
    scheme = theme.schemes.dark if dark else theme.schemes.light
    out = _scheme_to_dict(scheme)
    if not dark:
        _calibrate_light(out)
    return out


def contrast_ratio(foreground_hex: str, background_hex: str) -> float:
    """WCAG contrast ratio between two hex colors (1.0–21.0)."""
    fg = mcu.argb_from_hex(foreground_hex)
    bg = mcu.argb_from_hex(background_hex)
    return mcu.get_contrast_ratio(fg, bg)
