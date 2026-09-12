"""UI theme — design tokens. Compiled to C++.

Modern dark theme (Fluent-2 / Tailwind-inspired palette).
This file owns the Win32 includes for the whole C++ layer.

UI layer structure (one concern per file):
  theme.ge.py   — colors, font sizes, spacing (this file)
  layout.ge.py  — geometry math
  widgets.ge.py — drawing primitives
  render.ge.py  — frame orchestrator
"""
from __future__ import annotations
from pyeffic.backends import cpp

# Win32 SDK includes — injected at file scope, before all functions.
ge_preamble("cpp", """
#include <windows.h>
#include <windowsx.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
""")


# --- Colors ---

@cpp
def ui_color_bg() -> int:
    """Window background (deep slate)."""
    ge_inline("cpp", "return (int)RGB(15, 23, 42);")
    return 0


@cpp
def ui_color_panel() -> int:
    """Sidebar panel background."""
    ge_inline("cpp", "return (int)RGB(30, 41, 59);")
    return 0


@cpp
def ui_color_card() -> int:
    """Card background."""
    ge_inline("cpp", "return (int)RGB(30, 41, 59);")
    return 0


@cpp
def ui_color_accent() -> int:
    """Primary accent (blue)."""
    ge_inline("cpp", "return (int)RGB(96, 165, 250);")
    return 0


@cpp
def ui_color_text() -> int:
    """Primary text."""
    ge_inline("cpp", "return (int)RGB(241, 245, 249);")
    return 0


@cpp
def ui_color_text_dim() -> int:
    """Muted text."""
    ge_inline("cpp", "return (int)RGB(148, 163, 184);")
    return 0


@cpp
def ui_color_success() -> int:
    """Success / result (green)."""
    ge_inline("cpp", "return (int)RGB(74, 222, 128);")
    return 0


@cpp
def ui_color_warning() -> int:
    """Warning (amber)."""
    ge_inline("cpp", "return (int)RGB(251, 191, 36);")
    return 0


@cpp
def ui_color_grid() -> int:
    """Background grid dots."""
    ge_inline("cpp", "return (int)RGB(51, 65, 85);")
    return 0


# --- Font sizes ---

@cpp
def ui_font_title() -> int:
    """Title font size."""
    return 24


@cpp
def ui_font_heading() -> int:
    """Heading font size."""
    return 18


@cpp
def ui_font_body() -> int:
    """Body font size."""
    return 15


@cpp
def ui_font_small() -> int:
    """Caption font size."""
    return 13


# --- Spacing / radius ---

@cpp
def ui_space_xs() -> int:
    """Extra-small spacing."""
    return 4


@cpp
def ui_space_sm() -> int:
    """Small spacing."""
    return 8


@cpp
def ui_space_md() -> int:
    """Medium spacing."""
    return 16


@cpp
def ui_space_lg() -> int:
    """Large spacing."""
    return 24


@cpp
def ui_radius() -> int:
    """Corner radius."""
    return 12
