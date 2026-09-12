"""Memory limits — bounded ranges for app state. Compiled to Rust.

This is the memory-safety boundary of the app. Every value that can grow
is bounded here so no computation can overflow or allocate without limit.

Rust design principle: "bound everything that can grow".
"""
from __future__ import annotations
from pyeffic.backends import rust


@rust
def mem_input_min() -> int:
    """Minimum allowed input value."""
    return 0


@rust
def mem_input_max() -> int:
    """Maximum allowed input value.

    Kept at 20 so factorial(n) fits in a signed 64-bit integer
    (21! overflows i64). Bounding here prevents overflow at the source.
    """
    return 20


@rust
def mem_clamp_input(value: int) -> int:
    """Clamp a value into the allowed input range."""
    if value < mem_input_min():
        return mem_input_min()
    if value > mem_input_max():
        return mem_input_max()
    return value


@rust
def mem_step_up(value: int) -> int:
    """Increment a value, clamped to the max."""
    return mem_clamp_input(value + 1)


@rust
def mem_step_down(value: int) -> int:
    """Decrement a value, clamped to the min."""
    return mem_clamp_input(value - 1)
