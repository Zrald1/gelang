"""{app_name} — application aggregator.

Single import surface for the web backend.

Layers:
  app/memory/  Rust — request bounds, buffer capacities
  app/core/    Rust — computation (one function per file)
"""
from __future__ import annotations

# --- Memory layer ---
from app.memory.limits import (
    mem_max_arg_value, mem_min_arg_value, mem_max_args,
    mem_clamp_arg, mem_arg_count_ok,
)
from app.memory.buffer import (
    mem_json_capacity, mem_path_capacity, mem_body_capacity,
)

# --- Core functions ---
from app.core.add import add
from app.core.multiply import multiply
from app.core.factorial import factorial
from app.core.fibonacci import fibonacci
from app.core.is_prime import is_prime
