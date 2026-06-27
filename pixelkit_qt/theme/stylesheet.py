"""Material 3 QSS stylesheet generator.

Builds a complete Qt stylesheet string from an M3 scheme dict (see tokens.py).
Generating QSS in Python (rather than shipping a static .qss file) means a
seed change or light/dark toggle re-skins the entire app instantly — every
color is interpolated from the live M3 scheme.

QSS covers the common M3 components: surfaces, buttons (filled/tonal/outlined/
text), inputs (outlined fields, textareas), scrollbars, tabs, progress bars,
menus, tooltips, and dialogs.
"""
from __future__ import annotations

from . import tokens


def rgba(hex_color: str, alpha: float) -> str:
    """Convert '#rrggbb' + alpha(0..1) to an rgba() color string.

    Public so theme-aware widgets can build translucent overlays from scheme
    roles instead of hardcoding colors. Tolerates a leading alpha byte
    ('#aarrggbb') by ignoring it.
    """
    h = hex_color.lstrip("#")
    if len(h) == 8:
        h = h[2:]
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# Back-compat alias for the original private name used inside this module.
_with_alpha = rgba


def build_qss(scheme: dict) -> str:
    """Render a full M3 QSS stylesheet from an M3 scheme dict.

    Args:
        scheme: output of tokens.generate_scheme().

    Returns:
        A QSS string ready for QApplication.setStyleSheet().
    """
    s = scheme
    # Helpful aliases
    bg = s.get("surface", "#ffffff")
    on_bg = s.get("on_surface", "#000000")
    surface_var = s.get("surface_variant", bg)
    outline = s.get("outline", "#888888")
    outline_var = s.get("outline_variant", "#cccccc")
    primary = s.get("primary", "#0061e6")
    on_primary = s.get("on_primary", "#ffffff")
    primary_container = s.get("primary_container", primary)
    on_primary_container = s.get("on_primary_container", "#000000")
    error = s.get("error", "#b00020")
    on_error = s.get("on_error", "#ffffff")
    card = s.get("surface_container", bg)
    card_high = s.get("surface_container_high", card)
    card_highest = s.get("surface_container_highest", card_high)
    card_low = s.get("surface_container_low", bg)

    # State-layer overlays (M3: hover 8%, focus 10%, pressed 10-16%).
    hover_on_surface = _with_alpha(on_bg, 0.08)
    pressed_on_surface = _with_alpha(on_bg, 0.12)
    hover_on_primary = _with_alpha(on_primary, 0.08)
    disabled_text = _with_alpha(on_bg, 0.38)

    fam = ", ".join(tokens.TYPE_FAMILY)
    mono = ", ".join(tokens.MONO_FAMILY)
    sm, md, lg, xl = (tokens.SHAPE_SMALL, tokens.SHAPE_MEDIUM,
                      tokens.SHAPE_LARGE, tokens.SHAPE_EXTRA_LARGE)

    return f"""
/* ============================================================
   Material 3 stylesheet — generated from M3 scheme
   Seed: {tokens.SEED}   is_dark={scheme.get('is_dark', False)}
   ============================================================ */

* {{
    font-family: {fam};
    font-size: 13px;
    color: {on_bg};
}}

QWidget#Root, QMainWindow, QDialog {{
    background-color: {bg};
}}

/* ---------- Surfaces / cards ---------- */
QFrame[card="true"] {{
    background-color: {card};
    border: 1px solid {outline_var};
    border-radius: {md}px;
}}
/* Hovered card — M3 state-layer: primary-tinted border + brightened surface. */
QFrame[card="true"][hovered="true"] {{
    border: 1px solid {primary};
    background-color: {card_high};
}}
QFrame[card="high"] {{
    background-color: {card_high};
    border: 1px solid {outline_var};
    border-radius: {md}px;
}}

/* ---------- Filled button (default) ---------- */
/* Action buttons share one geometry across all variants: identical padding,
   corner radius, and a fixed height, so hover/variant state never changes a
   button's size and every button in every card lines up on the same grid.
   The 1px border is reserved (transparent) in the resting state so the hover
   border can appear without shifting the layout by a pixel. */
QPushButton {{
    background-color: {primary};
    color: {on_primary};
    border: 1px solid transparent;
    border-radius: {sm}px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    background-color: {primary};
    /* M3 state layer via a translucent overlay — approximated with a border */
    border: 1px solid {hover_on_primary};
}}
QPushButton:pressed {{
    background-color: {primary};
    border: 1px solid {hover_on_primary};
}}
QPushButton:disabled {{
    background-color: transparent;
    color: {disabled_text};
    border: 1px solid {outline_var};
}}

/* ---------- Outlined button (objectName convention) ---------- */
QPushButton[variant="outlined"] {{
    background-color: transparent;
    color: {primary};
    border: 1px solid {outline};
    border-radius: {sm}px;
    padding: 6px 14px;
}}
QPushButton[variant="outlined"]:hover {{
    background-color: {_with_alpha(primary, 0.08)};
    border: 1px solid {outline};
}}
QPushButton[variant="outlined"]:pressed {{
    background-color: {_with_alpha(primary, 0.12)};
}}

/* ---------- Text button ---------- */
QPushButton[variant="text"] {{
    background-color: transparent;
    color: {primary};
    border: 1px solid transparent;
    padding: 6px 10px;
}}
QPushButton[variant="text"]:hover {{
    background-color: {_with_alpha(primary, 0.08)};
    border: 1px solid transparent;
    border-radius: {sm}px;
}}

/* ---------- Tonal button (secondary action) ---------- */
QPushButton[variant="tonal"] {{
    background-color: {primary_container};
    color: {on_primary_container};
    border: 1px solid transparent;
    border-radius: {sm}px;
    padding: 6px 14px;
}}
QPushButton[variant="tonal"]:hover {{
    border: 1px solid {hover_on_primary};
}}

/* ---------- Danger button ---------- */
QPushButton[variant="danger"] {{
    background-color: {error};
    color: {on_error};
    border: 1px solid transparent;
    border-radius: {sm}px;
    padding: 6px 14px;
}}
QPushButton[variant="danger"]:hover {{
    border: 1px solid {_with_alpha(on_error, 0.12)};
}}

/* ---------- Outlined text field (M3) ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background-color: transparent;
    color: {on_bg};
    border: 1px solid {outline};
    border-radius: {sm}px;
    padding: 6px 10px;
    selection-background-color: {_with_alpha(primary, 0.20)};
    selection-color: {on_bg};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus {{
    border: 2px solid {primary};
    padding: 5px 9px;  /* -1px to compensate for the thicker border */
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: {disabled_text};
    border: 1px dashed {outline};
}}

/* Placeholder text */
QLineEdit {{ placeholder-text-color: {_with_alpha(on_bg, 0.60)}; }}

/* ---------- Console / log view (read-only terminal) ---------- */
/* Slightly smaller (11px) mono face for a denser, professional diagnostic
   console feel, while staying readable in both light and dark themes. */
QPlainTextEdit#LogView {{
    background-color: {card_low};
    color: {on_bg};
    font-family: {mono};
    font-size: 11px;
    border: 1px solid {outline_var};
    border-radius: {md}px;
    padding: 8px;
}}

/* ---------- Scrollbars (thin, M3) ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {outline};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {_with_alpha(on_bg, 0.30)};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {outline};
    border-radius: 4px;
    min-width: 32px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ---------- Progress bar (M3 linear, rounded) ---------- */
QProgressBar {{
    background-color: {_with_alpha(primary, 0.15)};
    border: none;
    border-radius: {sm}px;
    text-align: center;
    color: transparent;  /* hide the % text (font-size:0 logs a warning) */
    height: 6px;
}}
QProgressBar::chunk {{
    background-color: {primary};
    border-radius: {sm}px;
}}

/* ---------- Tabs (top, M3 styled) ---------- */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {on_bg};
    border: none;
    border-bottom: 3px solid transparent;
    padding: 10px 18px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    border-bottom: 3px solid {primary};
    color: {primary};
}}
QTabBar::tab:hover:!selected {{
    background-color: {hover_on_surface};
    border-radius: {sm}px;
}}

/* ---------- Menu bar / menus ---------- */
QMenuBar {{
    background-color: {bg};
    color: {on_bg};
    border-bottom: 1px solid {outline_var};
}}
QMenuBar::item:selected {{
    background-color: {hover_on_surface};
    border-radius: {sm}px;
}}
QMenu {{
    background-color: {card_high};
    border: 1px solid {outline_var};
    border-radius: {md}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 8px 24px 8px 16px;
    border-radius: {sm}px;
}}
QMenu::item:selected {{
    background-color: {hover_on_surface};
}}
QMenu::separator {{
    height: 1px;
    background: {outline_var};
    margin: 4px 8px;
}}

/* ---------- Status bar ---------- */
QStatusBar {{
    background-color: {card_low};
    color: {on_bg};
    border-top: 1px solid {outline_var};
}}

/* ---------- Tooltips (M3 style: rounded, on-surface-on-surface-variant) ---------- */
QToolTip {{
    background-color: {card_highest};
    color: {on_bg};
    border: 1px solid {outline_var};
    border-radius: {sm}px;
    padding: 6px 10px;
}}

/* ---------- Labels ---------- */
QLabel {{ background: transparent; }}
QLabel[role="title"]     {{ font-size: 20px; font-weight: 700; }}
QLabel[role="headline"]  {{ font-size: 16px; font-weight: 600; }}
QLabel[role="label-l"]   {{ font-size: 13px; font-weight: 600; }}
QLabel[role="label-m"]   {{ font-size: 11px; font-weight: 600; }}
QLabel[role="label-s"]   {{ font-size: 10px; font-weight: 600; }}
QLabel[role="body"]      {{ font-size: 13px; }}
QLabel[role="caption"]   {{ font-size: 11px; color: {s.get("on_surface_variant", on_bg)}; }}
QLabel[role="on_primary"]{{ color: {on_primary}; }}
QLabel[role="primary"]   {{ color: {primary}; }}

/* ---------- Splitters ---------- */
QSplitter::handle {{ background: {outline_var}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical   {{ height: 1px; }}

/* ---------- Checkboxes (M3) ---------- */
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 2px solid {outline};
    border-radius: 2px;
    background: transparent;
}}
QCheckBox::indicator:checked {{
    background: {primary};
    border: 2px solid {primary};
}}

/* ---------- Navigation rail (left vertical nav) ---------- */
QFrame#NavRail {{
    background-color: {card_low};
    border-right: 1px solid {outline_var};
}}
/* QToolButton-based rail items (icon-over-label via ToolButtonTextUnderIcon). */
QToolButton#NavItem {{
    background-color: transparent;
    color: {on_bg};
    border: none;
    border-radius: {lg}px;
    padding: 8px 4px;
    font-size: 10px;
    font-weight: 500;
}}
QToolButton#NavItem:hover {{
    background-color: {hover_on_surface};
}}
QToolButton#NavItem:checked {{
    /* M3 active-indicator: a pill filled with the primary-container tint. */
    background-color: {_with_alpha(primary, 0.14)};
    color: {primary};
    font-weight: 600;
}}

/* ---------- Category chips (filter pills) ---------- */
QPushButton#CategoryChip {{
    background-color: transparent;
    color: {on_bg};
    border: 1px solid {outline};
    border-radius: 8px;
    padding: 5px 14px;
    font-size: 12px;
}}
QPushButton#CategoryChip:hover {{
    background-color: {hover_on_surface};
}}
QPushButton#CategoryChip:checked {{
    background-color: {primary_container};
    color: {on_primary_container};
    border: 1px solid {primary_container};
    font-weight: 600;
}}

/* ---------- Partition list rows ---------- */
QFrame#PartitionRow {{
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {outline_var};
}}
QFrame#PartitionRow:hover {{
    background-color: {hover_on_surface};
    border-radius: 8px;
}}
"""
