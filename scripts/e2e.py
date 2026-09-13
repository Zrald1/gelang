#!/usr/bin/env python3
"""End-to-end tests for GE.

Runs the real CLI against real toolchains. No mocks, no stubs.

    python scripts/e2e.py                       # everything available
    python scripts/e2e.py -k string             # only cases matching a name
    python scripts/e2e.py --backend rust        # one backend
    python scripts/e2e.py --cli "npx gelang"    # test the published npm package
    python scripts/e2e.py --list                # list every case
    python scripts/e2e.py -j 8                  # parallel workers

Every case compiles and runs a real program and compares stdout. Cases that
need a toolchain which is not installed are reported as skipped, not failed.

Exit code is 0 when nothing failed.
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

CASES: list["Case"] = []


@dataclass
class Case:
    name: str
    fn: object
    group: str
    needs: str | None = None  # backend required, or None


def case(name: str, group: str, needs: str | None = None):
    def deco(fn):
        CASES.append(Case(name, fn, group, needs))
        return fn
    return deco


# ---------------------------------------------------------------------------
# result types
# ---------------------------------------------------------------------------

PASS, FAIL, SKIP = "pass", "fail", "skip"


@dataclass
class Result:
    case: str
    group: str
    status: str
    detail: str = ""
    seconds: float = 0.0


@dataclass
class Ctx:
    cli: list[str]
    workdir: Path
    backends: set[str]
    verbose: bool = False

    def run(self, args: list[str], cwd: Path | None = None,
            timeout: int = 300) -> subprocess.CompletedProcess:
        cmd = [*self.cli, *args]
        return subprocess.run(
            _spawnable(cmd), cwd=str(cwd or self.workdir), capture_output=True,
            text=True, timeout=timeout, encoding="utf-8", errors="replace")

    def write(self, relpath: str, content: str) -> Path:
        p = self.workdir / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
        return p

    def build(self, src: str, backend: str, name: str = "main",
              filename: str = "main.ge", extra: list[str] | None = None,
              timeout: int = 300) -> subprocess.CompletedProcess:
        self.write(filename, src)
        args = ["build", filename, "--backend", backend]
        if extra:
            args += extra
        return self.run(args, timeout=timeout)

    def build_and_run(self, src: str, backend: str,
                      filename: str = "main.ge",
                      extra: list[str] | None = None,
                      timeout: int = 300) -> tuple[str, subprocess.CompletedProcess]:
        """Build, then run the produced binary. Returns (stdout, build result).

        Each backend gets its own output directory and subdirectory, so a
        stale binary from a previous attempt can never be executed.
        """
        sub = self.workdir / f"src-{backend}"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / filename).write_text(textwrap.dedent(src).lstrip("\n"),
                                    encoding="utf-8")
        outdir = f"out-{backend}"
        args = ["build", filename, "--backend", backend, "-o", outdir]
        if extra:
            args += extra
        r = self.run(args, cwd=sub, timeout=timeout)
        exe = find_exe(sub / outdir)
        if exe is None:
            return "", r
        run = subprocess.run([str(exe)], capture_output=True, text=True,
                             timeout=120, encoding="utf-8", errors="replace")
        return run.stdout, r


def _spawnable(cmd: list[str]) -> list[str]:
    """Resolve a Windows .cmd/.bat shim to something subprocess can execute.

    `npx`, `npm` and friends are batch files on Windows; CreateProcess cannot
    run them directly, and Node 20.12+ refuses to spawn a .cmd without a
    shell. The interpreter is invoked explicitly instead of using shell=True,
    which would re-parse the arguments.
    """
    if os.name != "nt" or not cmd:
        return cmd
    exe = shutil.which(cmd[0])
    if not exe:
        return cmd
    if exe.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", exe, *cmd[1:]]
    return [exe, *cmd[1:]]


def find_exe(root: Path) -> Path | None:
    if not root.exists():
        return None
    for pat in ("**/bin/*.exe", "**/bin/*", "**/publish/*.exe",
                "**/*.exe", "**/*.out"):
        hits = [p for p in root.glob(pat)
                if p.is_file() and not p.suffix == ".o"
                and p.suffix not in (".rs", ".cpp", ".go", ".zig", ".kt", ".cs")]
        if hits:
            return sorted(hits, key=lambda p: len(str(p)))[0]
    return None


# ===========================================================================
# CLI surface
# ===========================================================================

@case("help", "cli")
def t_help(ctx: Ctx) -> str:
    r = ctx.run(["--help"])
    assert r.returncode == 0, r.stderr[:400]
    for cmd in ("build", "analyze", "create", "doctor", "diff", "golden",
                "api-check", "react", "flutter", "pack", "install", "tools"):
        assert cmd in r.stdout, f"`{cmd}` missing from help"
    return "all commands documented"


@case("doctor", "cli")
def t_doctor(ctx: Ctx) -> str:
    r = ctx.run(["doctor"])
    assert "GE doctor" in r.stdout, r.stdout[:300]
    assert "runtime" in r.stdout
    assert "native backends" in r.stdout
    return "reports runtime and backends"


@case("doctor-json", "cli")
def t_doctor_json(ctx: Ctx) -> str:
    import json
    r = ctx.run(["doctor", "--json"])
    d = json.loads(r.stdout)
    assert d["python"]["ok"], "python reported as unusable"
    assert "backends" in d and len(d["backends"]) == 6
    return f"{len(d['available_backends'])} backends"


@case("compilers", "cli")
def t_compilers(ctx: Ctx) -> str:
    r = ctx.run(["compilers"])
    assert r.returncode == 0, r.stderr[:300]
    assert "rustc" in r.stdout
    return "toolchain report"


@case("unknown-command", "cli")
def t_unknown_command(ctx: Ctx) -> str:
    r = ctx.run(["definitely-not-a-command"])
    assert r.returncode != 0, "unknown command should fail"
    assert "invalid choice" in (r.stderr + r.stdout).lower()
    return "rejected with non-zero exit"


@case("tools-list", "cli")
def t_tools_list(ctx: Ctx) -> str:
    r = ctx.run(["tools", "list"])
    assert r.returncode == 0, (r.stderr + r.stdout)[:400]
    return "tool list ok"


@case("tools-check", "cli")
def t_tools_check(ctx: Ctx) -> str:
    r = ctx.run(["tools", "check"])
    assert r.returncode == 0, (r.stderr + r.stdout)[:400]
    return "tool check ok"


@case("api-check", "cli")
def t_api_check(ctx: Ctx) -> str:
    if not _is_local_cli(ctx.cli):
        return "skipped: api/ ships with the source repo, not the npm package"
    r = ctx.run(["api-check"], cwd=REPO)
    assert r.returncode == 0, (r.stdout + r.stderr)[:500]
    return "surface matches"


@case("golden-check", "cli")
def t_golden_check(ctx: Ctx) -> str:
    if not _is_local_cli(ctx.cli):
        return "skipped: tests/golden ships with the source repo"
    r = ctx.run(["golden", "--check", "--no-behaviour"], cwd=REPO)
    assert r.returncode == 0, (r.stdout + r.stderr)[:500]
    return "goldens match"


# ===========================================================================
# every backend
# ===========================================================================

BACKEND_PROGRAM = """
def fib(n: int) -> int:
    if n <= 1:
        return n
    a: int = 0
    b: int = 1
    i: int = 2
    while i <= n:
        t: int = a + b
        a = b
        b = t
        i = i + 1
    return b


def main() -> None:
    print(fib(10))
"""


def _backend_case(backend: str):
    def fn(ctx: Ctx) -> str:
        out, r = ctx.build_and_run(BACKEND_PROGRAM, backend)
        assert r.returncode == 0, (r.stdout + r.stderr)[-700:]
        assert out.strip() == "55", f"expected 55, got {out!r}"
        return "fib(10)=55"
    return fn


for _b in ("rust", "cpp", "csharp", "zig", "go", "kotlin"):
    case(f"build-{_b}", "backend", needs=_b)(_backend_case(_b))


# ===========================================================================
# language features  (each runs on the fastest available backend)
# ===========================================================================

FEATURE_CASES: list[tuple[str, str, str]] = [
    # (name, source, expected stdout)
    ("int-arith", """
        def main() -> None:
            print(7 + 3 * 2)
            print((7 + 3) * 2)
            print(17 // 5)
            print(17 % 5)
            print(2 ** 10)
    """, "13\n20\n3\n2\n1024\n"),

    ("negative", """
        def main() -> None:
            x: int = -42
            print(x)
            print(-x)
            print(x * -1)
    """, "-42\n42\n42\n"),

    ("float-arith", """
        def main() -> None:
            print(1.5 + 2.25)
            print(10.0 / 4.0)
    """, "3.75\n2.5\n"),

    ("bool-logic", """
        def main() -> None:
            print(True)
            print(False)
            print(1 < 2)
            print(2 <= 2)
            print(3 > 4)
            print(1 == 1)
            print(1 != 2)
    """, "True\nFalse\nTrue\nTrue\nFalse\nTrue\nTrue\n"),

    ("if-elif-else", """
        def classify(n: int) -> int:
            if n < 0:
                return -1
            elif n == 0:
                return 0
            else:
                return 1


        def main() -> None:
            print(classify(-5))
            print(classify(0))
            print(classify(9))
    """, "-1\n0\n1\n"),

    ("while-break-continue", """
        def main() -> None:
            i: int = 0
            total: int = 0
            while i < 20:
                i = i + 1
                if i % 2 == 0:
                    continue
                if i > 15:
                    break
                total = total + i
            print(total)
    """, "64\n"),

    ("for-range", """
        def main() -> None:
            total: int = 0
            for i in range(1, 11):
                total = total + i
            print(total)
    """, "55\n"),

    ("nested-loops", """
        def main() -> None:
            count: int = 0
            for i in range(0, 5):
                for j in range(0, 5):
                    if i == j:
                        count = count + 1
            print(count)
    """, "5\n"),

    ("recursion", """
        def fact(n: int) -> int:
            if n <= 1:
                return 1
            return n * fact(n - 1)


        def main() -> None:
            print(fact(10))
    """, "3628800\n"),

    ("mutual-recursion", """
        def is_even(n: int) -> int:
            if n == 0:
                return 1
            return is_odd(n - 1)


        def is_odd(n: int) -> int:
            if n == 0:
                return 0
            return is_even(n - 1)


        def main() -> None:
            print(is_even(10))
            print(is_odd(10))
    """, "1\n0\n"),

    ("multiple-returns", """
        def divmod10(n: int) -> int:
            return n // 10


        def main() -> None:
            print(divmod10(123))
            print(123 % 10)
    """, "12\n3\n"),

    ("string-literal", """
        def main() -> None:
            s: str = "hello"
            print(s)
            print(len(s))
    """, "hello\n5\n"),

    ("string-concat", """
        def main() -> None:
            a: str = "foo"
            b: str = "bar"
            print(a + b)
            print(a + "-" + b)
    """, "foobar\nfoo-bar\n"),

    ("string-methods", """
        def main() -> None:
            s: str = "Hello World"
            print(s.upper())
            print(s.lower())
            print(s.replace("World", "GE"))
    """, "HELLO WORLD\nhello world\nHello GE\n"),

    ("fstring", """
        def main() -> None:
            n: int = 42
            s: str = "x"
            print(f"n={n} s={s}")
    """, "n=42 s=x\n"),

    ("list-basic", """
        def main() -> None:
            xs: list = [3, 1, 4, 1, 5, 9, 2, 6]
            print(len(xs))
            print(xs[0])
            print(xs[7])
    """, "8\n3\n6\n"),

    ("list-append", """
        def main() -> None:
            xs: list = []
            for i in range(0, 5):
                xs.append(i * i)
            print(xs)
    """, "[0, 1, 4, 9, 16]\n"),

    ("list-iterate", """
        def main() -> None:
            xs: list = [10, 20, 30]
            total: int = 0
            for x in xs:
                total = total + x
            print(total)
    """, "60\n"),

    ("list-sum", """
        def main() -> None:
            xs: list = [1, 2, 3, 4, 5]
            print(sum(xs))
            print(max(xs))
            print(min(xs))
    """, "15\n5\n1\n"),

    ("list-sort", """
        def main() -> None:
            xs: list = [5, 2, 9, 1]
            xs.sort()
            print(xs)
    """, "[1, 2, 5, 9]\n"),

    ("list-comprehension", """
        def main() -> None:
            xs: list = [i * 2 for i in range(0, 5)]
            print(xs)
    """, "[0, 2, 4, 6, 8]\n"),

    ("list-slice", """
        def main() -> None:
            xs: list = [0, 1, 2, 3, 4, 5]
            print(xs[1:4])
            print(xs[:3])
            print(xs[3:])
    """, "[1, 2, 3]\n[0, 1, 2]\n[3, 4, 5]\n"),

    ("dict-basic", """
        def main() -> None:
            d: dict = {"a": 1, "b": 2}
            print(d["a"])
            print(d["b"])
            print(len(d))
    """, "1\n2\n2\n"),

    ("dict-set", """
        def main() -> None:
            d: dict = {}
            d["x"] = 10
            d["y"] = 20
            print(d["x"] + d["y"])
    """, "30\n"),

    ("dict-iterate", """
        def main() -> None:
            d: dict = {"a": 1, "b": 2, "c": 3}
            total: int = 0
            for k in d:
                total = total + d[k]
            print(total)
    """, "6\n"),

    ("tuple", """
        def main() -> None:
            t: tuple = (1, 2, 3)
            print(t[0])
            print(t[2])
    """, "1\n3\n"),

    ("set-basic", """
        def main() -> None:
            s: set = {1, 2, 2, 3, 3, 3}
            print(len(s))
    """, "3\n"),

    ("ternary", """
        def pick(n: int) -> int:
            return 1 if n > 0 else -1


        def main() -> None:
            print(pick(5))
            print(pick(-5))
    """, "1\n-1\n"),

    ("default-args", """
        def add(a: int, b: int = 10) -> int:
            return a + b


        def main() -> None:
            print(add(5))
            print(add(5, 1))
    """, "15\n6\n"),

    ("many-args", """
        def add5(a: int, b: int, c: int, d: int, e: int) -> int:
            return a + b + c + d + e


        def main() -> None:
            print(add5(1, 2, 3, 4, 5))
    """, "15\n"),

    ("shadowing", """
        def f(x: int) -> int:
            y: int = x * 2
            return y


        def main() -> None:
            x: int = 100
            print(f(5))
            print(x)
    """, "10\n100\n"),

    ("global-const", """
        LIMIT: int = 50


        def clamp(v: int) -> int:
            if v > LIMIT:
                return LIMIT
            return v


        def main() -> None:
            print(clamp(10))
            print(clamp(999))
    """, "10\n50\n"),

    ("abs-min-max", """
        def main() -> None:
            print(abs(-7))
            print(min(3, 9))
            print(max(3, 9))
    """, "7\n3\n9\n"),

    ("math-fns", """
        def main() -> None:
            print(int(3.9))
            print(round(3.4))
            print(round(3.6))
    """, "3\n3\n4\n"),

    ("nested-function-calls", """
        def inc(x: int) -> int:
            return x + 1


        def twice(x: int) -> int:
            return inc(inc(x))


        def main() -> None:
            print(twice(twice(0)))
    """, "4\n"),

    ("early-return", """
        def find(xs: list, target: int) -> int:
            i: int = 0
            for x in xs:
                if x == target:
                    return i
                i = i + 1
            return -1


        def main() -> None:
            xs: list = [4, 8, 15, 16, 23, 42]
            print(find(xs, 16))
            print(find(xs, 99))
    """, "3\n-1\n"),

    ("long-chain", """
        def step(x: int) -> int:
            return (x * 3 + 7) % 100


        def main() -> None:
            v: int = 1
            for i in range(0, 10):
                v = step(v)
            print(v)
    """, "17\n"),
]

FEATURE_CASES.append(("bool-as-int2", """
    def main() -> None:
        flag: bool = False
        if flag:
            print("yes")
        else:
            print("no")
""", "no\n"))

FEATURE_CASES.append(("string-split", """
    def main() -> None:
        parts: list = "a,b,c".split(",")
        print(len(parts))
        print(parts[1])
""", "3\nb\n"))

FEATURE_CASES.append(("string-join", """
    def main() -> None:
        xs: list = ["x", "y", "z"]
        print("-".join(xs))
""", "x-y-z\n"))

FEATURE_CASES.append(("string-index", """
    def main() -> None:
        s: str = "abcdef"
        print(s[0])
        print(s[5])
""", "a\nf\n"))

FEATURE_CASES.append(("string-slice", """
    def main() -> None:
        s: str = "abcdefgh"
        print(s[2:5])
        print(s[:3])
        print(s[5:])
""", "cde\nabc\nfgh\n"))

FEATURE_CASES.append(("string-in", """
    def main() -> None:
        s: str = "hello world"
        print("world" in s)
        print("xyz" in s)
""", "True\nFalse\n"))

FEATURE_CASES.append(("list-in", """
    def main() -> None:
        xs: list = [1, 2, 3]
        print(2 in xs)
        print(9 in xs)
""", "True\nFalse\n"))

FEATURE_CASES.append(("list-reverse", """
    def main() -> None:
        xs: list = [1, 2, 3]
        xs.reverse()
        print(xs)
""", "[3, 2, 1]\n"))

FEATURE_CASES.append(("list-pop", """
    def main() -> None:
        xs: list = [1, 2, 3]
        xs.pop()
        print(xs)
        print(len(xs))
""", "[1, 2]\n2\n"))

FEATURE_CASES.append(("list-extend", """
    def main() -> None:
        a: list = [1, 2]
        b: list = [3, 4]
        a.extend(b)
        print(a)
""", "[1, 2, 3, 4]\n"))

FEATURE_CASES.append(("dict-get", """
    def main() -> None:
        d: dict = {"a": 1}
        print(d.get("a", 0))
        print(d.get("zzz", 99))
""", "1\n99\n"))

FEATURE_CASES.append(("dict-keys-count", """
    def main() -> None:
        d: dict = {"a": 1, "b": 2, "c": 3}
        print(len(d))
        print("b" in d)
""", "3\nTrue\n"))

FEATURE_CASES.append(("nested-list", """
    def main() -> None:
        grid: list = [[1, 2], [3, 4]]
        print(grid[0][1])
        print(grid[1][0])
""", "2\n3\n"))

FEATURE_CASES.append(("deep-recursion", """
    def count_down(n: int) -> int:
        if n == 0:
            return 0
        return 1 + count_down(n - 1)


    def main() -> None:
        print(count_down(200))
""", "200\n"))

FEATURE_CASES.append(("swap-vars", """
    def main() -> None:
        a: int = 1
        b: int = 2
        t: int = a
        a = b
        b = t
        print(a)
        print(b)
""", "2\n1\n"))

FEATURE_CASES.append(("accumulate-float", """
    def main() -> None:
        total: float = 0.0
        for i in range(0, 4):
            total = total + 0.25
        print(total)
""", "1.0\n"))

FEATURE_CASES.append(("modulo-negative", """
    def main() -> None:
        print(7 % 3)
        print(8 % 4)
        print(9 % 3)
""", "1\n0\n0\n"))

FEATURE_CASES.append(("bitwise-ish", """
    def main() -> None:
        print(12 // 5)
        print(12 - 5 * 2)
""", "2\n2\n"))

FEATURE_CASES.append(("multi-statement-line", """
    def main() -> None:
        x: int = 1
        y: int = 2
        z: int = 3
        print(x + y + z)
""", "6\n"))

FEATURE_CASES.append(("empty-func", """
    def nothing() -> int:
        return 0


    def main() -> None:
        print(nothing())
""", "0\n"))


@case("bool-as-int", "language")
def _bool_case(ctx: Ctx) -> str:
    return _feature_case("""
        def main() -> None:
            flag: bool = True
            if flag:
                print("yes")
            else:
                print("no")
    """, "yes\n")(ctx)


_FAST_ORDER = ["rust", "cpp", "go", "zig", "kotlin", "csharp"]


def _feature_case(src: str, expected: str, backends_only: tuple = ()):
    """Run a program on every available backend and require identical output.

    A backend that fails to build, produces no output, or prints something
    different is a bug — all of them are reported, not just the first.
    """
    def fn(ctx: Ctx) -> str:
        order = [b for b in _FAST_ORDER
                 if b in ctx.backends and (not backends_only or b in backends_only)]
        if not order:
            raise AssertionError("no backend available")
        problems: list[str] = []
        ok: list[str] = []
        for b in order:
            try:
                out, r = ctx.build_and_run(src, b)
            except subprocess.TimeoutExpired:
                problems.append(f"{b}: timed out")
                continue
            if r.returncode != 0:
                tail = (r.stdout + r.stderr).strip().splitlines()
                problems.append(f"{b}: build failed — {tail[-1][:160] if tail else '?'}")
                continue
            got = out.replace("\r\n", "\n")
            if not got.strip():
                problems.append(f"{b}: produced no output")
            elif got != expected:
                problems.append(
                    f"{b}: expected {expected!r} got {got!r}")
            else:
                ok.append(b)
        if problems:
            raise AssertionError(
                f"{len(ok)}/{len(order)} ok ({','.join(ok) or 'none'}); "
                + "; ".join(problems))
        return f"all {len(ok)} backends agree"
    return fn


for _name, _src, _exp in FEATURE_CASES:
    case(_name, "language", needs="rust")(_feature_case(_src, _exp))


# ===========================================================================
# frontends
# ===========================================================================

@case("frontend-hybrid", "frontend", needs="rust")
def t_frontend_hybrid(ctx: Ctx) -> str:
    src = '''
        <double:typescript>
        export function double(x: number): number {
            return x * 2;
        }
        </double>

        <label>
        def label(n: int) -> int:
            return n + 100
        </label>


        def main() -> None:
            print(@double(21))
            print(@label(1))
    '''
    out, r = ctx.build_and_run(src, "rust")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "42\n101\n", f"got {out!r}"
    return "mixed flavours + named blocks"


@case("frontend-ts-extension", "frontend", needs="rust")
def t_frontend_ts_ext(ctx: Ctx) -> str:
    src = """
        export function triple(x: number): number {
            return x * 3;
        }

        export function main(): void {
            console.log(triple(14));
        }
    """
    out, r = ctx.build_and_run(src, "rust", filename="main.ge.ts")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "42\n", f"got {out!r}"
    return ".ge.ts lowered"


@case("frontend-py-extension", "frontend", needs="rust")
def t_frontend_py_ext(ctx: Ctx) -> str:
    src = """
        def main() -> None:
            print(6 * 7)
    """
    out, r = ctx.build_and_run(src, "rust", filename="main.ge.py")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "42\n", f"got {out!r}"
    return ".ge.py lowered"


@case("frontend-ts-math", "frontend", needs="rust")
def t_frontend_ts_math(ctx: Ctx) -> str:
    src = """
        export function main(): void {
            console.log(Math.idiv(17, 5));
            console.log(Math.floor(3.9));
        }
    """
    out, r = ctx.build_and_run(src, "rust", filename="main.ge.ts")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "3\n3\n", f"got {out!r}"
    return "Math.* mapped"


@case("frontend-ts-array", "frontend", needs="rust")
def t_frontend_ts_array(ctx: Ctx) -> str:
    src = """
        export function main(): void {
            const xs: number[] = [1, 2, 3];
            console.log(xs.length);
            console.log(xs[0]);
        }
    """
    out, r = ctx.build_and_run(src, "rust", filename="main.ge.ts")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "3\n1\n", f"got {out!r}"
    return "TS arrays"


@case("frontend-ts-template", "frontend", needs="rust")
def t_frontend_ts_template(ctx: Ctx) -> str:
    src = """
        export function main(): void {
            const n: number = 42;
            console.log(`value is ${n}`);
        }
    """
    out, r = ctx.build_and_run(src, "rust", filename="main.ge.ts")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "value is 42\n", f"got {out!r}"
    return "template literals"


@case("frontend-ts-for", "frontend", needs="rust")
def t_frontend_ts_for(ctx: Ctx) -> str:
    src = """
        export function main(): void {
            let total: number = 0;
            for (let i: number = 1; i <= 10; i = i + 1) {
                total = total + i;
            }
            console.log(total);
        }
    """
    out, r = ctx.build_and_run(src, "rust", filename="main.ge.ts")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "55\n", f"got {out!r}"
    return "TS for loop"


@case("frontend-ts-if", "frontend", needs="rust")
def t_frontend_ts_if(ctx: Ctx) -> str:
    src = """
        export function classify(n: number): number {
            if (n < 0) {
                return -1;
            } else if (n === 0) {
                return 0;
            } else {
                return 1;
            }
        }

        export function main(): void {
            console.log(classify(-3));
            console.log(classify(0));
            console.log(classify(3));
        }
    """
    out, r = ctx.build_and_run(src, "rust", filename="main.ge.ts")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "-1\n0\n1\n", f"got {out!r}"
    return "TS conditionals"


@case("named-block-forward", "frontend", needs="rust")
def t_named_forward(ctx: Ctx) -> str:
    """A call may appear before the block it names."""
    src = '''
        def main() -> None:
            print(@later(5))


        <later>
        def later(x: int) -> int:
            return x * 8
        </later>
    '''
    out, r = ctx.build_and_run(src, "rust")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "40\n", f"got {out!r}"
    return "forward block reference"


@case("named-block-pinned", "frontend", needs="rust")
def t_named_pinned(ctx: Ctx) -> str:
    src = '''
        <scaled:typescript>
        export function scaled(x: number): number {
            return x * SCALE;
        }
        </scaled>

        # ge:typescript
        const SCALE: number = 3;

        <run>
        def run(n: int) -> int:
            return @scaled(n)
        </run>


        def main() -> None:
            print(@run(7))
    '''
    out, r = ctx.build_and_run(src, "rust")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "21\n", f"got {out!r}"
    return "pinned chunk + cross-flavour"


@case("decorator-rust", "frontend", needs="rust")
def t_decorator_rust(ctx: Ctx) -> str:
    src = """
        from pyeffic.backends import rust


        @rust
        def hot(x: int) -> int:
            return x * x


        def main() -> None:
            print(hot(9))
    """
    out, r = ctx.build_and_run(src, "rust")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "81\n", f"got {out!r}"
    return "@rust honoured"


@case("decorator-cpp", "frontend", needs="rust")
def t_decorator_cpp(ctx: Ctx) -> str:
    src = """
        from pyeffic.backends import cpp


        @cpp
        def hot(x: int) -> int:
            return x * x


        def main() -> None:
            print(hot(9))
    """
    out, r = ctx.build_and_run(src, "rust")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "81\n", f"got {out!r}"
    return "@cpp honoured in a rust program"


# ===========================================================================
# modules
# ===========================================================================

@case("modules-relative-import", "modules", needs="rust")
def t_modules_relative(ctx: Ctx) -> str:
    sub = ctx.workdir / "sub"
    sub.mkdir(exist_ok=True)
    (sub / "lib.ge").write_text(
        "def helper(x: int) -> int:\n    return x + 1\n", encoding="utf-8")
    (sub / "main.ge").write_text(
        "from lib import helper\n\n\n"
        "def main() -> None:\n    print(helper(41))\n", encoding="utf-8")
    r = ctx.run(["build", "main.ge", "--backend", "rust", "-o", "out"], cwd=sub)
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    exe = find_exe(sub / "out")
    assert exe, "no binary"
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.stdout.replace("\r\n", "\n") == "42\n", f"got {run.stdout!r}"
    return "relative import works"


@case("modules-transitive", "modules", needs="rust")
def t_modules_transitive(ctx: Ctx) -> str:
    sub = ctx.workdir / "sub2"
    sub.mkdir(exist_ok=True)
    (sub / "a.ge").write_text(
        "def fa(x: int) -> int:\n    return x * 2\n", encoding="utf-8")
    (sub / "b.ge").write_text(
        "from a import fa\n\n\n"
        "def fb(x: int) -> int:\n    return fa(x) + 1\n", encoding="utf-8")
    (sub / "main.ge").write_text(
        "from b import fb\n\n\n"
        "def main() -> None:\n    print(fb(20))\n", encoding="utf-8")
    r = ctx.run(["build", "main.ge", "--backend", "rust", "-o", "out"], cwd=sub)
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    exe = find_exe(sub / "out")
    assert exe, "no binary"
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.stdout.replace("\r\n", "\n") == "41\n", f"got {run.stdout!r}"
    return "transitive import resolves"


@case("modules-mixed-extensions", "modules", needs="rust")
def t_modules_mixed_ext(ctx: Ctx) -> str:
    sub = ctx.workdir / "sub3"
    sub.mkdir(exist_ok=True)
    (sub / "tslib.ge.ts").write_text(
        "export function tsf(x: number): number {\n"
        "    return x * 5;\n"
        "}\n", encoding="utf-8")
    (sub / "main.ge").write_text(
        "from tslib import tsf\n\n\n"
        "def main() -> None:\n    print(tsf(8))\n", encoding="utf-8")
    r = ctx.run(["build", "main.ge", "--backend", "rust", "-o", "out"], cwd=sub)
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    exe = find_exe(sub / "out")
    assert exe, "no binary"
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert run.stdout.replace("\r\n", "\n") == "40\n", f"got {run.stdout!r}"
    return "TS module imported from Python module"


# ===========================================================================
# mixed backends
# ===========================================================================

@case("mixed-rust-cpp", "mixed", needs="rust")
def t_mixed_rust_cpp(ctx: Ctx) -> str:
    if "cpp" not in ctx.backends:
        return "skipped: no cpp"
    src = """
        from pyeffic.backends import cpp, rust


        @cpp
        def heavy(x: int) -> int:
            return x * x + 1


        @rust
        def main() -> None:
            print(heavy(7))
    """
    out, r = ctx.build_and_run(src, "rust")
    assert r.returncode == 0, (r.stdout + r.stderr)[-700:]
    assert out.replace("\r\n", "\n") == "50\n", f"got {out!r}"
    return "one binary from rust + cpp"


@case("mixed-preamble", "mixed", needs="rust")
def t_mixed_preamble(ctx: Ctx) -> str:
    src = '''
        from pyeffic.backends import rust

        ge_preamble("rust", "const BIAS: i64 = 100;")


        @rust
        def shifted(x: int) -> int:
            return x + BIAS


        def main() -> None:
            print(shifted(23))
    '''
    out, r = ctx.build_and_run(src, "rust")
    assert r.returncode == 0, (r.stdout + r.stderr)[-700:]
    assert out.replace("\r\n", "\n") == "123\n", f"got {out!r}"
    return "ge_preamble injected"


@case("mixed-ge-inline", "mixed", needs="rust")
def t_ge_inline(ctx: Ctx) -> str:
    src = '''
        from pyeffic.backends import rust

        ge_preamble("rust", "fn triple(x: i64) -> i64 { x * 3 }")


        @rust
        def use_inline(x: int) -> int:
            return ge_inline("rust", "triple(x)")


        def main() -> None:
            print(use_inline(14))
    '''
    out, r = ctx.build_and_run(src, "rust")
    assert r.returncode == 0, (r.stdout + r.stderr)[-700:]
    assert out.replace("\r\n", "\n") == "42\n", f"got {out!r}"
    return "ge_inline works"


# ===========================================================================
# error handling  (the CLI must fail loudly, never silently)
# ===========================================================================

def _expect_failure(ctx: Ctx, args: list[str], *, why: str,
                    expect: str | None = None) -> str:
    r = ctx.run(args)
    assert r.returncode != 0, f"{why}: expected failure, got exit 0"
    blob = r.stdout + r.stderr
    if expect:
        assert expect.lower() in blob.lower(), \
            f"{why}: {expect!r} not in output:\n{blob[:400]}"
    return "failed as expected"


@case("err-missing-file", "errors")
def t_err_missing_file(ctx: Ctx) -> str:
    return _expect_failure(ctx, ["build", "does-not-exist.ge"],
                           why="missing input")


@case("err-bad-backend", "errors")
def t_err_bad_backend(ctx: Ctx) -> str:
    ctx.write("ok.ge", "def main() -> None:\n    print(1)\n")
    return _expect_failure(
        ctx, ["build", "ok.ge", "--backend", "cobol"],
        why="unknown backend", expect="invalid choice")


@case("err-syntax", "errors")
def t_err_syntax(ctx: Ctx) -> str:
    ctx.write("bad.ge", "def main( -> None:\n    print(1)\n")
    return _expect_failure(ctx, ["build", "bad.ge"], why="syntax error")


@case("err-syntax-analyze", "errors")
def t_err_syntax_analyze(ctx: Ctx) -> str:
    ctx.write("bad2.ge", "def f(x: int) -> int\n    return x\n")
    return _expect_failure(ctx, ["analyze", "bad2.ge"], why="syntax error in analyze")


@case("err-unknown-function", "errors", needs="rust")
def t_err_unknown_fn(ctx: Ctx) -> str:
    ctx.write("undef.ge",
              "def main() -> None:\n    print(not_defined_anywhere(1))\n")
    r = ctx.run(["build", "undef.ge", "--backend", "rust", "-o", "out"])
    assert r.returncode != 0, "undefined call should not build"
    return "undefined call rejected"


@case("err-bad-flag", "errors")
def t_err_bad_flag(ctx: Ctx) -> str:
    ctx.write("ok2.ge", "def main() -> None:\n    print(1)\n")
    return _expect_failure(ctx, ["build", "ok2.ge", "--nonsense"],
                           why="unknown flag")


@case("err-analyze-clean", "errors")
def t_err_analyze_clean(ctx: Ctx) -> str:
    ctx.write("fine.ge", "def main() -> None:\n    print(42)\n")
    r = ctx.run(["analyze", "fine.ge"])
    assert r.returncode == 0, (r.stdout + r.stderr)[-400:]
    return "clean program analyses"


@case("err-reserved-cpp", "errors", needs="cpp")
def t_err_reserved_cpp(ctx: Ctx) -> str:
    """A function named after a C++ type must still compile."""
    src = """
        def double(x: int) -> int:
            return x * 2


        def main() -> None:
            print(double(21))
    """
    out, r = ctx.build_and_run(src, "cpp")
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "42\n", f"got {out!r}"
    return "reserved name escaped"


@case("err-reserved-csharp", "errors", needs="csharp")
def t_err_reserved_csharp(ctx: Ctx) -> str:
    src = """
        def f(base: int, years: int) -> int:
            result: int = base
            for i in range(0, years):
                result = result + result // 10
            return result


        def main() -> None:
            print(f(100, 2))
    """
    out, r = ctx.build_and_run(src, "csharp", timeout=600)
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    assert out.replace("\r\n", "\n") == "121\n", f"got {out!r}"
    return "C# keyword escaped"


# ===========================================================================
# scaffolding
# ===========================================================================

@case("create-desktop", "scaffold")
def t_create_desktop(ctx: Ctx) -> str:
    r = ctx.run(["create", "proj1", "--template", "desktop-gui", "-y"])
    assert r.returncode == 0, (r.stdout + r.stderr)[-400:]
    root = ctx.workdir / "proj1"
    for rel in ("app/main.ge.py", "desktop/main.ge.py", "ge.toml",
                "tests/test_app.py"):
        assert (root / rel).exists(), f"missing {rel}"
    return "desktop-gui scaffold"


@case("create-web", "scaffold")
def t_create_web(ctx: Ctx) -> str:
    r = ctx.run(["create", "proj2", "--template", "web-react", "-y"])
    assert r.returncode == 0, (r.stdout + r.stderr)[-400:]
    root = ctx.workdir / "proj2"
    assert (root / "ge.toml").exists(), "no ge.toml"
    return "web-react scaffold"


@case("create-no-buildpy", "scaffold")
def t_create_no_buildpy(ctx: Ctx) -> str:
    """The scaffold must not reference files it does not create."""
    r = ctx.run(["create", "proj3", "--template", "desktop-gui", "-y"])
    assert r.returncode == 0, r.stderr[:300]
    root = ctx.workdir / "proj3"
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in root.rglob("*.md"))
    assert "build.py" not in blob, \
        "scaffold tells the user to run build.py, which it does not create"
    return "no dangling build.py reference"


@case("create-layers", "scaffold")
def t_create_layers(ctx: Ctx) -> str:
    """The desktop template must keep memory/core/ui separated."""
    r = ctx.run(["create", "proj4", "--template", "desktop-gui", "-y"])
    assert r.returncode == 0, r.stderr[:300]
    root = ctx.workdir / "proj4" / "app"
    for layer in ("memory", "core", "ui"):
        d = root / layer
        assert d.is_dir(), f"missing layer {layer}"
        assert list(d.glob("*.ge.py")), f"{layer}/ has no modules"
    return "memory/core/ui separated"


@case("build-scaffold", "scaffold", needs="rust")
def t_build_scaffold(ctx: Ctx) -> str:
    r = ctx.run(["create", "proj5", "--template", "desktop-gui", "-y"])
    assert r.returncode == 0, r.stderr[:300]
    root = ctx.workdir / "proj5"
    b = ctx.run(["build", "desktop/main.ge.py", "-o", "out"], cwd=root,
                timeout=600)
    assert b.returncode == 0, (b.stdout + b.stderr)[-700:]
    assert find_exe(root / "out"), "scaffold produced no binary"
    return "scaffolded project builds"


# ===========================================================================
# UI generation
# ===========================================================================

UI_SOURCE = '''
Window {
  title: "Demo"
  Column {
    padding: 24
    children:
      Text "Hello" style="headline"
      TextField state="query" hint="type here"
      ElevatedButton "Run" on_click=Action(call="compute")
      Text state="result" style="value"
  }
}
'''


@case("react-generate", "ui")
def t_react_generate(ctx: Ctx) -> str:
    ctx.write("ui/main.ge.ui", UI_SOURCE)
    r = ctx.run(["react", "ui/main.ge.ui", "--app-name", "demoapp"], timeout=120)
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    out = ctx.workdir / "build" / "web"
    app = next(out.rglob("App.tsx"), None)
    assert app, f"no App.tsx under {out}"
    assert (app.parent / "components").is_dir(), "no components dir"
    return "React project generated"


@case("react-components", "ui")
def t_react_components(ctx: Ctx) -> str:
    ctx.write("ui2/main.ge.ui", UI_SOURCE)
    r = ctx.run(["react", "ui2/main.ge.ui", "--app-name", "demoapp2"], timeout=120)
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    comps = list((ctx.workdir / "build" / "web").rglob("components/*.tsx"))
    assert len(comps) >= 4, f"expected several components, got {len(comps)}"
    return f"{len(comps)} components"


@case("react-preserves", "ui")
def t_react_preserves(ctx: Ctx) -> str:
    """Regeneration must not clobber a user-edited file."""
    ctx.write("ui3/main.ge.ui", UI_SOURCE)
    r = ctx.run(["react", "ui3/main.ge.ui", "--app-name", "demoapp3"], timeout=120)
    assert r.returncode == 0, (r.stdout + r.stderr)[-500:]
    app = next((ctx.workdir / "build" / "web").rglob("App.tsx"))
    marker = "// USER EDIT MARKER"
    app.write_text(app.read_text(encoding="utf-8") + "\n" + marker,
                   encoding="utf-8")
    r2 = ctx.run(["react", "ui3/main.ge.ui", "--app-name", "demoapp3"], timeout=120)
    assert r2.returncode == 0, (r2.stdout + r2.stderr)[-500:]
    assert marker in app.read_text(encoding="utf-8"), \
        "regeneration overwrote a user-edited file without --force"
    return "user edits preserved"


@case("flutter-generate", "ui")
def t_flutter_generate(ctx: Ctx) -> str:
    ctx.write("ui4/main.ge.ui", UI_SOURCE)
    r = ctx.run(["flutter", "ui4/main.ge.ui", "--app-name", "flutterdemo"],
                timeout=180)
    assert r.returncode == 0, (r.stdout + r.stderr)[-600:]
    dart = list((ctx.workdir / "build" / "mobile").rglob("*.dart"))
    assert dart, "no Dart generated"
    return f"{len(dart)} dart files"


@case("ui-bad-source", "ui")
def t_ui_bad_source(ctx: Ctx) -> str:
    ctx.write("uibad/main.ge.ui", "Window { title: \n")
    return _expect_failure(ctx, ["react", "uibad/main.ge.ui"],
                           why="malformed UI DSL")


# ===========================================================================
# analysis
# ===========================================================================

@case("analyze-ge", "analysis")
def t_analyze_ge(ctx: Ctx) -> str:
    ctx.write("an1.ge", '''
        <f:typescript>
        export function f(x: number): number {
            return x + 1;
        }
        </f>


        def main() -> None:
            print(@f(1))
    ''')
    r = ctx.run(["analyze", "an1.ge"])
    assert r.returncode == 0, \
        f"analyze failed on a hybrid .ge file:\n{(r.stdout + r.stderr)[-600:]}"
    return "hybrid .ge analyses"


@case("analyze-ts", "analysis")
def t_analyze_ts(ctx: Ctx) -> str:
    ctx.write("an2.ge.ts", """
        export function g(x: number): number {
            return x * 2;
        }

        export function main(): void {
            console.log(g(2));
        }
    """)
    r = ctx.run(["analyze", "an2.ge.ts"])
    assert r.returncode == 0, \
        f"analyze failed on .ge.ts:\n{(r.stdout + r.stderr)[-600:]}"
    return ".ge.ts analyses"


@case("analyze-py", "analysis")
def t_analyze_py(ctx: Ctx) -> str:
    ctx.write("an3.ge.py", "def main() -> None:\n    print(1)\n")
    r = ctx.run(["analyze", "an3.ge.py"])
    assert r.returncode == 0, (r.stdout + r.stderr)[-400:]
    return ".ge.py analyses"


@case("analyze-named-block", "analysis")
def t_analyze_named_block(ctx: Ctx) -> str:
    ctx.write("an4.ge", '''
        <helper>
        def helper(x: int) -> int:
            return x * 3
        </helper>


        def main() -> None:
            print(@helper(4))
    ''')
    r = ctx.run(["analyze", "an4.ge"])
    assert r.returncode == 0, \
        f"analyze failed on named blocks:\n{(r.stdout + r.stderr)[-600:]}"
    return "named blocks analyse"


# ===========================================================================
# packaging
# ===========================================================================

@case("pack-roundtrip", "package", needs="rust")
def t_pack_roundtrip(ctx: Ctx) -> str:
    ctx.write("pk/main.ge", "def main() -> None:\n    print(7 * 6)\n")
    r = ctx.run(["pack", "pk/main.ge"], timeout=180)
    assert r.returncode == 0, (r.stdout + r.stderr)[-600:]
    pkgs = list(ctx.workdir.rglob("*.ge"))
    pkgs = [p for p in pkgs if p.name != "main.ge"]
    assert pkgs, f"no package produced:\n{(r.stdout + r.stderr)[-400:]}"
    return f"packed {pkgs[0].name}"


# ===========================================================================
# differential + golden
# ===========================================================================

@case("diff-corpus", "verify", needs="rust")
def t_diff_corpus(ctx: Ctx) -> str:
    r = ctx.run(["diff", "tests/differential"], cwd=REPO, timeout=900)
    assert r.returncode == 0, (r.stdout + r.stderr)[-900:]
    m = re.search(r"mismatches\s*:\s*(\d+)", r.stdout)
    if m:
        assert m.group(1) == "0", f"{m.group(1)} mismatches"
    return "all backends agree with CPython"


@case("diff-single-backend", "verify", needs="rust")
def t_diff_single(ctx: Ctx) -> str:
    r = ctx.run(["diff", "tests/differential", "--backends", "rust"],
                cwd=REPO, timeout=600)
    assert r.returncode == 0, (r.stdout + r.stderr)[-700:]
    return "single-backend diff"


@case("golden-drift-detected", "verify")
def t_golden_drift(ctx: Ctx) -> str:
    """A deliberate change to a golden must be reported."""
    golden = REPO / "tests" / "golden"
    target = next(golden.rglob("*.golden"), None)
    assert target, "no golden files"
    backup = target.read_text(encoding="utf-8")
    try:
        target.write_text(backup + "\n// drift probe\n", encoding="utf-8")
        r = ctx.run(["golden", "--check", "--no-behaviour"], cwd=REPO, timeout=180)
        assert r.returncode != 0, "drift was not detected"
        assert "drift" in (r.stdout + r.stderr).lower()
    finally:
        target.write_text(backup, encoding="utf-8")
    return "drift caught and reverted"


# ===========================================================================
# runner
# ===========================================================================

def detect_backends(cli: list[str], workdir: Path) -> set[str]:
    import json
    try:
        r = subprocess.run(_spawnable([*cli, "doctor", "--json"]), capture_output=True,
                           text=True, timeout=180, cwd=str(workdir),
                           encoding="utf-8", errors="replace")
        d = json.loads(r.stdout)
        return set(d.get("available_backends", []))
    except Exception:
        return set()


def _safe(text: str) -> str:
    """Make text printable on any console.

    Compiler diagnostics contain characters the Windows console codec cannot
    encode (curly quotes, box drawing), which would otherwise abort the whole
    run with UnicodeEncodeError while printing a failure.
    """
    enc = sys.stdout.encoding or "utf-8"
    return str(text).encode(enc, errors="replace").decode(enc, errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-k", "--filter", default="",
                    help="only run cases whose name contains this")
    ap.add_argument("--group", default="", help="only run this group")
    ap.add_argument("--backend", default="", help="only cases needing this backend")
    ap.add_argument("--cli", default="", help="CLI command (default: local source)")
    ap.add_argument("--list", action="store_true", help="list cases and exit")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.list:
        for c in CASES:
            need = f" [{c.needs}]" if c.needs else ""
            print(f"{c.group:10} {c.name}{need}")
        print(f"\n{len(CASES)} cases")
        return 0

    selected = CASES
    if args.filter:
        selected = [c for c in selected if args.filter in c.name]
    if args.group:
        selected = [c for c in selected if c.group == args.group]
    if args.backend:
        selected = [c for c in selected if c.needs == args.backend]

    if not selected:
        print("no cases matched")
        return 1

    cli = args.cli.split() if args.cli else [sys.executable, "-m", "pyeffic.ge_cli"]

    root = Path(tempfile.mkdtemp(prefix="ge-e2e-"))
    try:
        print(f"GE end-to-end tests")
        print(f"  cli     : {' '.join(cli)}")
        print(f"  workdir : {root}")
        backends = detect_backends(cli, root)
        print(f"  backends: {', '.join(sorted(backends)) or 'none'}")
        print(f"  cases   : {len(selected)}")
        print()

        def run_one(c: Case) -> Result:
            if c.needs and c.needs not in backends:
                return Result(c.name, c.group, SKIP, f"no {c.needs}")
            d = root / c.name
            d.mkdir(parents=True, exist_ok=True)
            ctx = Ctx(cli=cli, workdir=d, backends=backends,
                      verbose=args.verbose)
            t0 = time.time()
            try:
                detail = c.fn(ctx) or "ok"
                return Result(c.name, c.group, PASS, str(detail),
                              time.time() - t0)
            except AssertionError as e:
                return Result(c.name, c.group, FAIL, str(e), time.time() - t0)
            except subprocess.TimeoutExpired:
                return Result(c.name, c.group, FAIL, "timed out",
                              time.time() - t0)
            except Exception as e:  # noqa: BLE001
                return Result(c.name, c.group, FAIL,
                              f"{type(e).__name__}: {e}", time.time() - t0)

        results: list[Result] = []
        with futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            for res in ex.map(run_one, selected):
                results.append(res)
                mark = {PASS: "ok  ", FAIL: "FAIL", SKIP: "skip"}[res.status]
                line = _safe(f"  {mark} {res.case:<28} {res.detail[:70]}")
                print(line, flush=True)

        failed = [r for r in results if r.status == FAIL]
        skipped = [r for r in results if r.status == SKIP]
        passed = [r for r in results if r.status == PASS]

        print()
        print("=" * 70)
        print(f"  passed  : {len(passed)}")
        print(f"  failed  : {len(failed)}")
        print(f"  skipped : {len(skipped)}")
        if failed:
            print()
            print("failures:")
            for r in failed:
                print(f"\n  [{r.group}] {r.case}")
                for line in _safe(str(r.detail)).splitlines()[:12]:
                    print(f"      {line}")
        print("=" * 70)
        return 1 if failed else 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
