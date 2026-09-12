"""UI widgets — drawing primitives. Compiled to C++.

Each function draws exactly one primitive onto a raw HDC passed from the
Rust shell. No application state lives here.

Depends on: theme.ge.py
"""
from __future__ import annotations
from pyeffic.backends import cpp
from app.ui.theme import (
    ui_color_card, ui_color_accent, ui_radius,
)


@cpp
def ui_draw_panel(hdc_val: int, x: int, y: int, w: int, h: int, color: int) -> int:
    """Fill a rectangle."""
    ge_inline("cpp", """
    HDC hdc = (HDC)(intptr_t)hdc_val;
    RECT rc = { (LONG)x, (LONG)y, (LONG)(x + w), (LONG)(y + h) };
    HBRUSH brush = CreateSolidBrush((COLORREF)color);
    FillRect(hdc, &rc, brush);
    DeleteObject(brush);
    return 0;
    """)
    return 0


@cpp
def ui_draw_card(hdc_val: int, x: int, y: int, w: int, h: int) -> int:
    """Draw a rounded card with an accent border."""
    ge_inline("cpp", """
    HDC hdc = (HDC)(intptr_t)hdc_val;
    HBRUSH brush = CreateSolidBrush((COLORREF)ui_color_card());
    HPEN pen = CreatePen(PS_SOLID, 2, (COLORREF)ui_color_accent());
    HBRUSH old_brush = (HBRUSH)SelectObject(hdc, brush);
    HPEN old_pen = (HPEN)SelectObject(hdc, pen);
    RoundRect(hdc, (int)x, (int)y, (int)(x + w), (int)(y + h),
              ui_radius() * 2, ui_radius() * 2);
    SelectObject(hdc, old_brush);
    SelectObject(hdc, old_pen);
    DeleteObject(brush);
    DeleteObject(pen);
    return 0;
    """)
    return 0


@cpp
def ui_draw_text(hdc_val: int, text: str, x: int, y: int, w: int,
                 size: int, color: int, bold: int) -> int:
    """Draw centered single-line text."""
    ge_inline("cpp", """
    HDC hdc = (HDC)(intptr_t)hdc_val;
    HFONT font = CreateFontA((int)size, 0, 0, 0, bold ? FW_BOLD : FW_NORMAL,
        FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
        DEFAULT_PITCH | FF_SWISS, "Segoe UI");
    HFONT old = (HFONT)SelectObject(hdc, font);
    SetBkMode(hdc, TRANSPARENT);
    SetTextColor(hdc, (COLORREF)color);
    RECT rc = { (LONG)x, (LONG)y, (LONG)(x + w), (LONG)(y + size + 10) };
    DrawTextA(hdc, text.c_str(), -1, &rc, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
    SelectObject(hdc, old);
    DeleteObject(font);
    return 0;
    """)
    return 0


@cpp
def ui_draw_number(hdc_val: int, value: int, x: int, y: int, w: int,
                   size: int, color: int, bold: int) -> int:
    """Draw an integer using a fixed-size stack buffer (no heap allocation)."""
    ge_inline("cpp", """
    HDC hdc = (HDC)(intptr_t)hdc_val;
    char buf[64];
    snprintf(buf, sizeof(buf), "%lld", (long long)value);
    HFONT font = CreateFontA((int)size, 0, 0, 0, bold ? FW_BOLD : FW_NORMAL,
        FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
        DEFAULT_PITCH | FF_SWISS, "Segoe UI");
    HFONT old = (HFONT)SelectObject(hdc, font);
    SetBkMode(hdc, TRANSPARENT);
    SetTextColor(hdc, (COLORREF)color);
    RECT rc = { (LONG)x, (LONG)y, (LONG)(x + w), (LONG)(y + size + 10) };
    DrawTextA(hdc, buf, -1, &rc, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
    SelectObject(hdc, old);
    DeleteObject(font);
    return 0;
    """)
    return 0


@cpp
def ui_draw_grid(hdc_val: int, width: int, height: int, spacing: int, color: int) -> int:
    """Draw a dotted background grid."""
    ge_inline("cpp", """
    HDC hdc = (HDC)(intptr_t)hdc_val;
    for (int gx = 0; gx < (int)width; gx += (int)spacing)
        for (int gy = 0; gy < (int)height; gy += (int)spacing)
            SetPixel(hdc, gx, gy, (COLORREF)color);
    return 0;
    """)
    return 0
