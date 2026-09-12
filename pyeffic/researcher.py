"""Backend selection: web research + static heuristics.

For each function the researcher builds a query describing the workload, runs a
real web search (DuckDuckGo HTML endpoint, no API key required), and scores
C++ vs Rust from the snippets. Static heuristics are always computed as a
reliable backbone; web results nudge the score. If the network is unavailable
or `do_research` is off, heuristics alone decide.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .analyzer import FuncUnit

# Static heuristic weights. Positive => favors Rust, negative => favors C++.
HEURISTICS: dict[str, int] = {
    "numeric_loop": +2,      # Rust bounds-checked SIMD-friendly loops
    "arithmetic": +1,
    "indexing": +1,          # Rust safe indexing
    "list_alloc": +1,        # Vec is ergonomic
    "list_append": +1,
    "container_iter": 0,
    "math_builtin": 0,
    "len_builtin": 0,
    "comparison": 0,
    "while_loop": 0,
    "io_print": -1,          # C++ iostream often lighter for trivial IO
    "class_use": -2,         # C++ OOP ergonomics
    "plain": 0,
}

RUST_POS = re.compile(r"\b(rust)\b", re.I)
CPP_POS = re.compile(r"\b(c\+\+|cpp|std::)\b", re.I)
RUST_PERF = re.compile(r"rust.{0,40}(faster|safer|zero.cost|simd|bounds)", re.I)
CPP_PERF = re.compile(r"(c\+\+|cpp).{0,40}(faster|stl|template|simd|legacy)", re.I)


@dataclass
class Decision:
    backend: str  # "rust" | "cpp"
    rust_score: float
    cpp_score: float
    reasons: list[str]
    web_used: bool


def _query_for(unit: FuncUnit) -> str:
    feats = sorted(unit.features)
    keywords = {
        "numeric_loop": "numeric loop SIMD",
        "arithmetic": "arithmetic kernel",
        "indexing": "array indexing",
        "list_alloc": "dynamic array allocation",
        "list_append": "vector append",
        "container_iter": "container iteration",
        "math_builtin": "math builtins",
        "io_print": "console IO",
        "class_use": "object oriented class",
        "comparison": "comparisons",
        "while_loop": "while loop",
        "plain": "plain function",
    }
    terms = [keywords.get(f, f) for f in feats[:3]]
    return "rust vs c++ performance " + " ".join(terms)


def _ddg_search(query: str, timeout: float) -> list[str]:
    """Fetch DuckDuckGo lite results and return snippet strings.

    Uses the lite endpoint (plain HTML, no JS) with a POST request, which is
    the most scraping-friendly surface DuckDuckGo offers.
    """
    data = urllib.parse.urlencode({"q": query, "kl": "us-en"}).encode()
    req = urllib.request.Request(
        "https://lite.duckduckgo.com/lite/",
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0 (pyeffic/0.1)",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return []
    # snippets live in <td class='result-snippet'>...</td>
    snippets = re.findall(r"<td class='result-snippet'>(.*?)</td>", html, re.S)
    clean = [re.sub(r"<[^>]+>", " ", s) for s in snippets]
    return [s.strip() for s in clean if s.strip()][:8]


def decide(unit: FuncUnit, do_research: bool, timeout: float, force: str | None) -> Decision:
    if force in ("rust", "cpp", "csharp", "zig", "go", "kotlin"):
        return Decision(backend=force, rust_score=0, cpp_score=0,
                        reasons=[f"forced backend={force}"], web_used=False)

    # Use the new auto-selector for intelligent multi-backend selection
    from .autoselect import select_backend
    backend, reasons = select_backend(unit)

    web_used = False
    if do_research:
        q = _query_for(unit)
        snippets = _ddg_search(q, timeout)
        if snippets:
            web_used = True
            # web research can adjust the selection
            r_hits = sum(1 for s in snippets if RUST_POS.search(s))
            c_hits = sum(1 for s in snippets if CPP_POS.search(s))
            r_perf = sum(1 for s in snippets if RUST_PERF.search(s))
            c_perf = sum(1 for s in snippets if CPP_PERF.search(s))
            reasons.append(f"web: rust_hits={r_hits} perf={r_perf}, cpp_hits={c_hits} perf={c_perf} (query='{q}')")
            # if web research strongly favors C++ over Rust, override
            if c_hits + c_perf > r_hits + r_perf + 2 and backend == "rust":
                backend = "cpp"
                reasons.append(f"web override: cpp favored -> {backend}")
        else:
            reasons.append("web: no results, auto-select only")

    return Decision(backend=backend, rust_score=0, cpp_score=0, reasons=reasons, web_used=web_used)


def decide_program(units: list[FuncUnit], do_research: bool, timeout: float,
                   force: str | None) -> tuple[Decision, list[Decision]]:
    """Pick ONE backend for the whole program (so the call graph stays intact).

    Returns (program_decision, per_function_decisions_for_reporting).
    Uses the auto-selector to pick the best backend for the whole program
    based on aggregated function characteristics.
    """
    per_fn: list[Decision] = []
    any_web = False
    all_reasons: list[str] = []
    # aggregate backend scores across all functions
    from .autoselect import score_backend, DEFAULT_PREFERENCE
    agg_scores = {b: 0.0 for b in DEFAULT_PREFERENCE}

    for u in units:
        if not u.supported:
            per_fn.append(Decision("cpython", 0, 0, ["unsupported -> cpython fallback"], False))
            continue
        d = decide(u, do_research, timeout, force)
        per_fn.append(d)
        any_web = any_web or d.web_used
        all_reasons.append(f"[{u.name}] " + "; ".join(d.reasons))
        # aggregate scores from auto-selector
        if not force:
            scores = score_backend(u)
            for b in DEFAULT_PREFERENCE:
                agg_scores[b] += scores[b].score

    if force in ("rust", "cpp", "csharp", "zig", "go", "kotlin"):
        prog = Decision(force, 0, 0, [f"forced backend={force}"], False)
    else:
        # pick the backend with the highest aggregate score
        best_backend = "rust"
        best_score = 0.0
        for b in DEFAULT_PREFERENCE:
            if agg_scores[b] > best_score:
                best_score = agg_scores[b]
                best_backend = b
        if best_score <= 0:
            best_backend = "rust"  # default tie-break
        score_summary = ", ".join(f"{b}={agg_scores[b]:.1f}" for b in DEFAULT_PREFERENCE
                                  if agg_scores[b] != 0)
        prog = Decision(
            backend=best_backend,
            rust_score=agg_scores.get("rust", 0),
            cpp_score=agg_scores.get("cpp", 0),
            reasons=[f"auto-select aggregate: {score_summary} -> {best_backend}"] + all_reasons,
            web_used=any_web,
        )
    return prog, per_fn
