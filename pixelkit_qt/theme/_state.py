"""Active-scheme state, isolated to avoid a circular import.

The package __init__ imports `manager`, and `manager` needs to publish the
active scheme on every apply(). Putting the state in this leaf module means
both can import it without a cycle (neither imports the other transitively
through here).

`active_scheme()` returns the most recently applied M3 scheme dict so widgets
that paint their own colors (dialogs, popups) can read the live scheme without
holding a ThemeManager reference. QSS does NOT populate QPalette, so this is
the canonical way for non-QSS code to get theme-aware colors.
"""
from __future__ import annotations

_active_scheme: dict = {}


def active_scheme() -> dict:
    """Return the most recently applied M3 scheme dict (role -> '#rrggbb').

    Empty until the ThemeManager has applied once. Callers should provide their
    own fallbacks for any role they consume, so a pre-theme paint doesn't crash.
    """
    return _active_scheme


def set_active_scheme(scheme: dict) -> None:
    """Record the active scheme (called by ThemeManager.apply)."""
    global _active_scheme
    _active_scheme = scheme or {}
