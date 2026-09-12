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

# .ge.py modules are importable now.
from app.core.add import add  # noqa: E402
from app.core.multiply import multiply  # noqa: E402
from app.core.factorial import factorial  # noqa: E402
from app.core.fibonacci import fibonacci  # noqa: E402
from app.core.is_prime import is_prime  # noqa: E402
from app.core.gcd import gcd  # noqa: E402
from app.core.power import power  # noqa: E402
from app.memory.limits import (  # noqa: E402
    mem_input_min, mem_input_max, mem_clamp_input, mem_step_up, mem_step_down,
)
from app.memory.buffer import (  # noqa: E402
    mem_buffer_capacity, mem_digits_capacity, mem_state_slots,
)
from app.memory.state import (  # noqa: E402
    mem_initial_input, mem_initial_result, mem_initial_op,
    mem_op_count, mem_next_op, mem_normalize_input,
)
from app.ui.theme import ui_color_bg, ui_color_accent, ui_font_body, ui_radius  # noqa: E402
from app.ui.layout import (  # noqa: E402
    ui_card_width, ui_card_height, ui_sidebar_width, ui_content_x,
    ui_center_x, ui_row_y,
)


class TestCoreFunctions(unittest.TestCase):
    """C++ core layer - computation."""

    def test_add(self):
        self.assertEqual(add(3, 4), 7)
        self.assertEqual(add(-1, 1), 0)

    def test_multiply(self):
        self.assertEqual(multiply(3, 4), 12)
        self.assertEqual(multiply(0, 5), 0)

    def test_factorial(self):
        self.assertEqual(factorial(0), 1)
        self.assertEqual(factorial(5), 120)
        self.assertEqual(factorial(10), 3628800)

    def test_fibonacci(self):
        self.assertEqual(fibonacci(0), 0)
        self.assertEqual(fibonacci(1), 1)
        self.assertEqual(fibonacci(10), 55)

    def test_is_prime(self):
        self.assertEqual(is_prime(2), 1)
        self.assertEqual(is_prime(3), 1)
        self.assertEqual(is_prime(4), 0)
        self.assertEqual(is_prime(17), 1)
        self.assertEqual(is_prime(100), 0)

    def test_gcd(self):
        self.assertEqual(gcd(12, 8), 4)
        self.assertEqual(gcd(17, 5), 1)
        self.assertEqual(gcd(100, 50), 50)

    def test_power(self):
        self.assertEqual(power(2, 0), 1)
        self.assertEqual(power(2, 10), 1024)
        self.assertEqual(power(3, 3), 27)


class TestMemoryLayer(unittest.TestCase):
    """Rust memory layer - bounds and state."""

    def test_clamp_input(self):
        self.assertEqual(mem_clamp_input(-5), mem_input_min())
        self.assertEqual(mem_clamp_input(999), mem_input_max())
        self.assertEqual(mem_clamp_input(7), 7)

    def test_step_up_down(self):
        self.assertEqual(mem_step_up(1), 2)
        self.assertEqual(mem_step_down(1), 0)
        self.assertEqual(mem_step_up(mem_input_max()),
                         mem_input_max())
        self.assertEqual(mem_step_down(mem_input_min()),
                         mem_input_min())

    def test_factorial_fits_in_i64(self):
        # mem_input_max() must keep factorial within i64 range
        self.assertLess(factorial(mem_input_max()),
                        2 ** 63)

    def test_state_defaults(self):
        self.assertEqual(mem_initial_result(), 0)
        self.assertEqual(mem_initial_op(), 0)
        self.assertIsInstance(mem_initial_input(), int)

    def test_op_cycle(self):
        self.assertEqual(mem_next_op(mem_op_count() - 1), 0)
        self.assertEqual(mem_next_op(0), 1)

    def test_normalize(self):
        self.assertEqual(mem_normalize_input(999), mem_input_max())

    def test_buffers_bounded(self):
        self.assertGreater(mem_buffer_capacity(),
                           mem_digits_capacity())
        self.assertGreater(mem_state_slots(), 0)


class TestUILayer(unittest.TestCase):
    """C++ UI layer - design tokens and layout math."""

    def test_theme_tokens(self):
        self.assertIsInstance(ui_color_bg(), int)
        self.assertIsInstance(ui_color_accent(), int)
        self.assertGreater(ui_font_body(), 0)
        self.assertGreater(ui_radius(), 0)

    def test_layout_math(self):
        self.assertGreater(ui_card_width(1200), 0)
        self.assertGreater(ui_content_x(), ui_sidebar_width())
        self.assertGreater(ui_card_height(800), 0)

    def test_centering(self):
        self.assertEqual(ui_center_x(0, 100, 20), 40)

    def test_rows_increase(self):
        self.assertGreater(ui_row_y(2), ui_row_y(1))


class TestProjectStructure(unittest.TestCase):
    """Layered architecture is present on disk."""

    def test_layers_exist(self):
        for layer in ["memory", "core", "ui"]:
            self.assertTrue((ROOT / "app" / layer).is_dir(),
                            "app/" + layer + "/ should exist")

    def test_one_function_per_core_file(self):
        core = ROOT / "app" / "core"
        for f in ["add.ge.py", "multiply.ge.py", "factorial.ge.py",
                  "fibonacci.ge.py", "is_prime.ge.py", "gcd.ge.py", "power.ge.py"]:
            self.assertTrue((core / f).exists(), "app/core/" + f + " should exist")

    def test_ui_files(self):
        ui = ROOT / "app" / "ui"
        for f in ["theme.ge.py", "layout.ge.py", "widgets.ge.py", "render.ge.py"]:
            self.assertTrue((ui / f).exists(), "app/ui/" + f + " should exist")

    def test_memory_files(self):
        mem = ROOT / "app" / "memory"
        for f in ["limits.ge.py", "buffer.ge.py", "state.ge.py"]:
            self.assertTrue((mem / f).exists(), "app/memory/" + f + " should exist")

    def test_entry_and_config(self):
        # the build is `ge build desktop/main.ge.py` — no project build script
        self.assertTrue((ROOT / "desktop" / "main.ge.py").exists())
        self.assertTrue((ROOT / "ge.toml").exists())


if __name__ == "__main__":
    unittest.main()
