"""Backend selection decorators for GE.

Usage in GE source:
    from pyeffic.backends import rust, cpp, dart, csharp, zig, go, kotlin

    @rust
    def safe_function(x: int) -> int:
        return x * 2

    @cpp
    def cpp_function(x: int) -> int:
        return x * 3

    @dart
    def ui_function():
        pass

    @csharp
    def enterprise_logic(x: int) -> int:
        return x * 4

    @zig
    def systems_function(x: int) -> int:
        return x * 5

    @go
    def concurrent_function(x: int) -> int:
        return x * 6

    @kotlin
    def android_function(x: int) -> int:
        return x * 7

The analyzer reads these decorators from the AST to determine which native
backend each function should be compiled to. At Python runtime (when running
the source directly for testing), these are identity decorators — they just
return the function unchanged.

Backend strengths (from web research):
  @rust    — memory safety without GC, fearless concurrency, systems, security-sensitive
  @cpp     — C++ ecosystem (CUDA, OpenCV, game engines), template metaprogramming, performance-critical
  @dart    — stays in Dart (Flutter UI, async event loop, state management, cross-platform)
  @csharp  — .NET ecosystem, enterprise logic, game dev (Unity), NativeAOT to C ABI
  @zig     — no runtime, fast compilation, manual memory control, embedded, C replacement
  @go      — goroutine concurrency, network services, cloud infrastructure, microservices
  @kotlin  — Android-native, Kotlin Multiplatform, JVM backend, coroutines, null-safety
"""
from __future__ import annotations

from typing import TypeVar, Callable

T = TypeVar("T")


def rust(func: T) -> T:
    """Mark a function for compilation to Rust. No-op at Python runtime."""
    return func


def cpp(func: T) -> T:
    """Mark a function for compilation to C++. No-op at Python runtime."""
    return func


def dart(func: T) -> T:
    """Mark a function to stay in Dart (not compiled to native). No-op at Python runtime."""
    return func


def csharp(func: T) -> T:
    """Mark a function for compilation to C# via .NET NativeAOT. No-op at Python runtime."""
    return func


def zig(func: T) -> T:
    """Mark a function for compilation to Zig. No-op at Python runtime."""
    return func


def go(func: T) -> T:
    """Mark a function for compilation to Go (cgo shared library). No-op at Python runtime."""
    return func


def kotlin(func: T) -> T:
    """Mark a function for compilation to Kotlin/Native. No-op at Python runtime."""
    return func
