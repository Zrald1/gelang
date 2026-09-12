"""Request limits — bounds for the web backend. Compiled to Rust.

Every value that can grow from client input is bounded here, so a hostile
or buggy client cannot make the server allocate without limit.

Rust design principle: "bound everything that can grow".
"""
from __future__ import annotations
from pyeffic.backends import rust


@rust
def mem_max_arg_value() -> int:
    """Largest integer argument the API accepts.

    Kept at 20 so factorial(n) fits in a signed 64-bit integer
    (21! overflows i64). Bounding here prevents overflow at the source.
    """
    return 20


@rust
def mem_min_arg_value() -> int:
    """Smallest integer argument the API accepts."""
    return -20


@rust
def mem_max_args() -> int:
    """Maximum number of arguments per call."""
    return 8


@rust
def mem_clamp_arg(value: int) -> int:
    """Clamp a client-supplied argument into range."""
    if value < mem_min_arg_value():
        return mem_min_arg_value()
    if value > mem_max_arg_value():
        return mem_max_arg_value()
    return value


@rust
def mem_arg_count_ok(count: int) -> int:
    """Return 1 if the argument count is acceptable."""
    if count < 0:
        return 0
    if count > mem_max_args():
        return 0
    return 1
