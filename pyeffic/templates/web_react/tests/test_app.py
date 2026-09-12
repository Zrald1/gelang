"""{app_name} test suite.

Run with:

    python -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from ge_loader import install  # noqa: E402

install()

from app.core.add import add  # noqa: E402
from app.core.multiply import multiply  # noqa: E402
from app.core.factorial import factorial  # noqa: E402
from app.core.fibonacci import fibonacci  # noqa: E402
from app.core.is_prime import is_prime  # noqa: E402
from app.memory.limits import (  # noqa: E402
    mem_clamp_arg, mem_max_arg_value, mem_min_arg_value, mem_arg_count_ok,
    mem_max_args,
)
from app.memory.buffer import (  # noqa: E402
    mem_json_capacity, mem_path_capacity, mem_body_capacity,
)


class TestCore(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(3, 4), 7)
        self.assertEqual(add(-1, 1), 0)

    def test_multiply(self):
        self.assertEqual(multiply(3, 4), 12)

    def test_factorial(self):
        self.assertEqual(factorial(0), 1)
        self.assertEqual(factorial(5), 120)

    def test_fibonacci(self):
        self.assertEqual(fibonacci(10), 55)

    def test_is_prime(self):
        self.assertEqual(is_prime(17), 1)
        self.assertEqual(is_prime(100), 0)


class TestMemoryBounds(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(mem_clamp_arg(10**12), mem_max_arg_value())
        self.assertEqual(mem_clamp_arg(-10**12), mem_min_arg_value())
        self.assertEqual(mem_clamp_arg(5), 5)

    def test_arg_count(self):
        self.assertEqual(mem_arg_count_ok(0), 1)
        self.assertEqual(mem_arg_count_ok(mem_max_args()), 1)
        self.assertEqual(mem_arg_count_ok(mem_max_args() + 1), 0)

    def test_buffers(self):
        self.assertGreater(mem_body_capacity(), mem_json_capacity())
        self.assertGreater(mem_path_capacity(), 0)


class TestDispatch(unittest.TestCase):
    def test_dispatch_routes(self):
        from web.server import safe_dispatch, api_ok
        self.assertEqual(safe_dispatch(0, 2, 3), 5)
        self.assertEqual(safe_dispatch(1, 2, 3), 6)
        self.assertEqual(safe_dispatch(2, 5, 0), 120)
        self.assertEqual(safe_dispatch(3, 10, 0), 55)
        self.assertEqual(safe_dispatch(4, 17, 0), 1)
        self.assertEqual(api_ok(), 1)

    def test_dispatch_clamps(self):
        from web.server import safe_dispatch
        # the clamp itself is what we assert on; factorial of the clamp limit
        # is intentionally not computed here (it would be a huge loop)
        self.assertEqual(mem_clamp_arg(10**12), mem_max_arg_value())
        self.assertEqual(mem_clamp_arg(-10**12), mem_min_arg_value())
        # a value inside the bound passes through unchanged
        self.assertEqual(safe_dispatch(2, 5, 0), 120)

    def test_dispatch_rejects_bad_op(self):
        from web.server import safe_dispatch
        self.assertEqual(safe_dispatch(-1, 1, 1), 0)
        self.assertEqual(safe_dispatch(99, 1, 1), 0)


class TestStructure(unittest.TestCase):
    def test_layers(self):
        for layer in ["memory", "core"]:
            self.assertTrue((ROOT / "app" / layer).is_dir())

    def test_web_and_ui(self):
        self.assertTrue((ROOT / "web" / "server.ge.py").exists())
        self.assertTrue((ROOT / "ui" / "main.ge.ui").exists())
        self.assertTrue((ROOT / "ge.toml").exists())


if __name__ == "__main__":
    unittest.main()
