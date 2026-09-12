"""Memory buffers — fixed-size capacities. Compiled to Rust.

The app formats numbers into fixed-size stack buffers instead of
heap-allocating Strings. These functions expose the capacities so the
Rust shell and the C++ UI layer agree on the same bounds.
"""
from __future__ import annotations
from pyeffic.backends import rust


@rust
def mem_buffer_capacity() -> int:
    """Capacity of a general text buffer (bytes)."""
    return 64


@rust
def mem_digits_capacity() -> int:
    """Capacity of the scratch buffer used for integer digits."""
    return 20


@rust
def mem_state_slots() -> int:
    """Number of fixed app-state slots (input, result, op)."""
    return 3
