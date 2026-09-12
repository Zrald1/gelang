"""GE project scaffolding — `ge create` command.

Generates a properly structured GE project with:
  app/       — main application entry (shared logic)
  desktop/   — desktop platform wrapper (Windows/Linux/macOS)
  web/       — web platform wrapper
  mobile/    — mobile platform wrapper (Android/iOS)
  backend/   — native backend source (Rust/C++/C#/Zig/Go/Kotlin)
  ui/        — .ge.ui declarative UI definitions
  tests/     — test scripts

The user is prompted for:
  1. App name
  2. Platforms (desktop/web/mobile/all) — default: all
  3. Backend language (all/rust/cpp/csharp/zig/go/kotlin) — default: all
  4. UI backend (all/dart) — default: all (dart only for now)

Non-interactive mode is supported via CLI flags.
"""
from __future__ import annotations

import re
from pathlib import Path

ALL_BACKENDS = ["rust", "cpp", "csharp", "zig", "go", "kotlin"]
ALL_PLATFORMS = ["desktop", "web", "mobile"]
#: Template name -> directory under pyeffic/templates/
TEMPLATE_DIRS = {
    "desktop-gui": "desktop_gui",
    "web-react": "web_react",
}
ALL_TEMPLATES = ["default"] + list(TEMPLATE_DIRS)


def _sanitize_name(name: str) -> str:
    """Convert app name to a valid package name (lowercase, underscores)."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())
    if s and s[0].isdigit():
        s = "_" + s
    return s.lower() or "ge_app"


def _prompt(message: str, default: str, choices: list[str] | None = None) -> str:
    """Interactive prompt with default and optional choices."""
    hint = f" [{default}]" if default else ""
    choice_hint = ""
    if choices:
        choice_hint = f" ({'/'.join(choices)})"
    while True:
        val = input(f"{message}{choice_hint}{hint}: ").strip()
        if not val:
            return default
        if choices and val not in choices:
            print(f"  Invalid choice. Options: {', '.join(choices)}")
            continue
        return val


def _prompt_multi(message: str, default: str, choices: list[str]) -> list[str]:
    """Prompt for comma-separated multi-select. 'all' selects everything."""
    while True:
        val = input(f"{message} (choices: {', '.join(choices)}, or 'all') [{default}]: ").strip()
        if not val:
            val = default
        if val == "all":
            return choices[:]
        parts = [p.strip() for p in val.split(",") if p.strip()]
        invalid = [p for p in parts if p not in choices]
        if invalid:
            print(f"  Invalid: {', '.join(invalid)}. Options: {', '.join(choices)}")
            continue
        return parts


# Template files

_APP_MAIN_TEMPLATE = '''"""GE application — {app_name}

This is the main application logic. Platform-specific code (desktop/web/mobile)
imports from here. Write your core GE functions in this file.
"""
from __future__ import annotations


def greet(name: str) -> str:
    return f"Hello, {{name}}! Welcome to {app_name}."


def main() -> None:
    print(greet("World"))
'''

_DESKTOP_MAIN_TEMPLATE = '''"""Desktop entry point for {app_name}.

Builds the desktop application using the shared app logic.
Run with: ge build desktop/main.ge.py --run
"""
from __future__ import annotations
from app.main import greet, main


def desktop_main() -> None:
    print("=== {app_name} Desktop ===")
    main()
'''

_WEB_MAIN_TEMPLATE = '''"""Web entry point for {app_name}.

Builds the web application using the shared app logic.
Run with: ge build web/main.ge.py
"""
from __future__ import annotations
from app.main import greet, main


def web_main() -> None:
    print("=== {app_name} Web ===")
    main()
'''

_MOBILE_MAIN_TEMPLATE = '''"""Mobile entry point for {app_name}.

Builds the mobile (Android/iOS) application using the shared app logic.
Run with: ge flutter mobile/main.ge.py --app-name {app_name}
"""
from __future__ import annotations
from app.main import greet, main


def mobile_main() -> None:
    print("=== {app_name} Mobile ===")
    main()
'''

_UI_TEMPLATE = '''"""GE UI definition for {app_name}.

Define your UI declaratively using the .ge.ui DSL.
This file is parsed by the GE UI parser and generates Flutter widgets.
"""
Window {{
  title: "{app_name}"
  Column {{
    Text {{ text: "Welcome to {app_name}", style: "headline" }}
    Text {{ text: "Built with GE", style: "body" }}
  }}
}}
'''

_BACKEND_TEMPLATE = '''"""GE backend functions for {app_name}.

These functions are compiled to native code via the selected backend(s).
Use @rust, @cpp, @csharp, @zig, @go, or @kotlin decorators to force a backend.
Without a decorator, GE auto-selects the best backend.
"""
from __future__ import annotations
from pyeffic.backends import rust, cpp, csharp, zig, go, kotlin


def compute_sum(a: int, b: int) -> int:
    return a + b


def compute_product(a: int, b: int) -> int:
    return a * b
'''

_TEST_TEMPLATE = '''"""Tests for {app_name}.

Run with: python -m unittest discover tests
"""
import unittest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAppFunctions(unittest.TestCase):
    def test_greet(self):
        from app.main import greet
        self.assertEqual(greet("World"), "Hello, World! Welcome to {app_name}.")

    def test_compute_sum(self):
        from backend.main import compute_sum
        self.assertEqual(compute_sum(3, 4), 7)

    def test_compute_product(self):
        from backend.main import compute_product
        self.assertEqual(compute_product(3, 4), 12)


if __name__ == "__main__":
    unittest.main()
'''

_GE_CONFIG_TEMPLATE = '''# GE project configuration for {app_name}
[project]
name = "{app_name}"
version = "0.1.0"
description = "A GE application"

[build]
# Default backend for all functions (auto selects best per function)
backend = "auto"
# Platforms to build for
platforms = [{platforms}]

[backends]
# Which backends to generate code for (default: all)
languages = [{backends}]

[ui]
# UI backend (dart for Flutter)
backend = "dart"
'''

_README_TEMPLATE = '''# {app_name}

A GE application built with the [GE programming language](https://github.com/user/ge).

## Structure

```
{app_name}/
  app/        — main application logic (shared)
  desktop/    — desktop platform entry
  web/        — web platform entry
  mobile/     — mobile platform entry
  backend/    — native backend functions
  ui/         — .ge.ui declarative UI definitions
  tests/      — test scripts
  ge.toml     — GE project config
```

## Build

```bash
# Build for desktop
ge build desktop/main.ge.py --run

# Build for web
ge build web/main.ge.py

# Build Flutter app (mobile/desktop)
ge flutter mobile/main.ge.py --app-name {app_name}

# Build all backends
ge build app/main.ge.py --backend auto
```

## Test

```bash
python -m unittest discover tests
```
'''


def create_project(
    name: str,
    out_dir: Path | str = ".",
    platforms: list[str] | None = None,
    backends: list[str] | None = None,
    interactive: bool = True,
    template: str = "default",
) -> Path:
    """Create a new GE project with proper structure.

    Args:
        name: app name
        out_dir: output directory
        platforms: list of platforms (desktop/web/mobile), or None for all
        backends: list of backend languages, or None for all
        interactive: if True, prompt for missing values
        template: "default" or "desktop-gui"

    Returns:
        Path to the created project directory.
    """
    if interactive:
        name = _prompt("App name", _sanitize_name(name))
        if template == "default":
            template = _prompt("Template", "default", ALL_TEMPLATES)
        if platforms is None:
            platforms = _prompt_multi("Platforms", "all", ALL_PLATFORMS)
        if backends is None:
            backends = _prompt_multi("Backend languages", "all", ALL_BACKENDS)
    else:
        name = _sanitize_name(name)
        if platforms is None:
            platforms = ALL_PLATFORMS[:]
        if backends is None:
            backends = ALL_BACKENDS[:]

    if template in TEMPLATE_DIRS:
        return _create_template_project(template, name, out_dir)

    out = Path(out_dir) / name
    if out.exists():
        raise FileExistsError(f"Directory already exists: {out}")

    # Create directory structure
    dirs = ["app", "backend", "ui", "tests"]
    for p in platforms:
        dirs.append(p)
    for d in dirs:
        (out / d).mkdir(parents=True, exist_ok=True)

    # Write files
    (out / "app" / "main.ge.py").write_text(
        _APP_MAIN_TEMPLATE.format(app_name=name), encoding="utf-8")
    (out / "app" / "__init__.py").write_text("", encoding="utf-8")

    if "desktop" in platforms:
        (out / "desktop" / "main.ge.py").write_text(
            _DESKTOP_MAIN_TEMPLATE.format(app_name=name), encoding="utf-8")
    if "web" in platforms:
        (out / "web" / "main.ge.py").write_text(
            _WEB_MAIN_TEMPLATE.format(app_name=name), encoding="utf-8")
    if "mobile" in platforms:
        (out / "mobile" / "main.ge.py").write_text(
            _MOBILE_MAIN_TEMPLATE.format(app_name=name), encoding="utf-8")

    (out / "backend" / "main.ge.py").write_text(
        _BACKEND_TEMPLATE.format(app_name=name), encoding="utf-8")
    (out / "backend" / "__init__.py").write_text("", encoding="utf-8")

    (out / "ui" / "main.ge.ui").write_text(
        _UI_TEMPLATE.format(app_name=name), encoding="utf-8")

    (out / "tests" / "test_app.py").write_text(
        _TEST_TEMPLATE.format(app_name=name), encoding="utf-8")
    (out / "tests" / "__init__.py").write_text("", encoding="utf-8")

    platforms_str = ", ".join(f'"{p}"' for p in platforms)
    backends_str = ", ".join(f'"{b}"' for b in backends)
    (out / "ge.toml").write_text(
        _GE_CONFIG_TEMPLATE.format(app_name=name, platforms=platforms_str, backends=backends_str),
        encoding="utf-8")

    (out / "README.md").write_text(
        _README_TEMPLATE.format(app_name=name), encoding="utf-8")

    return out


def create_project_noninteractive(
    name: str,
    out_dir: Path | str = ".",
    platforms: list[str] | None = None,
    backends: list[str] | None = None,
    template: str = "default",
) -> Path:
    """Create a project without any prompts."""
    return create_project(name, out_dir, platforms, backends, interactive=False,
                          template=template)


def _create_template_project(template: str, name: str,
                             out_dir: Path | str = ".") -> Path:
    """Create a project from a directory under pyeffic/templates/.

    Each template is a real file tree (not inline strings) so it stays
    readable, diffable, and independently editable. Every occurrence of
    `{app_name}` in a template file is replaced with the project name.

    Registered templates:
      desktop-gui  Rust shell + C++ core + C++ UI (native Win32)
      web-react    React 19 + TypeScript SPA + Rust backend
    """
    dirname = TEMPLATE_DIRS.get(template)
    if dirname is None:
        raise ValueError(f"unknown template: {template}")
    template_root = Path(__file__).parent / "templates" / dirname
    if not template_root.is_dir():
        raise FileNotFoundError(f"template directory missing: {template_root}")

    out = Path(out_dir) / name
    if out.exists():
        raise FileExistsError(f"Directory already exists: {out}")

    for src in sorted(template_root.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(template_root)
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text(encoding="utf-8")
        dst.write_text(content.replace("{app_name}", name), encoding="utf-8")

    return out


def _create_desktop_gui_project(name: str, out_dir: Path | str = ".") -> Path:
    """Backwards-compatible alias for the desktop-gui template."""
    return _create_template_project("desktop-gui", name, out_dir)
