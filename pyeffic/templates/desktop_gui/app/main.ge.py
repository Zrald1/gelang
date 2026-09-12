"""{app_name} — application aggregator.

Single import surface for platform entry points. Import order matters:
theme before layout/widgets/render, so the C++ preamble declares the
Win32 SDK before anything that uses it.

Layers:
  app/memory/  Rust  — bounded state, buffers, limits
  app/core/    C++   — computation (one function per file)
  app/ui/      C++   — theme, layout, widgets, render
"""
from __future__ import annotations

# --- Memory layer (Rust) ---
from app.memory.limits import (
    mem_input_min, mem_input_max, mem_clamp_input, mem_step_up, mem_step_down,
)
from app.memory.buffer import (
    mem_buffer_capacity, mem_digits_capacity, mem_state_slots,
)
from app.memory.state import (
    mem_initial_input, mem_initial_result, mem_initial_op,
    mem_op_count, mem_next_op, mem_normalize_input,
)

# --- Core functions (C++) ---
from app.core.add import add
from app.core.multiply import multiply
from app.core.factorial import factorial
from app.core.fibonacci import fibonacci
from app.core.is_prime import is_prime
from app.core.gcd import gcd
from app.core.power import power

# --- UI layer (C++), theme first ---
from app.ui.theme import (
    ui_color_bg, ui_color_panel, ui_color_card, ui_color_accent,
    ui_color_text, ui_color_text_dim, ui_color_success, ui_color_warning,
    ui_color_grid, ui_font_title, ui_font_heading, ui_font_body, ui_font_small,
    ui_space_xs, ui_space_sm, ui_space_md, ui_space_lg, ui_radius,
)
from app.ui.layout import (
    ui_sidebar_width, ui_content_x, ui_card_x, ui_card_y,
    ui_card_width, ui_card_height, ui_controls_y, ui_row_y, ui_center_x,
)
from app.ui.widgets import (
    ui_draw_panel, ui_draw_card, ui_draw_text, ui_draw_number, ui_draw_grid,
)
from app.ui.render import ui_draw_frame
