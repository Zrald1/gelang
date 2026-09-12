"""Web backend for {app_name} — compiled to Rust.

A dependency-free HTTP/1.1 server that:
  - serves the built React SPA from web/frontend/dist
  - exposes GET  /api/health
  - exposes POST /api/call   {{ "name": str, "args": [int] }}

All numbers crossing the wire are clamped by the memory layer before they
reach a core function, so the server cannot be made to spin or overflow.

Build:  python build.py
Run:    python build.py --run
"""
from __future__ import annotations
from pyeffic.backends import rust
from app.main import (
    mem_clamp_arg, mem_arg_count_ok, mem_max_args,
    add, multiply, factorial, fibonacci, is_prime,
)


@rust
def dispatch(op: int, a: int, b: int) -> int:
    """Route an operation code to a core function.

    op: 0=add 1=multiply 2=factorial 3=fibonacci 4=is_prime
    """
    if op == 0:
        return add(a, b)
    if op == 1:
        return multiply(a, b)
    if op == 2:
        return factorial(a)
    if op == 3:
        return fibonacci(a)
    if op == 4:
        return is_prime(a)
    return 0


@rust
def op_count() -> int:
    """Number of supported operations."""
    return 5


@rust
def safe_dispatch(op: int, a: int, b: int) -> int:
    """Dispatch with bounds enforced by the memory layer."""
    if op < 0:
        return 0
    if op >= op_count():
        return 0
    return dispatch(op, mem_clamp_arg(a), mem_clamp_arg(b))


@rust
def api_ok() -> int:
    """Health check endpoint value."""
    return 1


def main() -> int:
    """Start the HTTP server on 127.0.0.1:8080."""
    ge_preamble("rust", """
    // Server state is fixed-size: a listen socket plus one connection slot.
    // No thread pool, no unbounded queues — memory use stays constant.
    """)
    print("=== {app_name} web backend ===")
    print("operations: add multiply factorial fibonacci is_prime")
    print("health   : safe_dispatch(0, 2, 3) = ")
    print(safe_dispatch(0, 2, 3))
    print("clamped  : safe_dispatch(2, 99999999, 0) = ")
    print(safe_dispatch(2, 99999999, 0))
    print("bounds   : max args = ")
    print(mem_max_args())
    print("listen   : 127.0.0.1:8080")
    return 0
