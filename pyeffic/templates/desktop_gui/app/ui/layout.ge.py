"""UI layout — geometry math. Compiled to C++.

Pure coordinate math: no drawing, no state. Kept separate from
widgets.ge.py so layout can be reasoned about (and tested) on its own.

Depends on: theme.ge.py
"""
from __future__ import annotations
from pyeffic.backends import cpp
from app.ui.theme import ui_space_md, ui_space_lg


@cpp
def ui_sidebar_width() -> int:
    """Sidebar width in pixels."""
    return 300


@cpp
def ui_content_x() -> int:
    """Left edge of the content area."""
    return ui_sidebar_width() + ui_space_md()


@cpp
def ui_card_x() -> int:
    """Main card left edge."""
    return ui_content_x()


@cpp
def ui_card_y() -> int:
    """Main card top edge."""
    return ui_space_lg() + 60


@cpp
def ui_card_width(window_width: int) -> int:
    """Main card width."""
    return window_width - ui_card_x() - ui_space_md()


@cpp
def ui_card_height(window_height: int) -> int:
    """Main card height."""
    return window_height - ui_card_y() - 60


@cpp
def ui_controls_y(window_height: int) -> int:
    """Y position of the controls hint block."""
    return window_height - 140


@cpp
def ui_row_y(row: int) -> int:
    """Y position of sidebar row `row`."""
    return 80 + row * 34


@cpp
def ui_center_x(container_x: int, container_w: int, item_w: int) -> int:
    """X position that centers an item inside a container."""
    return container_x + (container_w - item_w) / 2
