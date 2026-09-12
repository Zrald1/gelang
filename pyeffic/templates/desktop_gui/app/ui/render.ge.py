"""UI render — frame orchestrator. Compiled to C++.

Draws one complete frame. Called from the Rust shell on WM_PAINT with the
raw HDC handle. Composition order:

  background -> grid -> sidebar -> sidebar text -> card -> card content -> footer

Depends on: theme.ge.py, layout.ge.py, widgets.ge.py
"""
from __future__ import annotations
from pyeffic.backends import cpp
from app.ui.theme import (
    ui_color_bg, ui_color_panel, ui_color_accent, ui_color_text,
    ui_color_text_dim, ui_color_success, ui_color_grid,
    ui_font_title, ui_font_body, ui_font_small,
)
from app.ui.layout import (
    ui_sidebar_width, ui_content_x, ui_card_x, ui_card_y,
    ui_card_width, ui_card_height, ui_controls_y, ui_row_y,
)
from app.ui.widgets import (
    ui_draw_panel, ui_draw_card, ui_draw_text, ui_draw_number, ui_draw_grid,
)


@cpp
def ui_draw_frame(hdc_val: int, width: int, height: int,
                  input_val: int, result_val: int, op: int) -> int:
    """Draw the whole application frame."""
    ge_inline("cpp", """
    HDC hdc = (HDC)(intptr_t)hdc_val;

    ui_draw_panel(hdc_val, 0, 0, width, height, ui_color_bg());
    ui_draw_grid(hdc_val, width, height, 40, ui_color_grid());
    ui_draw_panel(hdc_val, 0, 0, ui_sidebar_width(), height, ui_color_panel());

    ui_draw_text(hdc_val, "{app_name}", 16, 16, ui_sidebar_width() - 32,
                 ui_font_title(), ui_color_accent(), 1);
    ui_draw_text(hdc_val, "Rust memory + C++ functions", 16, 50,
                 ui_sidebar_width() - 32, ui_font_small(), ui_color_text_dim(), 0);

    ui_draw_text(hdc_val, "Input", 16, ui_row_y(0), 90,
                 ui_font_small(), ui_color_text_dim(), 0);
    ui_draw_number(hdc_val, input_val, 110, ui_row_y(0), 170,
                   ui_font_body(), ui_color_text(), 1);

    const char* op_names[4] = { "factorial", "fibonacci", "is_prime", "gcd" };
    const char* op_label = (op >= 0 && op < 4) ? op_names[op] : "?";
    ui_draw_text(hdc_val, "Operation", 16, ui_row_y(1), 90,
                 ui_font_small(), ui_color_text_dim(), 0);
    ui_draw_text(hdc_val, op_label, 110, ui_row_y(1), 170,
                 ui_font_small(), ui_color_warning(), 0);

    ui_draw_text(hdc_val, "Result", 16, ui_row_y(2), 90,
                 ui_font_small(), ui_color_text_dim(), 0);
    ui_draw_number(hdc_val, result_val, 110, ui_row_y(2), 170,
                   ui_font_body(), ui_color_success(), 1);

    int cy = ui_controls_y(height);
    ui_draw_text(hdc_val, "Controls", 16, cy, ui_sidebar_width() - 32,
                 ui_font_body(), ui_color_text(), 1);
    ui_draw_text(hdc_val, "Up / Down   change input", 16, cy + 26,
                 ui_sidebar_width() - 32, ui_font_small(), ui_color_text_dim(), 0);
    ui_draw_text(hdc_val, "Enter       run operation", 16, cy + 44,
                 ui_sidebar_width() - 32, ui_font_small(), ui_color_text_dim(), 0);
    ui_draw_text(hdc_val, "F / P / G   fib / prime / gcd", 16, cy + 62,
                 ui_sidebar_width() - 32, ui_font_small(), ui_color_text_dim(), 0);
    ui_draw_text(hdc_val, "Esc         quit", 16, cy + 80,
                 ui_sidebar_width() - 32, ui_font_small(), ui_color_text_dim(), 0);

    ui_draw_card(hdc_val, ui_card_x(), ui_card_y(),
                 ui_card_width(width), ui_card_height(height));
    ui_draw_text(hdc_val, "C++ Core Function", ui_card_x(), ui_card_y() + 20,
                 ui_card_width(width), ui_font_body(), ui_color_text(), 1);
    ui_draw_text(hdc_val, "Computed in C++ - drawn in C++ - driven by Rust",
                 ui_card_x(), ui_card_y() + 50, ui_card_width(width),
                 ui_font_small(), ui_color_text_dim(), 0);
    ui_draw_number(hdc_val, result_val, ui_card_x(), ui_card_y() + 100,
                   ui_card_width(width), ui_font_title(), ui_color_success(), 1);

    ui_draw_text(hdc_val, "{app_name} v0.1.0 - Rust + C++ Desktop",
                 ui_content_x(), height - 30, ui_card_width(width),
                 ui_font_small(), ui_color_text_dim(), 0);

    return 0;
    """)
    return 0
