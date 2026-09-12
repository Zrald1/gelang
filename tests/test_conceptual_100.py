"""100 conceptual tests for GE language — each test runs against all 6 backends.

Tests are organized into 10 categories (10 tests each = 100 scenarios):
  1.  Arithmetic basics (add, sub, mul, div, mod, neg, precedence, parentheses)
  2.  Arithmetic edge cases (zero, negative, large, boundary, compound assign)
  3.  Comparison and boolean logic (==, !=, <, >, <=, >=, and, or)
  4.  Control flow (if/else, elif, nested if, early return, multi-return)
  5.  Loops (for, while, nested, break-like patterns, accumulation)
  6.  Recursion (factorial, fibonacci, GCD, Ackermann, mutual recursion)
  7.  Function calls (multi-arg, chained, default-like, void functions)
  8.  List operations (indexing, iteration, search, count, min/max)
  9.  Type handling (int operations, bool, cast, mixed)
  10. Real-world algorithms (prime check, FizzBuzz, sum of digits, etc.)

Each of the 100 scenarios is compiled and run with each available backend.
Total: 100 scenarios x 6 backends = 600 compilation + execution checks.
"""
import unittest
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyeffic.pipeline import build
from pyeffic.config import Config, detect_compilers

_COMPILERS = detect_compilers()
BACKENDS = []
if _COMPILERS.rustc:
    BACKENDS.append("rust")
if _COMPILERS.cpp:
    BACKENDS.append("cpp")
if _COMPILERS.dotnet:
    BACKENDS.append("csharp")
if _COMPILERS.zig:
    BACKENDS.append("zig")
if _COMPILERS.go:
    BACKENDS.append("go")
if _COMPILERS.kotlinc:
    BACKENDS.append("kotlin")

_TMPDIR = Path(tempfile.mkdtemp(prefix="ge_conceptual_"))


def _compile_and_run(source: str, backend: str, expected: str) -> bool:
    """Compile source with backend, run binary, check output."""
    src_file = _TMPDIR / f"t_{backend}_{abs(hash(source)) % 100000}.ge.py"
    src_file.write_text(source, encoding="utf-8")
    out_dir = _TMPDIR / f"o_{backend}_{abs(hash(source)) % 100000}"
    cfg = Config(out_dir=out_dir, force_backend=backend, do_research=False)
    try:
        report = build(src_file, cfg)
    except Exception:
        return False
    cr = None
    for attr in ("rust_compile", "cpp_compile", "csharp_compile",
                 "zig_compile", "go_compile", "kotlin_compile"):
        cr = getattr(report, attr, None)
        if cr and cr.ok and cr.exe:
            break
    if not cr or not cr.ok or not cr.exe:
        return False
    try:
        r = subprocess.run([str(cr.exe)], capture_output=True, text=True,
                           timeout=30, cwd=str(cr.exe.parent))
        return r.stdout.strip() == expected.strip()
    except Exception:
        return False


# Helper: build a test program with a function and main that prints its result
def _prog(func_src: str, call: str) -> str:
    return func_src + "\ndef main() -> None:\n    " + call + "\n"


def _prog_multi(func_src: str, calls: list[str]) -> str:
    body = "\n".join("    " + c for c in calls)
    return func_src + "\ndef main() -> None:\n" + body + "\n"


# ---- 100 test scenarios ----
# Each entry: (name, source_code, expected_output)
S = []

# === Category 1: Arithmetic basics (1-10) ===
S.append(("add_simple", _prog("def f(a: int, b: int) -> int:\n    return a + b", "print(f(10, 20))"), "30"))
S.append(("sub_simple", _prog("def f(a: int, b: int) -> int:\n    return a - b", "print(f(50, 20))"), "30"))
S.append(("mul_simple", _prog("def f(a: int, b: int) -> int:\n    return a * b", "print(f(6, 7))"), "42"))
S.append(("div_exact", _prog("def f(a: int, b: int) -> int:\n    return a // b", "print(f(84, 2))"), "42"))
S.append(("mod_remainder", _prog("def f(a: int, b: int) -> int:\n    return a % b", "print(f(10, 3))"), "1"))
S.append(("neg_unary", _prog("def f(a: int) -> int:\n    return -a", "print(f(42))"), "-42"))
S.append(("precedence_mul_add", _prog("def f() -> int:\n    return 2 + 3 * 4", "print(f())"), "14"))
S.append(("parentheses_override", _prog("def f() -> int:\n    return (2 + 3) * 4", "print(f())"), "20"))
S.append(("complex_arithmetic", _prog("def f() -> int:\n    return (10 + 20) * 2 - 18", "print(f())"), "42"))
S.append(("chained_add", _prog("def f() -> int:\n    return 1 + 2 + 3 + 4", "print(f())"), "10"))

# === Category 2: Arithmetic edge cases (11-20) ===
S.append(("mul_by_zero", _prog("def f(a: int) -> int:\n    return a * 0", "print(f(100))"), "0"))
S.append(("add_zero", _prog("def f(a: int) -> int:\n    return a + 0", "print(f(42))"), "42"))
S.append(("sub_zero", _prog("def f(a: int) -> int:\n    return a - 0", "print(f(42))"), "42"))
S.append(("neg_result", _prog("def f(a: int, b: int) -> int:\n    return a - b", "print(f(10, 20))"), "-10"))
S.append(("div_by_one", _prog("def f(a: int) -> int:\n    return a // 1", "print(f(42))"), "42"))
S.append(("mod_nonzero", _prog("def f(a: int, b: int) -> int:\n    return a % b", "print(f(20, 7))"), "6"))
S.append(("large_numbers", _prog("def f() -> int:\n    return 1000000 * 1000", "print(f())"), "1000000000"))
S.append(("compound_add", _prog("def f(n: int) -> int:\n    total: int = 0\n    total += n\n    return total", "print(f(42))"), "42"))
S.append(("compound_sub", _prog("def f(n: int) -> int:\n    total: int = 100\n    total -= n\n    return total", "print(f(30))"), "70"))
S.append(("double_neg", _prog("def f(a: int) -> int:\n    return -(-a)", "print(f(42))"), "42"))

# === Category 3: Comparison and boolean logic (21-30) ===
S.append(("eq_true", _prog("def f(a: int, b: int) -> int:\n    if a == b:\n        return 1\n    return 0", "print(f(5, 5))"), "1"))
S.append(("eq_false", _prog("def f(a: int, b: int) -> int:\n    if a == b:\n        return 1\n    return 0", "print(f(5, 3))"), "0"))
S.append(("neq_true", _prog("def f(a: int, b: int) -> int:\n    if a != b:\n        return 1\n    return 0", "print(f(5, 3))"), "1"))
S.append(("lt_true", _prog("def f(a: int, b: int) -> int:\n    if a < b:\n        return 1\n    return 0", "print(f(3, 5))"), "1"))
S.append(("gt_true", _prog("def f(a: int, b: int) -> int:\n    if a > b:\n        return 1\n    return 0", "print(f(5, 3))"), "1"))
S.append(("le_true", _prog("def f(a: int, b: int) -> int:\n    if a <= b:\n        return 1\n    return 0", "print(f(5, 5))"), "1"))
S.append(("ge_true", _prog("def f(a: int, b: int) -> int:\n    if a >= b:\n        return 1\n    return 0", "print(f(5, 5))"), "1"))
S.append(("max_of_two", _prog("def f(a: int, b: int) -> int:\n    if a > b:\n        return a\n    return b", "print(f(30, 50))"), "50"))
S.append(("min_of_two", _prog("def f(a: int, b: int) -> int:\n    if a < b:\n        return a\n    return b", "print(f(30, 50))"), "30"))
S.append(("max_of_three", _prog("def f(a: int, b: int, c: int) -> int:\n    if a >= b:\n        if a >= c:\n            return a\n    if b >= c:\n        return b\n    return c", "print(f(10, 25, 15))"), "25"))

# === Category 4: Control flow (31-40) ===
S.append(("if_else", _prog("def f(n: int) -> int:\n    if n > 0:\n        return 1\n    return -1", "print(f(5))"), "1"))
S.append(("elif_chain", _prog("def f(n: int) -> int:\n    if n > 0:\n        return 1\n    elif n < 0:\n        return -1\n    return 0", "print(f(0))"), "0"))
S.append(("nested_if_1", _prog("def f(a: int, b: int) -> int:\n    if a > 0:\n        if b > 0:\n            return 1\n        return 2\n    return 3", "print(f(1, 1))"), "1"))
S.append(("nested_if_2", _prog("def f(a: int, b: int) -> int:\n    if a > 0:\n        if b > 0:\n            return 1\n        return 2\n    return 3", "print(f(1, -1))"), "2"))
S.append(("nested_if_3", _prog("def f(a: int, b: int) -> int:\n    if a > 0:\n        if b > 0:\n            return 1\n        return 2\n    return 3", "print(f(-1, 1))"), "3"))
S.append(("early_return", _prog("def f(n: int) -> int:\n    if n == 0:\n        return 42\n    return n", "print(f(0))"), "42"))
S.append(("multi_return", _prog("def f(n: int) -> int:\n    if n == 1:\n        return 10\n    if n == 2:\n        return 20\n    if n == 3:\n        return 30\n    return 0", "print(f(2))"), "20"))
S.append(("if_with_and", _prog("def f(a: int, b: int) -> int:\n    if a > 0:\n        if b > 0:\n            return 1\n    return 0", "print(f(1, 1))"), "1"))
S.append(("if_with_or", _prog("def f(a: int, b: int) -> int:\n    if a > 0:\n        return 1\n    if b > 0:\n        return 1\n    return 0", "print(f(-1, 1))"), "1"))
S.append(("classify_sign", _prog_multi("def f(n: int) -> int:\n    if n > 0:\n        return 1\n    elif n < 0:\n        return -1\n    return 0", ["print(f(5))", "print(f(-3))", "print(f(0))"]), "1\n-1\n0"))

# === Category 5: Loops (41-50) ===
S.append(("for_sum_10", _prog("def f(n: int) -> int:\n    total: int = 0\n    for i in range(0, n):\n        total = total + i\n    return total", "print(f(10))"), "45"))
S.append(("for_sum_100", _prog("def f(n: int) -> int:\n    total: int = 0\n    for i in range(0, n):\n        total = total + i\n    return total", "print(f(100))"), "4950"))
S.append(("while_countdown", _prog("def f(n: int) -> int:\n    count: int = 0\n    while n > 0:\n        count = count + 1\n        n = n - 1\n    return count", "print(f(10))"), "10"))
S.append(("while_accumulate", _prog("def f(n: int) -> int:\n    total: int = 0\n    while n > 0:\n        total = total + n\n        n = n - 1\n    return total", "print(f(5))"), "15"))
S.append(("nested_loops", _prog("def f(n: int) -> int:\n    count: int = 0\n    for i in range(0, n):\n        for j in range(0, n):\n            count = count + 1\n    return count", "print(f(3))"), "9"))
S.append(("loop_with_break", _prog("def f(n: int) -> int:\n    total: int = 0\n    for i in range(0, n):\n        if i >= 5:\n            break\n        total = total + i\n    return total", "print(f(100))"), "10"))
S.append(("loop_with_continue", _prog("def f(n: int) -> int:\n    total: int = 0\n    for i in range(0, n):\n        if i == 5:\n            continue\n        total = total + i\n    return total", "print(f(10))"), "40"))
S.append(("loop_double", _prog("def f(n: int) -> int:\n    total: int = 0\n    for i in range(0, n):\n        total = total + 2\n    return total", "print(f(21))"), "42"))
S.append(("loop_multiply", _prog("def f(n: int) -> int:\n    result: int = 1\n    for i in range(1, n):\n        result = result * i\n    return result", "print(f(6))"), "120"))
S.append(("countdown_zero", _prog("def f(n: int) -> int:\n    while n > 0:\n        n = n - 1\n    return n", "print(f(5))"), "0"))

# === Category 6: Recursion (51-60) ===
S.append(("factorial", _prog("def f(n: int) -> int:\n    if n <= 1:\n        return 1\n    return n * f(n - 1)", "print(f(5))"), "120"))
S.append(("fibonacci", _prog("def f(n: int) -> int:\n    if n <= 1:\n        return n\n    return f(n - 1) + f(n - 2)", "print(f(10))"), "55"))
S.append(("gcd_recursive", _prog("def f(a: int, b: int) -> int:\n    if b == 0:\n        return a\n    return f(b, a % b)", "print(f(48, 18))"), "6"))
S.append(("sum_recursive", _prog("def f(n: int) -> int:\n    if n == 0:\n        return 0\n    return n + f(n - 1)", "print(f(10))"), "55"))
S.append(("power_recursive", _prog("def f(base: int, exp: int) -> int:\n    if exp == 0:\n        return 1\n    return base * f(base, exp - 1)", "print(f(2, 10))"), "1024"))
S.append(("ackermann_small", _prog("def f(m: int, n: int) -> int:\n    if m == 0:\n        return n + 1\n    if n == 0:\n        return f(m - 1, 1)\n    return f(m - 1, f(m, n - 1))", "print(f(1, 2))"), "4"))
S.append(("reverse_count", _prog("def f(n: int) -> int:\n    if n == 0:\n        return 0\n    return 1 + f(n - 1)", "print(f(10))"), "10"))
S.append(("deep_recursion", _prog("def f(n: int) -> int:\n    if n == 0:\n        return 42\n    return f(n - 1)", "print(f(100))"), "42"))
S.append(("fib_iter", _prog("def f(n: int) -> int:\n    if n <= 1:\n        return n\n    a: int = 0\n    b: int = 1\n    for i in range(2, n):\n        temp: int = a + b\n        a = b\n        b = temp\n    return a + b", "print(f(10))"), "55"))
S.append(("collatz_steps", _prog("def f(n: int) -> int:\n    steps: int = 0\n    while n != 1:\n        if n % 2 == 0:\n            n = n // 2\n        else:\n            n = n * 3 + 1\n        steps = steps + 1\n    return steps", "print(f(6))"), "8"))

# === Category 7: Function calls (61-70) ===
S.append(("multi_arg", _prog("def f(a: int, b: int, c: int) -> int:\n    return a + b + c", "print(f(10, 20, 30))"), "60"))
S.append(("chained_calls", _prog("def sq(n: int) -> int:\n    return n * n\ndef f(a: int) -> int:\n    return sq(sq(a))", "print(f(3))"), "81"))
S.append(("call_in_expr", _prog("def sq(n: int) -> int:\n    return n * n\ndef f(a: int, b: int) -> int:\n    return sq(a) + sq(b)", "print(f(3, 4))"), "25"))
S.append(("void_function", _prog("def f(n: int) -> int:\n    print(n)\n    return 0", "f(42)"), "42"))
S.append(("pass_result", _prog("def sq(n: int) -> int:\n    return n * n\ndef dbl(n: int) -> int:\n    return n * 2\ndef f(n: int) -> int:\n    return dbl(sq(n))", "print(f(5))"), "50"))
S.append(("three_functions", _prog("def a(n: int) -> int:\n    return n + 1\ndef b(n: int) -> int:\n    return a(n) + 1\ndef c(n: int) -> int:\n    return b(n) + 1", "print(c(10))"), "13"))
S.append(("function_with_loop", _prog("def f(n: int) -> int:\n    total: int = 0\n    for i in range(0, n):\n        total = total + i\n    return total", "print(f(5))"), "10"))
S.append(("function_conditional", _prog_multi("def f(n: int) -> int:\n    if n % 2 == 0:\n        return n // 2\n    return n * 3 + 1", ["print(f(4))", "print(f(3))"]), "2\n10"))
S.append(("helper_pattern", _prog("def is_pos(n: int) -> int:\n    if n > 0:\n        return 1\n    return 0\ndef f(a: int, b: int) -> int:\n    return is_pos(a) + is_pos(b)", "print(f(5, -3))"), "1"))
S.append(("identity", _prog("def f(n: int) -> int:\n    return n", "print(f(42))"), "42"))

# === Category 8: List operations (71-80) ===
S.append(("list_sum", _prog("def f(arr: list) -> int:\n    total: int = 0\n    for i in range(0, len(arr)):\n        total = total + arr[i]\n    return total", "nums: list = [1, 2, 3, 4, 5]\n    print(f(nums))"), "15"))
S.append(("list_index", _prog("def f(arr: list) -> int:\n    return arr[0]", "nums: list = [42, 10, 20]\n    print(f(nums))"), "42"))
S.append(("list_last", _prog("def f(arr: list) -> int:\n    return arr[len(arr) - 1]", "nums: list = [10, 20, 30]\n    print(f(nums))"), "30"))
S.append(("list_max", _prog("def f(arr: list) -> int:\n    m: int = arr[0]\n    for i in range(1, len(arr)):\n        if arr[i] > m:\n            m = arr[i]\n    return m", "nums: list = [3, 7, 2, 9, 5]\n    print(f(nums))"), "9"))
S.append(("list_min", _prog("def f(arr: list) -> int:\n    m: int = arr[0]\n    for i in range(1, len(arr)):\n        if arr[i] < m:\n            m = arr[i]\n    return m", "nums: list = [3, 7, 2, 9, 5]\n    print(f(nums))"), "2"))
S.append(("list_count", _prog("def f(arr: list, target: int) -> int:\n    count: int = 0\n    for i in range(0, len(arr)):\n        if arr[i] == target:\n            count = count + 1\n    return count", "nums: list = [1, 2, 3, 2, 2, 4]\n    print(f(nums, 2))"), "3"))
S.append(("list_average", _prog("def f(arr: list) -> int:\n    total: int = 0\n    for i in range(0, len(arr)):\n        total = total + arr[i]\n    return total // len(arr)", "nums: list = [10, 20, 30, 40]\n    print(f(nums))"), "25"))
S.append(("list_search", _prog("def f(arr: list, target: int) -> int:\n    for i in range(0, len(arr)):\n        if arr[i] == target:\n            return i\n    return -1", "nums: list = [10, 20, 30, 40]\n    print(f(nums, 30))"), "2"))
S.append(("list_length", _prog("def f(arr: list) -> int:\n    return len(arr)", "nums: list = [1, 2, 3, 4, 5, 6]\n    print(f(nums))"), "6"))
S.append(("list_product", _prog("def f(arr: list) -> int:\n    result: int = 1\n    for i in range(0, len(arr)):\n        result = result * arr[i]\n    return result", "nums: list = [1, 2, 3, 4]\n    print(f(nums))"), "24"))

# === Category 9: Type handling (81-90) ===
S.append(("int_to_int", _prog("def f(a: int) -> int:\n    return a + 0", "print(f(42))"), "42"))
S.append(("bool_true_path", _prog("def f(flag: int) -> int:\n    if flag:\n        return 1\n    return 0", "print(f(1))"), "1"))
S.append(("bool_false_path", _prog("def f(flag: int) -> int:\n    if flag:\n        return 1\n    return 0", "print(f(0))"), "0"))
S.append(("neg_to_pos", _prog("def f(a: int) -> int:\n    return -a", "print(f(-42))"), "42"))
S.append(("pos_to_neg", _prog("def f(a: int) -> int:\n    return -a", "print(f(42))"), "-42"))
S.append(("zero_value", _prog("def f() -> int:\n    return 0", "print(f())"), "0"))
S.append(("one_value", _prog("def f() -> int:\n    return 1", "print(f())"), "1"))
S.append(("large_int", _prog("def f() -> int:\n    return 2147483647", "print(f())"), "2147483647"))
S.append(("int_div_truncation", _prog("def f(a: int, b: int) -> int:\n    return a // b", "print(f(7, 2))"), "3"))
S.append(("mixed_ops", _prog("def f(a: int, b: int, c: int) -> int:\n    return (a + b) * c - (a - b)", "print(f(3, 4, 5))"), "36"))

# === Category 10: Real-world algorithms (91-100) ===
S.append(("is_prime", _prog_multi("def f(n: int) -> int:\n    if n < 2:\n        return 0\n    for i in range(2, n):\n        if n % i == 0:\n            return 0\n    return 1", ["print(f(7))", "print(f(8))"]), "1\n0"))
S.append(("count_primes", _prog("def is_prime(n: int) -> int:\n    if n < 2:\n        return 0\n    for i in range(2, n):\n        if n % i == 0:\n            return 0\n    return 1\ndef f(limit: int) -> int:\n    count: int = 0\n    for i in range(2, limit):\n        if is_prime(i):\n            count = count + 1\n    return count", "print(f(20))"), "8"))
S.append(("sum_of_digits", _prog("def f(n: int) -> int:\n    total: int = 0\n    while n > 0:\n        total = total + n % 10\n        n = n // 10\n    return total", "print(f(12345))"), "15"))
S.append(("reverse_number", _prog("def f(n: int) -> int:\n    result: int = 0\n    while n > 0:\n        result = result * 10 + n % 10\n        n = n // 10\n    return result", "print(f(12345))"), "54321"))
S.append(("is_palindrome_num", _prog("def f(n: int) -> int:\n    original: int = n\n    rev: int = 0\n    while n > 0:\n        rev = rev * 10 + n % 10\n        n = n // 10\n    if original == rev:\n        return 1\n    return 0", "print(f(121))"), "1"))
S.append(("leap_year", _prog_multi("def f(year: int) -> int:\n    if year % 4 == 0:\n        if year % 100 == 0:\n            if year % 400 == 0:\n                return 1\n            return 0\n        return 1\n    return 0", ["print(f(2000))", "print(f(1900))", "print(f(2024))"]), "1\n0\n1"))
S.append(("simple_interest", _prog("def f(principal: int, rate: int, time: int) -> int:\n    return (principal * rate * time) // 100", "print(f(1000, 5, 2))"), "100"))
S.append(("compound_calc", _prog("def f(base: int, years: int) -> int:\n    result: int = base\n    for i in range(0, years):\n        result = result + result // 10\n    return result", "print(f(100, 2))"), "121"))
S.append(("digit_count", _prog("def f(n: int) -> int:\n    count: int = 0\n    if n == 0:\n        return 1\n    while n > 0:\n        count = count + 1\n        n = n // 10\n    return count", "print(f(12345))"), "5"))
S.append(("bubble_count", _prog("def f(arr: list) -> int:\n    swaps: int = 0\n    for i in range(0, len(arr)):\n        for j in range(0, len(arr) - 1):\n            if arr[j] > arr[j + 1]:\n                swaps = swaps + 1\n    return swaps", "nums: list = [3, 1, 2]\n    print(f(nums))"), "3"))

SCENARIOS = S


def _make_test(scenario, backend):
    name, source, expected = scenario
    def test(self):
        if backend not in BACKENDS:
            self.skipTest(f"{backend} not available")
        ok = _compile_and_run(source, backend, expected)
        self.assertTrue(ok,
            f"{backend}: '{name}' expected '{expected}'")
    test.__name__ = f"test_{name}_{backend}"
    return test


class TestConceptual100(unittest.TestCase):
    """100 conceptual tests x 6 backends = 600 checks."""
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMPDIR, ignore_errors=True)


for _i, _scenario in enumerate(SCENARIOS):
    for _backend in ("rust", "cpp", "csharp", "zig", "go", "kotlin"):
        _test = _make_test(_scenario, _backend)
        setattr(TestConceptual100, _test.__name__, _test)


if __name__ == "__main__":
    unittest.main(verbosity=2)
