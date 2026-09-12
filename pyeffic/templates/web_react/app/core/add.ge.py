"""Core function: add. Compiled to the selected native backend."""
from __future__ import annotations
from pyeffic.backends import rust


@rust
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b
