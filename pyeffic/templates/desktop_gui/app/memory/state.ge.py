"""Memory state — bounded application state. Compiled to Rust.

The GUI keeps a fixed number of scalar slots. No collections grow at
runtime, so memory use is constant regardless of how long the app runs.
"""
from __future__ import annotations
from pyeffic.backends import rust
from app.memory.limits import mem_clamp_input


@rust
def mem_initial_input() -> int:
    """Initial input value at startup."""
    return 10


@rust
def mem_initial_result() -> int:
    """Initial result value at startup."""
    return 0


@rust
def mem_initial_op() -> int:
    """Initial operation code (0 = factorial)."""
    return 0


@rust
def mem_op_count() -> int:
    """Number of supported operations."""
    return 4


@rust
def mem_next_op(op: int) -> int:
    """Cycle to the next operation code."""
    return (op + 1) % mem_op_count()


@rust
def mem_normalize_input(value: int) -> int:
    """Normalize an input value into the bounded range."""
    return mem_clamp_input(value)
