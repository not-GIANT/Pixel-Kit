"""Reusable M3 composite widgets used across views.

- ActionCard: an outlined card with a title, optional subtitle, and a grid of
  action buttons. The core building block of every operations view.
- LabeledField: a caption label above an input, for forms (push destination,
  package name, IMEI entry, etc.).
- SectionTitle: a styled label-large heading.

These keep view code declarative — a view is mostly a list of ActionCards.
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from .nav_rail import NavRail  # re-export for convenience

__all__ = ["ActionCard", "FitScrollArea", "LabeledField", "SectionTitle", "NavRail"]

# Shared action-button sizing tokens. Centralizing them here keeps every card's
# buttons at the same height so the action grids line up across cards regardless
# of label length or per-card button count. The QSS layer sets the base
# padding/radius; these are the layout-side constraints Qt honors for grid
# alignment (a fixed height → uniform rows).
#   - BTN_HEIGHT: every action button is exactly this tall (set on the widget).
# We deliberately do NOT set a minimum width on the buttons. A per-button
# minimum summed across two columns made each card's minSizeHint (~330-375px),
# so two cards side by side (~750px) overflowed the ~455px scroll viewport and
# clipped under the Command Matrix. Equal column stretch (set in ActionCard)
# already makes the two buttons in a row identical in width; the fixed height
# is what keeps the grids aligned across cards.
BTN_HEIGHT = 34


def equalize_card_heights(cards) -> None:
    """Make every ActionCard in *cards* the same height.

    Sets a shared minimum height (the tallest card's heightHint) on every card
    so the outer borders line up across the whole section — not just within a
    grid row. After this call:

      - All cards render at the same height (the tallest wins).
      - Buttons stay at their natural size, anchored at the top of each card
        (the per-card trailing spacer added by *append_bottom_spacer* absorbs
        the extra space). No button is stretched.
      - The fixed height token (BTN_HEIGHT) and equal column stretch still keep
        every button identical within and across cards.

    Safe to call before the widget is shown (the hint comes from the layout)
    and to re-run later (idempotent: it just resets every minimum to the
    current tallest hint).
    """
    for card in cards:
        card.setMinimumHeight(0)
    tallest = 0
    for card in cards:
        h = card.sizeHint().height()
        if h > tallest:
            tallest = h
    if tallest > 0:
        for card in cards:
            card.setMinimumHeight(tallest)


class SectionTitle(QLabel):
    """A label-large section heading (e.g. 'ADB Operations')."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("role", "headline")


class FitScrollArea(QScrollArea):
    """A QScrollArea that forces its content widget to exactly fit the viewport
    width — vertical scroll only, never horizontal.

    This is the canonical Qt fix for the "card grid wider than viewport" bug.
    With `widgetResizable=True`, Qt sizes the host to `max(viewport,
    host.minimumSizeHint)`. When the host's contents (cards) each report a
    ~440px sizeHint, two side-by-side cards push the host to ~880px and it
    overflows past the viewport, clipping under a sibling panel (here, the
    Command Matrix). The two mechanisms fight each other, so we instead disable
    widgetResizable and drive the host width ourselves from resizeEvent +
    the initial show: the host is forced to the viewport width and the inner
    grid reflows against the *visible* width. Equal column stretch then
    compresses the two cards to half the viewport each, so nothing ever renders
    wider than the scroll area. Content taller than the viewport scrolls
    vertically as usual.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # We manage the host width ourselves; widgetResizable would re-expand it
        # to minimumSizeHint and re-introduce the overflow.
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def setWidget(self, w):
        """Accept the content widget and size it to the viewport right away."""
        old_w = self.widget()
        if old_w is not None:
            old_w.removeEventFilter(self)
        super().setWidget(w)
        if w is not None:
            w.installEventFilter(self)
        self._refit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit()

    def _refit(self):
        """Set the host's width to the current viewport width (height kept from
        its sizeHint so tall content can scroll vertically)."""
        w = self.widget()
        if w is None:
            return
        vw = self.viewport().width()
        vh = w.sizeHint().height()
        # Keep the natural height (sum of all cards) so vertical scroll works;
        # only the width is clamped to the viewport.
        if w.width() != vw or w.height() != vh:
            w.resize(vw, vh)

    def eventFilter(self, watched, event):
        if watched == self.widget() and event.type() == QEvent.LayoutRequest:
            self._refit()
        return super().eventFilter(watched, event)


class ActionCard(QFrame):
    """An M3 outlined card grouping related action buttons.

    Hover paints a subtle state-layer tint + primary border (the QSS reacts to
    the [hovered="true"] dynamic property set in enterEvent/leaveEvent). This
    reads as the M3 elevation affordance cross-platform without drop shadows.

    Layout contract (so cards never clip/overflow and always align):
      - The card is Expanding/Preferred: it fills the column width its parent
        grid gives it, and — unlike a Fixed policy — can also grow *taller*
        than its own content. That is what lets equalize_card_heights() pull a
        shorter card down to match the tallest sibling so every card in a
        section renders at exactly the same height with borders that line up.
      - The inner button grid gives every column equal stretch (1:1), so the
        two buttons in a row are always the same width — equal to each other
        and to buttons in sibling cards — instead of sizing to label length.
      - Buttons get a shared fixed height + min-width (BTN_HEIGHT/BTN_MIN_WIDTH)
        so every button in every card is identical in height and never smaller
        than the grid floor.

    Usage:
        card = ActionCard("Power", "Reboot controls")
        card.add_button("System", on_system, tip="Reboot to OS")
        card.add_button("Bootloader", on_bl, variant="tonal")
    """

    def __init__(self, title: str, subtitle: str = "", columns: int = 2,
                 parent=None):
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("hovered", False)
        self.setAttribute(Qt.WA_Hover)
        # Preferred (not Fixed) vertically: lets a card grow down to match the
        # tallest sibling when equalize_card_heights() pins the group to a
        # shared minimum height, so every card in a section renders at the same
        # height with perfectly aligned borders. A card with no min height set
        # still shrinks to its natural content size, so non-equalized users
        # (e.g. the CPID form cards) are unaffected.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._columns = columns
        self._row = 0
        self._col = 0

        outer = QVBoxLayout(self)
        # Equal internal padding on all sides + consistent header spacing, so
        # every card shares the same chrome regardless of content.
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)

        title_lbl = QLabel(title)
        title_lbl.setProperty("role", "label-l")
        outer.addWidget(title_lbl)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setProperty("role", "caption")
            outer.addWidget(sub)

        self._grid = QGridLayout()
        self._grid.setSpacing(8)
        # Equal column stretch → both columns are always the same width. We do
        # NOT set column minimum widths here: doing so blocks the card from
        # shrinking when its scroll viewport is narrower than the sum of the
        # minimums, which was the root cause of the host overflowing past the
        # viewport and cards clipping under the Command Matrix. The buttons'
        # own min-width is enough to keep them usable; equal stretch keeps the
        # two columns identical.
        for c in range(columns):
            self._grid.setColumnStretch(c, 1)
        outer.addLayout(self._grid)

    # --- hover state-layer ---
    def event(self, e):
        if e.type() == QEvent.HoverEnter:
            self.setProperty("hovered", True)
            self._unpolish_and_repolish()
        elif e.type() == QEvent.HoverLeave:
            self.setProperty("hovered", False)
            self._unpolish_and_repolish()
        return super().event(e)

    def _unpolish_and_repolish(self) -> None:
        """Re-apply QSS so the dynamic [hovered] selector takes effect."""
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

    def add_button(self, button: QPushButton) -> None:
        """Add an already-constructed button to the card's grid.

        Applies the shared sizing so every button in every card is identical:
          - fixed height → uniform rows across all cards;
          - MinimumExpanding horizontal policy + zero minimum width → the two
            buttons in a row share the available column width equally (paired
            with equal column stretch) AND can compress below their label's
            natural sizeHint, which is what lets the card shrink to fit a narrow
            scroll viewport instead of overflowing under the Command Matrix.
        """
        button.setFixedHeight(BTN_HEIGHT)
        button.setMinimumWidth(0)
        sp = button.sizePolicy()
        button.setSizePolicy(QSizePolicy.MinimumExpanding, sp.verticalPolicy())
        self._grid.addWidget(button, self._row, self._col)
        self._advance()

    def _advance(self) -> None:
        self._col += 1
        if self._col >= self._columns:
            self._col = 0
            self._row += 1

    def append_bottom_spacer(self) -> None:
        """Add an elastic spacer as the LAST item of the card's outer layout.

        After this, when equalize_card_heights() gives the card more vertical
        space than its content needs, the extra space lands BELOW the buttons:
          title → subtitle → button grid → [grows here] → card bottom.
        That keeps the title, description, and buttons anchored at the top
        (the M3 dashboard look the design calls for) and never stretches a
        button. Without it, the outer QVBoxLayout would spread the extra space
        evenly between its items, pushing the button grid toward the middle.

        Called explicitly by the operations views (ADB / Fastboot) after they
        finish adding buttons, so cards used elsewhere (e.g. the CPID form
        cards, which append fields/layouts to card.layout() themselves) are
        untouched.
        """
        self.layout().addStretch()


class LabeledField(QWidget):
    """A caption label above a QLineEdit — M3 outlined text-field pattern."""

    def __init__(self, label: str, placeholder: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        cap = QLabel(label)
        cap.setProperty("role", "caption")
        layout.addWidget(cap)

        self.entry = QLineEdit()
        self.entry.setPlaceholderText(placeholder)
        layout.addWidget(self.entry)

    def text(self) -> str:
        return self.entry.text().strip()

    def set_text(self, value: str) -> None:
        self.entry.setText(value)
