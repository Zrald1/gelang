"""Auto-selection rule engine for GE backend selection.

When the user does NOT specify a backend with @rust/@cpp/@csharp/@zig/@go/@kotlin,
the auto-selector analyzes each function's characteristics and picks the best
backend based on research-backed rules.

Rules are derived from web research on best use cases for each language:

  Rust    — memory safety, concurrency, systems, security-sensitive, long-running services
  C++     — game engines, CUDA, OpenCV, performance-critical computation, template metaprogramming
  C#      — enterprise logic, game dev (Unity), .NET ecosystem, business logic, data processing
  Dart    — Flutter UI, async event loop, state management, cross-platform UI
  Zig     — embedded systems, toolchains, C replacement, manual memory control, no runtime
  Go      — network services, microservices, cloud infrastructure, goroutine concurrency
  Kotlin  — Android, Kotlin Multiplatform, JVM backend, coroutines, null-safety

The engine scores each backend for each function based on detected features,
then picks the highest-scoring backend. If all scores are zero, it defaults to
Rust (the safest general-purpose systems language).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from .analyzer import FuncUnit


@dataclass
class BackendScore:
    """Score for a single backend for a single function."""
    backend: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def add(self, points: float, reason: str) -> None:
        self.score += points
        self.reasons.append(f"+{points:.1f} {self.backend} ({reason})")


# ---- Feature detection rules ----
# Each rule: (pattern_name, feature_keywords, backend_scores)
# The analyzer's feature detection already classifies functions; we map those
# features to backend scores based on research.

# Research-backed scoring rules:
#   - Higher score = better fit for that backend
#   - Negative score = poor fit (avoid)
#   - Zero = neutral

RULES: list[tuple[str, dict[str, float]]] = [
    # ---- Memory safety / security ----
    # Rust is the premier choice for memory safety without GC
    ("memory_safety_critical", {
        "rust": +3.0,    # Rust: ownership model eliminates memory bugs
        "zig": +1.5,     # Zig: safer than C but manual memory
        "csharp": +0.5,  # C#: GC-managed, safe but not systems-level
        "kotlin": +0.5,  # Kotlin: GC-managed, null-safe
        "cpp": -1.0,     # C++: many unsafe-by-default edges
        "go": +0.5,      # Go: GC-managed, safe for ordinary code
    }),

    # ---- Concurrency ----
    # Go excels at goroutine concurrency; Rust has type-system-enforced concurrency
    ("concurrency", {
        "go": +3.0,      # Go: goroutines are the killer feature
        "rust": +2.5,    # Rust: Send/Sync type-system-enforced concurrency
        "kotlin": +2.0,  # Kotlin: coroutines for lightweight async
        "csharp": +1.5,  # C#: async/await, Task Parallel Library
        "cpp": +1.0,     # C++: threads, atomics, but complex
        "zig": +0.5,     # Zig: evolving async model
        "dart": +1.0,    # Dart: async/await, isolates
    }),

    # ---- Numeric computation / arithmetic ----
    # C++ and Rust are top performers; C# for enterprise data processing
    ("arithmetic", {
        "cpp": +2.0,     # C++: excellent performance, SIMD, auto-vectorization
        "rust": +2.0,    # Rust: competitive with C++, SIMD auto-vectorization
        "csharp": +1.5,  # C#: good performance, .NET numerics
        "zig": +1.5,     # Zig: excellent potential, explicit allocation
        "go": +1.0,      # Go: good but GC affects some workloads
        "kotlin": +0.5,  # Kotlin: JVM overhead for pure computation
        "dart": +0.5,    # Dart: not optimized for heavy computation
    }),

    # ---- Loops / iteration ----
    # C++ and Rust excel at tight loops; Go for simple iteration
    ("numeric_loop", {
        "cpp": +2.0,     # C++: tight loop optimization, auto-vectorization
        "rust": +2.0,    # Rust: zero-cost iterators, auto-vectorization
        "zig": +1.5,     # Zig: explicit control, fast compilation
        "csharp": +1.0,  # C#: good loop performance
        "go": +1.0,      # Go: simple loops, fast enough
        "kotlin": +0.5,  # Kotlin: functional iteration overhead
        "dart": +0.3,    # Dart: not for heavy loops
    }),

    # ---- Comparisons / conditionals ----
    # All languages handle this well; slight edge to systems languages
    ("comparison", {
        "rust": +1.0,    # Rust: pattern matching, exhaustive
        "cpp": +1.0,     # C++: standard conditionals
        "zig": +1.0,     # Zig: no hidden control flow
        "csharp": +0.5,  # C#: standard
        "go": +0.5,      # Go: simple conditionals
        "kotlin": +0.5,  # Kotlin: when expressions
        "dart": +0.3,    # Dart: standard
    }),

    # ---- I/O (print, input) ----
    # All handle I/O; Dart for UI output, Go for network I/O
    ("io_print", {
        "dart": +2.0,    # Dart: UI output, console for debugging
        "go": +1.5,      # Go: excellent I/O stdlib
        "kotlin": +1.0,  # Kotlin: JVM I/O
        "csharp": +1.0,  # C#: Console I/O
        "rust": +0.5,    # Rust: basic I/O
        "cpp": +0.5,     # C++: iostream
        "zig": +0.5,     # Zig: basic I/O
    }),

    # ---- List / array operations ----
    # C++ for performance; Rust for safety; Go for simplicity
    ("list_operation", {
        "cpp": +2.0,     # C++: std::vector, performance
        "rust": +2.0,    # Rust: Vec, safe and fast
        "zig": +1.5,     # Zig: slices, explicit allocators
        "csharp": +1.5,  # C#: LINQ, List<T>
        "go": +1.0,      # Go: slices, simple
        "kotlin": +1.0,  # Kotlin: collections, functional
        "dart": +0.5,    # Dart: List, not performance-focused
    }),

    # ---- Function calls (inter-function) ----
    # All handle this; slight edge to languages with good inlining
    ("function_call", {
        "rust": +1.0,    # Rust: zero-cost abstractions, inlining
        "cpp": +1.0,     # C++: inlining, templates
        "zig": +1.0,     # Zig: comptime, inlining
        "csharp": +0.5,  # C#: JIT inlining (AOT less aggressive)
        "go": +0.5,      # Go: inlining but interface overhead
        "kotlin": +0.5,  # Kotlin: JVM inlining
        "dart": +0.3,    # Dart: standard
    }),
]


# ---- Name-based heuristics ----
# Function name patterns that suggest a specific backend
NAME_PATTERNS: list[tuple[re.Pattern, dict[str, float]]] = [
    # UI / widget / screen / page → Dart
    (re.compile(r"^(build|render|widget|screen|page|view|drawer|dialog|snackbar|appbar)", re.I), {
        "dart": +5.0,    # Flutter UI is Dart's domain
        "kotlin": +1.0,  # Compose also possible
    }),
    # Network / HTTP / API / request → Go
    (re.compile(r"^(fetch|request|http|api|endpoint|route|handler|serve|listen|connect|socket|websocket)", re.I), {
        "go": +5.0,      # Go: network services, goroutines
        "kotlin": +1.5,  # Kotlin: Ktor, coroutines
        "csharp": +1.0,  # C#: ASP.NET
    }),
    # Compute / calculate / process → C++ or Rust
    (re.compile(r"^(compute|calculate|process|transform|optimize|render|encode|decode|compress|encrypt|decrypt|hash)", re.I), {
        "cpp": +3.0,     # C++: performance-critical computation
        "rust": +2.5,    # Rust: safe computation
        "zig": +2.0,     # Zig: explicit control
        "csharp": +1.0,  # C#: data processing
    }),
    # Memory / allocate / free / buffer → Zig or Rust
    (re.compile(r"^(alloc|free|buffer|memory|pointer|register|hardware|device|firmware|embedded)", re.I), {
        "zig": +5.0,     # Zig: manual memory control, embedded
        "rust": +2.0,    # Rust: ownership model
        "cpp": +1.0,     # C++: manual memory
    }),
    # Business / enterprise / model / service / validate → C# or Kotlin
    (re.compile(r"^(business|enterprise|model|service|validate|validate|repository|entity|domain|logic|rule|policy)", re.I), {
        "csharp": +4.0,  # C#: enterprise logic, .NET
        "kotlin": +3.0,  # Kotlin: JVM backend, domain logic
        "go": +1.0,      # Go: services
    }),
    # Android / mobile / jetpack / compose → Kotlin
    (re.compile(r"^(android|mobile|jetpack|compose|lifecycle|viewmodel|navigation)", re.I), {
        "kotlin": +5.0,  # Kotlin: Android-native
        "dart": +2.0,    # Dart: Flutter mobile
    }),
    # Concurrent / async / parallel / goroutine → Go
    (re.compile(r"^(concurrent|async|parallel|goroutine|channel|pipeline|worker|spawn|schedule)", re.I), {
        "go": +5.0,      # Go: goroutines, channels
        "rust": +2.0,    # Rust: async, threads
        "kotlin": +2.0,  # Kotlin: coroutines
        "csharp": +1.5,  # C#: async/await
    }),
    # Safe / secure / verify / check / guard → Rust
    (re.compile(r"^(safe|secure|verify|check|guard|protect|sanitize|validate_token|auth|permission)", re.I), {
        "rust": +5.0,    # Rust: memory safety, security
        "kotlin": +1.0,  # Kotlin: null-safety
        "csharp": +1.0,  # C#: safe by default
    }),
    # Game / render / physics / collision / sprite → C++
    (re.compile(r"^(game|render|physics|collision|sprite|mesh|shader|texture|vertex|polygon|raycast)", re.I), {
        "cpp": +5.0,     # C++: game engines, rendering
        "csharp": +2.0,  # C#: Unity game dev
        "rust": +1.0,    # Rust: emerging game dev
    }),
    # Data / dataframe / query / filter / map / reduce → C# or Kotlin
    (re.compile(r"^(data|dataframe|query|filter|map|reduce|aggregate|group|sort|search|index)", re.I), {
        "csharp": +3.0,  # C#: LINQ, data processing
        "kotlin": +2.5,  # Kotlin: collections, functional
        "go": +1.0,      # Go: simple data handling
        "rust": +1.0,    # Rust: iterators
    }),
]


# ---- Default backend preference order (when scores are tied) ----
# Based on research: Rust is the safest default for general-purpose code
DEFAULT_PREFERENCE = ["rust", "cpp", "csharp", "go", "kotlin", "zig", "dart"]


def score_backend(unit: FuncUnit) -> dict[str, BackendScore]:
    """Score all backends for a given function.

    Returns a dict mapping backend name to BackendScore.
    """
    scores = {b: BackendScore(backend=b) for b in
              ["rust", "cpp", "csharp", "zig", "go", "kotlin", "dart"]}

    # 1) Apply feature-based rules
    for feature in unit.features:
        for pattern_name, backend_scores in RULES:
            if pattern_name == feature or feature.startswith(pattern_name):
                for backend, points in backend_scores.items():
                    if points > 0:
                        scores[backend].add(points, feature)
                    elif points < 0:
                        scores[backend].score += points
                        scores[backend].reasons.append(f"{points:.1f} {backend} ({feature})")

    # 2) Apply name-based heuristics
    for pattern, backend_scores in NAME_PATTERNS:
        if pattern.match(unit.name):
            for backend, points in backend_scores.items():
                if points > 0:
                    scores[backend].add(points, f"name pattern: {unit.name}")

    # 3) Check for UI-related patterns in the function body (build function)
    if unit.name == "build" or unit.name.startswith("build_"):
        scores["dart"].add(5.0, "UI build function")

    # 4) Check for async/event-loop patterns
    if unit.body:
        for node in ast.walk(unit.body):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                fname = node.func.id
                # network-like calls suggest Go
                if fname in ("fetch", "request", "send", "receive", "listen", "connect"):
                    scores["go"].add(2.0, f"network call: {fname}")
                # async-like patterns suggest Go or Kotlin
                if fname in ("async", "await", "spawn", "go"):
                    scores["go"].add(1.5, f"async call: {fname}")
                    scores["kotlin"].add(1.0, f"async call: {fname}")

    return scores


def select_backend(unit: FuncUnit) -> tuple[str, list[str]]:
    """Select the best backend for a function based on auto-selection rules.

    Returns (backend_name, list_of_reasons).
    """
    scores = score_backend(unit)

    # find the highest-scoring backend
    best_backend = None
    best_score = 0.0
    for backend in DEFAULT_PREFERENCE:
        s = scores[backend].score
        if s > best_score:
            best_score = s
            best_backend = backend

    # if all scores are zero, default to Rust
    if best_backend is None or best_score <= 0:
        best_backend = "rust"
        return best_backend, ["default: no strong signal -> rust (safest general-purpose)"]

    # collect reasons
    reasons = scores[best_backend].reasons.copy()
    # add comparison summary
    summary_parts = []
    for backend in DEFAULT_PREFERENCE:
        s = scores[backend].score
        if s != 0:
            summary_parts.append(f"{backend}={s:.1f}")
    if summary_parts:
        reasons.append(f"scores: {', '.join(summary_parts)}")

    return best_backend, reasons


def auto_select_backends(units: list[FuncUnit]) -> dict[str, tuple[str, list[str]]]:
    """Auto-select backends for all functions.

    Returns a dict mapping function name to (backend, reasons).
    Only selects for functions that don't have a forced_backend.
    """
    result: dict[str, tuple[str, list[str]]] = {}
    for u in units:
        if u.forced_backend:
            result[u.name] = (u.forced_backend, [f"forced: @{u.forced_backend}"])
        elif u.supported and u.name != "build":
            backend, reasons = select_backend(u)
            result[u.name] = (backend, reasons)
    return result


def explain_selection(unit: FuncUnit) -> str:
    """Explain why a particular backend was selected for a function.

    Returns a human-readable explanation string.
    """
    backend, reasons = select_backend(unit)
    lines = [f"Function '{unit.name}' -> {backend}"]
    for r in reasons:
        lines.append(f"  {r}")
    return "\n".join(lines)
