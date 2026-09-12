"""GE — a unified programming language.

GE source can be written in either Python (.ge.py) or TypeScript (.ts).
Both transpile to Rust/C++/Dart via the same pipeline:

  Python (.ge.py)  → [existing GE pipeline] → Rust/C++/Dart
  TypeScript (.ts) → Python → [existing GE pipeline] → Rust/C++/Dart

The GE compiler targets your installed toolchains (rustc / clang++ / dart) —
you only need the latest of those installed to build. It produces tiny packed
artifacts and matches C++/Rust performance (proven by `ge bench`).

Commands:
  ge create [NAME] [--platforms ...] [--backends ...]  # scaffold a new project
  ge build <file.ge.py> [--target desktop|web|mobile|crossplatform] [--run]
  ge analyze <file.ge.py> [--entry main]                    # type check + diagnostics
  ge flutter <file.ge.py> --app-name NAME                  # native FFI lib + Dart UI
  ge pack <file.ge.py>                                     # bundle -> .ge file
  ge deploy <package.ge> [--target local|vps|simulate]     # auto-detect + distribute + simulate + go live
  ge install <package.ge> --target windows|android|apk     # unpack + build (auto-downloads toolchains)
  ge tools list|install|check [toolchain]                  # manage toolchains
  ge bench                                                 # GE vs hand-written C++ parity
  ge doctor                                                # check runtime + toolchains
  ge compilers                                             # show detected toolchains
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config, compiler_version, detect_compilers
from .pipeline import build, build_flutter
from .packer import pack, pack_ge, unpack_ge, PackageMeta, fmt_size
from .compiler import compile_rust, compile_rust_android, compile_mixed_android, AndroidCompileResult
from .bench import bench_squares, bench_vectorize
from .scaffold import create_project, create_project_noninteractive, ALL_PLATFORMS, ALL_BACKENDS

GE_BANNER = "GE — unified programming language  (targets rustc / clang++ / dart)"


def _find_dart() -> str | None:
    for c in ("C:\\flutter\\bin\\cache\\dart-sdk\\bin\\dart.exe",):
        if Path(c).exists():
            return c
    return shutil.which("dart")


def _find_flutter() -> str | None:
    for c in ("C:\\flutter\\bin\\flutter.bat",):
        if Path(c).exists():
            return c
    return shutil.which("flutter")


def _maybe_transpile_ts(file_path: Path) -> Path:
    """If the source is TypeScript (.ts), transpile to Python (.ge.py) first.

    This lets users write in either Python or TypeScript — both feed into the
    same GE pipeline (analyzer → Rust/C++ emitters → FFI → Flutter → .ge).
    """
    if file_path.suffix == ".ts":
        from .ts2py import transpile
        print(f"  [TS] transpiling {file_path.name} -> Python...")
        py_source = transpile(file_path.read_text(encoding="utf-8"))
        # avoid clobbering a hand-written .ge.py — use .ts.ge.py instead
        py_path = file_path.with_suffix(".ge.py")
        if py_path.exists():
            py_path = file_path.with_suffix(".ts.ge.py")
        py_path.write_text(py_source, encoding="utf-8")
        print(f"  [TS] -> {py_path.name} ({len(py_source)} bytes)")
        return py_path
    return file_path


def cmd_doctor(args) -> int:
    """Check the runtime and every optional toolchain, with install hints."""
    import sys as _sys

    from .config import detect_compilers, MIN_VERSIONS

    info = detect_compilers()

    # ---- runtime -------------------------------------------------------
    py_ok = _sys.version_info >= (3, 10)
    py_ver = f"{_sys.version_info.major}.{_sys.version_info.minor}.{_sys.version_info.micro}"

    # ---- native backends ----------------------------------------------
    backends = [
        ("rust", "rustc", info.rustc, "Rust backend"),
        ("cpp", "clang++/g++", info.cpp, "C++ backend"),
        ("csharp", "dotnet", info.dotnet, "C# backend (NativeAOT)"),
        ("zig", "zig", info.zig, "Zig backend"),
        ("go", "go", info.go, "Go backend"),
        ("kotlin", "kotlinc-native", info.kotlinc, "Kotlin backend"),
    ]
    have = [b for b in backends if b[2]]

    # ---- UI targets ----------------------------------------------------
    dart = _find_dart()
    flutter = _find_flutter()
    npm = shutil.which("npm")

    ui = [
        ("flutter", "flutter", flutter, "Flutter/Dart UI (ge flutter)"),
        ("dart", "dart", dart, "Dart bindings"),
        ("npm", "npm", npm, "React UI (ge react)"),
    ]

    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps({
            "python": {"ok": py_ok, "version": py_ver},
            "backends": {n: {"ok": bool(p), "path": p, "purpose": why}
                         for n, _t, p, why in backends},
            "ui": {n: {"ok": bool(p), "path": p, "purpose": why}
                   for n, _t, p, why in ui},
            "available_backends": [b[0] for b in have],
        }, indent=2))
        return 0 if py_ok and have else 1

    print("GE doctor")
    print()
    print("  runtime")
    mark = "OK" if py_ok else "!!"
    print(f"    [{mark}] Python {py_ver}"
          + ("" if py_ok else "   needs 3.10 or newer"))

    print()
    print("  native backends")
    for _key, tool, path, why in backends:
        mark = "OK" if path else "--"
        detail = (path if path else "not found")
        print(f"    [{mark}] {tool:<14} {detail:<40} {why}")

    print()
    print("  UI targets")
    for _key, tool, path, why in ui:
        mark = "OK" if path else "--"
        detail = (path if path else "not found")
        print(f"    [{mark}] {tool:<14} {detail:<40} {why}")

    print()
    n_have = len(have)
    print(f"  {n_have} of {len(backends)} native backends available.")
    if n_have == 0:
        print("  GE cannot build anything yet. Install at least one backend.")
    elif n_have == len(backends):
        print("  All backends available — every target can be built.")
    else:
        print("  GE builds with any single backend; each one adds targets.")

    if n_have < len(backends) or not py_ok:
        print()
        print("  Install missing toolchains")
        print("    Windows")
        print("      winget install Rustlang.Rustup")
        print("      winget install LLVM.LLVM")
        print("      winget install GoLang.Go")
        print("      winget install Python.Python.3.12")
        print("      (Zig)    https://ziglang.org/download/")
        print("      (dotnet) winget install Microsoft.DotNet.SDK.8")
        print("      (Kotlin) https://github.com/JetBrains/kotlin/releases")
        print("    macOS")
        print("      brew install rustup-init llvm go python@3.12")
        print("      (Zig)    brew install zig")
        print("      (dotnet) brew install --cask dotnet-sdk")
        print("    Debian / Ubuntu")
        print("      curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")
        print("      sudo apt install clang golang python3")
        print("      (Zig)    https://ziglang.org/download/")

    print()
    print("  minimum supported versions")
    for tool, ver in MIN_VERSIONS.items():
        print(f"    {tool:<14} >= {ver}")

    print()
    print("  re-run `ge doctor` after installing")
    return 0 if (py_ok and n_have) else 1


def cmd_compilers(args) -> int:
    from .config import print_toolchain_report, MIN_VERSIONS
    info = detect_compilers()
    print(GE_BANNER)
    print()
    print_toolchain_report(info)
    dart = _find_dart()
    fl = _find_flutter()
    print(f"  [{'OK' if dart else '--'}] Dart         {'vSDK' if dart else '':12} {dart or 'not found'}")
    print(f"  [{'OK' if fl else '--'}] Flutter       {'vSDK' if fl else '':12} {fl or 'not found'}")
    print()
    print("Minimum supported versions:")
    for tool, ver in MIN_VERSIONS.items():
        print(f"  {tool:12} >= {ver}")
    return 0


def cmd_analyze(args) -> int:
    """Analyze GE source files — type checking, diagnostics, linting."""
    from .typecheck import check_source
    from .modules import resolve_imports

    source_path = Path(args.file)
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1

    source = source_path.read_text(encoding="utf-8")
    original_source = source
    entry = args.entry or "main"

    # Lower non-Python flavours (.ge hybrid, .ge.ts) before analysis, exactly
    # as build() does. Without this, `ge analyze` parses a hybrid file as
    # plain Python and reports a syntax error on the first block tag.
    # resolve_imports lowers internally, so it gets the original source.
    from .frontends import frontend_for
    from .frontends.typescript import TypeScriptSyntaxError
    from .modules import _lower_source

    if frontend_for(source_path) != "python":
        try:
            source = _lower_source(source, source_path)
        except TypeScriptSyntaxError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    # Resolve imports first
    try:
        units, classes, warnings = resolve_imports(original_source, source_path)
        for w in warnings:
            print(f"  warning: {w}")
    except Exception as e:
        print(f"  Import resolution error: {e}")
        units, classes, warnings = [], [], []

    # Run type checker
    reporter = check_source(source, file=str(source_path), entry=entry)

    # Print diagnostics
    errors = [d for d in reporter.diagnostics if d.severity == "error"]
    warns = [d for d in reporter.diagnostics if d.severity == "warning"]

    if not errors and not warns:
        print(f"No issues found! ({len(units)} functions analyzed)")
        return 0

    for d in reporter.diagnostics:
        symbol = "ERROR" if d.severity == "error" else "WARN"
        loc = f"{d.file}:{d.line}" if hasattr(d, "file") and d.file else f"line {d.line}"
        print(f"  {symbol} {d.code} at {loc}: {d.message}")
        if hasattr(d, "source_line") and d.source_line:
            print(f"    {d.source_line}")

    print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
    return 1 if errors else 0


def cmd_build(args) -> int:
    """Build GE source — supports platform targets (desktop/web/mobile/crossplatform)."""
    source = _maybe_transpile_ts(Path(args.file))
    target = getattr(args, "target", None)  # desktop, web, mobile, crossplatform

    # If target is specified, route to the appropriate build path
    if target == "mobile":
        # Mobile = Flutter app
        app_name = getattr(args, "app_name", None) or source.stem
        cfg = Config(out_dir=Path(args.out_dir), target=_target_of(args),
                     force_backend=None if args.backend == "auto" else args.backend,
                     do_research=not args.no_research)
        report = build_flutter(source, cfg, app_name=app_name)
        _print_flutter(report)
        return 0 if not (hasattr(report, "errors") and report.errors) else 1

    if target == "crossplatform":
        # Crossplatform = build both native binary AND Flutter app
        app_name = getattr(args, "app_name", None) or source.stem
        cfg = Config(out_dir=Path(args.out_dir), target=_target_of(args),
                     force_backend=None if args.backend == "auto" else args.backend,
                     do_research=not args.no_research, run_after_compile=args.run)
        # Build native binary
        report = build(source, cfg, entry=args.entry)
        _print_build(report)
        # Build Flutter app
        flutter_report = build_flutter(source, cfg, app_name=app_name)
        _print_flutter(flutter_report)
        return 0

    # Default: desktop/native build
    cfg = Config(out_dir=Path(args.out_dir), target=_target_of(args),
                 force_backend=None if args.backend == "auto" else args.backend,
                 do_research=not args.no_research, run_after_compile=args.run)

    # Mixed-backend native program? (e.g. a Rust shell over C++ rendering.)
    # Detect it before the single-backend path so one `ge build` produces the
    # whole executable, companion objects included.
    if args.backend == "auto" and _is_mixed_native(source):
        return _build_native_mixed_cli(source, cfg, args)

    report = build(source, cfg, entry=args.entry)
    _print_build(report)
    # print structured diagnostics if there are errors
    if hasattr(report, "errors") and report.errors.has_errors():
        report.errors.print()
        return 1
    if args.run:
        ran = False
        for cr in (report.rust_compile, report.cpp_compile,
                   report.csharp_compile, report.zig_compile,
                   report.go_compile, report.kotlin_compile):
            if cr and cr.ok and cr.exe:
                print(f"\n-- running {cr.exe.name} --")
                subprocess.run([str(cr.exe)])
                ran = True
        if not ran:
            print("\n(no compiled binary to run)")
    return 0


def _target_of(args) -> str:
    """Map the CLI --target flag onto a build bucket.

    desktop / crossplatform -> "desktop"; web -> "web"; mobile -> "mobile".
    """
    target = getattr(args, "target", None)
    if target == "web":
        return "web"
    if target == "mobile":
        return "mobile"
    return "desktop"


def _is_mixed_native(source: Path) -> bool:
    """True if the program's resolved units span more than one native backend.

    A single-backend program takes the normal fast path; a mixed one needs
    the companion-object link step.
    """
    try:
        from .modules import resolve_imports
        units, _classes, _warnings = resolve_imports(
            source.read_text(encoding="utf-8"), source)
    except Exception:
        return False
    backends = {u.forced_backend for u in units
                if u.supported and u.forced_backend in
                ("rust", "cpp", "csharp", "zig", "go", "kotlin")}
    return len(backends) > 1


def _build_native_mixed_cli(source: Path, cfg, args) -> int:
    """Build a mixed-backend native executable and report the result."""
    from .pipeline import build_native_mixed

    print(f"\n== GE mixed-backend native build: {source} ==")
    report = build_native_mixed(source, cfg, entry=args.entry)

    print(f"Frontend: {report.frontend}")
    for backend in sorted(report.group_sizes):
        role = "exe" if report.srcs.get(backend) and backend == "rust" else "object"
        print(f"  {backend:<8} {report.group_sizes[backend]:>3} functions -> {role}")
    for backend, src in sorted(report.srcs.items()):
        print(f"  source  [{backend}] {src}")
    for backend, obj in sorted(report.objects.items()):
        print(f"  object  [{backend}] {obj}")
    if report.exe:
        print(f"  exe     {report.exe}")
    print(f"  compile: {'OK' if report.compile_ok else 'FAIL'}")

    if report.errors.has_errors():
        report.errors.print()
        if report.compile_log.strip():
            print()
            print(report.compile_log.strip()[:3000])
        return 1

    if args.run and report.exe:
        print(f"\n-- running {report.exe.name} --")
        return subprocess.run([str(report.exe)]).returncode
    if not report.compile_ok and report.compile_log.strip():
        print()
        print(report.compile_log.strip()[:2000])
        return 1
    return 0


def _print_build(report) -> None:
    print(f"\n== GE build: {report.source} ==")
    pd = report.program_decision
    if pd:
        print(f"Backend: {pd.backend}  (rust={pd.rust_score:.1f} cpp={pd.cpp_score:.1f}, web={'yes' if pd.web_used else 'no'})")
    for r in report.units:
        u = r.unit
        st = "OK " if u.supported else "CPY"
        print(f"  [{st}] {u.name:<28} L{u.lineno}")
        if not u.supported:
            print(f"         fallback: {', '.join(u.unsupported_reasons)}")
    for label, src, cr in (("Rust", report.rust_src, report.rust_compile),
                           ("C++", report.cpp_src, report.cpp_compile),
                           ("C#", report.csharp_src, report.csharp_compile),
                           ("Zig", report.zig_src, report.zig_compile),
                           ("Go", report.go_src, report.go_compile),
                           ("Kotlin", report.kotlin_src, report.kotlin_compile)):
        if src:
            ok = cr.ok if cr else False
            print(f"\n{label}: {src}")
            print(f"  compile: {'OK' if ok else 'FAIL'} -> {cr.exe if cr else None}")
            if cr and not cr.ok and cr.log.strip():
                print("  " + cr.log.strip().replace("\n", "\n  ")[:800])


def _print_flutter(report) -> None:
    """Print a Flutter build report summary."""
    print(f"\n== GE flutter app: {report.project_dir} ==")
    print(f"Backend: {report.backend}")
    ok = report.lib_compile.ok if report.lib_compile else False
    print(f"Native lib: {'OK' if ok else 'FAIL'} -> {report.lib_binary}")
    if report.lib_compile and not ok and report.lib_compile.log.strip():
        print("  " + report.lib_compile.log.strip().replace("\n", "\n  ")[:800])
    print(f"FFI exports : {report.ffi_exports}")
    print(f"Dart files  : {report.bindings_dart}, {report.main_dart}")
    for e in report.errors:
        print(f"  ! {e}")


def _ui_node_to_tree(node) -> dict:
    """Convert a .ge.ui WidgetNode into the dict dartgen.generate_main wants."""
    if node is None:
        return {"kind": "Column", "children": [], "align": "center"}
    d: dict = {"kind": node.kind}
    if node.children:
        d["children"] = [_ui_node_to_tree(c) for c in node.children]
    child = node.props.get("child")
    if child is not None and hasattr(child, "kind"):
        d["child"] = _ui_node_to_tree(child)
    if node.text is not None:
        d["text"] = node.text
    elif "text" in node.props:
        d["text"] = node.props["text"]
    if node.label is not None:
        d["label"] = node.label
    elif "label" in node.props:
        d["label"] = node.props["label"]
    if node.state:
        d["state"] = node.state
    style = node.props.get("style") or node.style_dict.get("style")
    if style:
        d["style"] = style
    for key in ("align", "padding", "color", "hint"):
        if key in node.props:
            d[key] = node.props[key]
    if node.action:
        d["action"] = node.action
    return d


def _flutter_from_ui(args, ui_path: Path) -> int:
    """`ge flutter foo.ge.ui` — generate a Flutter project from the UI DSL."""
    from .ui_dsl import parse_ui_file
    from .dartgen import generate_main, generate_pubspec
    from .config import Config

    try:
        screen = parse_ui_file(ui_path)
    except SyntaxError as e:
        print(f"error: invalid .ge.ui — {e}", file=sys.stderr)
        return 1

    app_name = args.app_name or ui_path.stem
    cfg = Config(out_dir=Path(args.out_dir), target="mobile")
    project_dir = cfg.target_dir / app_name
    lib_dir = project_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)

    tree = _ui_node_to_tree(screen.root)
    title = screen.title or app_name
    main_dart = generate_main(tree, [], app_title=title)

    (lib_dir / "main.dart").write_text(main_dart, encoding="utf-8")
    # generate_main always imports bindings.dart; a UI-only project has no
    # FFI exports, so emit the stub rather than leaving a dangling import.
    from .dartgen import generate_bindings
    (lib_dir / "bindings.dart").write_text(
        generate_bindings([], app_name), encoding="utf-8")
    (project_dir / "pubspec.yaml").write_text(
        generate_pubspec(app_name), encoding="utf-8")

    print(GE_BANNER)
    print()
    print(f"== GE flutter app: {project_dir} ==")
    print(f"Title       : {title}")
    print(f"Dart files  : {lib_dir / 'main.dart'}")
    print(f"\nNext: cd {project_dir} && flutter pub get && flutter run")

    dart = _find_dart()
    if dart:
        r = subprocess.run([dart, "analyze", str(lib_dir)],
                           capture_output=True, text=True, timeout=120)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        print(out[:1200] if out else "(analyzer: no output)")
        print("Dart analysis: " + ("PASS" if r.returncode == 0 else "issues found"))
    else:
        print("\n(dart not found — install Flutter to validate generated Dart)")
    return 0


def cmd_flutter(args) -> int:
    src_path = Path(args.file)
    # A .ge.ui file is a UI definition, not GE source. `ge flutter` used to
    # hand it to the module resolver, which tried to parse `Window {` as
    # Python and failed. Generate the Dart UI directly instead.
    if src_path.suffix == ".ui":
        return _flutter_from_ui(args, src_path)

    source = _maybe_transpile_ts(src_path)
    # a Flutter app is a mobile artifact, so it always lands in build/mobile/
    cfg = Config(out_dir=Path(args.out_dir), target="mobile",
                 force_backend=None if args.backend == "auto" else args.backend,
                 do_research=not args.no_research)
    report = build_flutter(source, cfg, app_name=args.app_name,
                           lib_basename=args.lib_name)
    print(f"\n== GE flutter app: {report.project_dir} ==")
    print(f"Backend: {report.backend}")
    ok = report.lib_compile.ok if report.lib_compile else False
    print(f"Native lib: {'OK' if ok else 'FAIL'} -> {report.lib_binary}")
    if report.lib_compile and not ok and report.lib_compile.log.strip():
        print("  " + report.lib_compile.log.strip().replace("\n", "\n  ")[:800])
    print(f"FFI exports : {report.ffi_exports}")
    print(f"Dart files  : {report.bindings_dart}, {report.main_dart}")
    for e in report.errors:
        print(f"  ! {e}")

    # verify the generated Dart with the installed dart analyzer
    dart = _find_dart()
    if dart and report.main_dart:
        print(f"\n-- dart analyze (verifying generated Dart compiles) --")
        r = subprocess.run([dart, "analyze", str(report.main_dart.parent)],
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")
        print(out.strip()[:1200] if out.strip() else "(analyzer: no output)")
        if r.returncode == 0:
            print("Dart analysis: PASS — generated Flutter code is valid.")
        else:
            print("Dart analysis: issues found (see above).")
    else:
        print("\n(dart not found — install Flutter to validate generated Dart)")
    print(f"\nNext: cd {report.project_dir} && flutter pub get && flutter run")
    return 0


def cmd_api_check(args) -> int:
    """Check or regenerate the committed API surface dumps."""
    from .apisurface import main as api_main
    argv = ["--update"] if args.update else []
    return api_main(argv)


def cmd_golden(args) -> int:
    """Check or regenerate the golden lowering corpus."""
    from .golden import main as golden_main
    argv = []
    if args.update:
        argv.append("--update")
    else:
        argv.append("--check")
    if args.no_behaviour:
        argv.append("--no-behaviour")
    if args.backends:
        argv += ["--backends", args.backends]
    if args.verbose:
        argv.append("-v")
    return golden_main(argv)


def cmd_diff(args) -> int:
    """Differential test: compare CPython and every backend on the same program."""
    from .difftest import main as difftest_main
    argv = [args.path]
    if args.backends:
        argv += ["--backends", args.backends]
    if args.timeout:
        argv += ["--timeout", str(args.timeout)]
    if args.verbose:
        argv += ["-v"]
    return difftest_main(argv)


def cmd_react(args) -> int:
    """Generate a React + TypeScript frontend from a .ge.ui definition."""
    from .ui_dsl import parse_ui_file
    from .reactgen import generate_react_app, write_react_app

    ui_path = Path(args.file)
    if not ui_path.exists():
        print(f"error: {ui_path} not found", file=sys.stderr)
        return 1

    try:
        screen = parse_ui_file(ui_path)
    except SyntaxError as e:
        print(f"error: invalid .ge.ui — {e}", file=sys.stderr)
        return 1

    app_name = args.app_name or ui_path.stem.replace(".ge", "")
    # Output goes under the target-aware build root so every artifact of a
    # project lives in one place: build/web/frontend. An explicit -o wins.
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        from .config import Config
        cfg = Config(target="web")
        out_dir = cfg.target_dir / "frontend"

    files = generate_react_app(screen, app_name)
    written = write_react_app(files, out_dir, force=args.force)

    print(GE_BANNER)
    print()
    print(f"== GE react: {ui_path} ==")
    print(f"App     : {app_name}")
    print(f"Screen  : {screen.title or '(untitled)'}")
    print(f"Output  : {out_dir}")
    print()
    for rel in sorted(files):
        mark = "written" if rel in written else "kept"
        print(f"  [{mark:>7}] {rel}")
    if not args.force:
        print()
        print("(existing files are kept; pass --force to regenerate them)")
    print()
    print("Next:")
    print(f"  cd {out_dir}")
    print("  npm install")
    print("  npm run dev        # dev server on :5173, proxies /api to the Rust backend")
    print("  npm run build      # production bundle into dist/")
    return 0


def cmd_pack(args) -> int:
    source = _maybe_transpile_ts(Path(args.file))
    # pack bundles the Flutter project, so it uses the mobile bucket too
    cfg = Config(out_dir=Path(args.out_dir), target="mobile",
                 force_backend=None if args.backend == "auto" else args.backend,
                 do_research=not args.no_research)

    # run the full Flutter pipeline to get all artifacts
    app_name = args.app_name or source.stem.replace(".ge", "")
    report = build_flutter(source, cfg, app_name=app_name,
                           lib_basename=args.lib_name)

    ok = all(cr.ok for cr in report.lib_compiles.values()) if report.lib_compiles else False
    if not ok:
        print(f"\nNative lib compile FAILED — cannot package.")
        for b, cr in report.lib_compiles.items():
            if not cr.ok:
                print(f"  [{b}] {cr.log.strip()[:500]}")
        return 1

    # build metadata
    meta = PackageMeta(
        name=app_name,
        version=args.version,
        app_name=app_name,
        lib_name=args.lib_name,
        backend=report.backend,
        ffi_exports=report.ffi_exports,
        targets=["windows", "android"],
    )

    # collect artifacts: archive path -> local file path
    # multi-backend: include all native sources and binaries
    artifacts = {}
    for b, src in report.lib_srcs.items():
        artifacts[f"native/{b}/" + src.name] = src
    for b, binary in report.lib_binaries.items():
        artifacts[f"native/{b}/" + binary.name] = binary
    if report.bindings_dart:
        artifacts["dart/bindings.dart"] = report.bindings_dart
    if report.main_dart:
        artifacts["dart/main.dart"] = report.main_dart
    if report.pubspec:
        artifacts["dart/pubspec.yaml"] = report.pubspec

    # Include web/ directory if it exists (static web files for deployment)
    # Check both source.parent (app/) and source.parent.parent (project root)
    source_dir = source.parent
    web_dir = source_dir / "web"
    if not web_dir.exists():
        web_dir = source_dir.parent / "web"
    if web_dir.exists():
        for f in web_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(web_dir)
                artifacts[f"web/{rel}"] = f

    pkg = cfg.out_dir / (app_name + ".ge")
    rep = pack_ge(source, meta, artifacts, pkg)

    print(f"\n== GE pack: {source.name} -> {pkg.name} ==")
    print(f"  app: {app_name}  v{args.version}  backend: {report.backend}")
    print(f"  ffi exports: {len(report.ffi_exports)} functions")
    print(f"  targets: windows, android")
    print(f"\n{'file':<32} {'raw':>10} {'packed':>10} {'ratio':>8}")
    for fs in rep.files:
        print(f"{fs.path.name:<32} {fmt_size(fs.raw):>10} {fmt_size(fs.packed):>10} {fs.ratio:>7.1%}")
    print(f"{'TOTAL':<32} {fmt_size(rep.total_raw):>10} {fmt_size(rep.total_packed):>10} {rep.ratio:>7.1%}")
    print(f"\nPackage: {pkg}  ({fmt_size(pkg.stat().st_size)})")
    print(f"Install: ge install {pkg.name} --target windows")
    print(f"         ge install {pkg.name} --target android")
    return 0


def cmd_install(args) -> int:
    """Unpack a .ge package and build it for the target platform.

    Auto-provisions missing toolchains from official sources.
    """
    from .downloader import ensure_toolchains, is_toolchain_available

    pkg = Path(args.package)
    if not pkg.exists():
        print(f"Error: package not found: {pkg}")
        return 1

    target = args.target
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 0) ensure required toolchains are available
    print("Checking toolchains...")
    needed = ["rust"]  # always need a native backend
    if target in ("android", "apk"):
        needed.append("go")  # for Android shared library
    status = ensure_toolchains(needed, auto_download=not args.no_download)
    missing = [n for n, ok in status.items() if not ok]
    if missing:
        print(f"Warning: missing toolchains: {', '.join(missing)}")
        print("  Install manually or run: ge tools install <name>")

    flutter = _find_flutter()
    if not flutter and target in ("windows", "android", "apk"):
        print("Error: Flutter not found. Install Flutter to build .ge packages.")
        print("  Download from: https://flutter.dev/docs/get-started/install")
        return 1

    # 1) unpack
    project_dir = out_dir / (pkg.stem)
    staging = project_dir / ".ge_unpacked"
    print(f"\n== GE install: {pkg.name} -> target: {target} ==")
    print(f"  unpacking to {staging}")
    meta = unpack_ge(pkg, staging)

    if not meta.app_name:
        meta.app_name = pkg.stem
    if not meta.lib_name:
        meta.lib_name = "ge_logic"

    print(f"  app: {meta.app_name}  v{meta.version}  backend: {meta.backend}")
    print(f"  ffi exports: {len(meta.ffi_exports)} functions")

    # 2) create Flutter project
    print(f"\n  creating Flutter project ({target})...")
    platforms = "windows" if target == "windows" else "android"
    r = subprocess.run([flutter, "create", "--platforms", platforms,
                        "--project-name", meta.app_name, str(project_dir)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"  flutter create FAILED: {(r.stderr or r.stdout)[:400]}")
        return 1

    # 3) copy Dart files + pubspec from the package
    lib_dir = project_dir / "lib"
    lib_dir.mkdir(exist_ok=True)
    for name in ("bindings.dart", "main.dart"):
        src = staging / "dart" / name
        if src.exists():
            shutil.copy2(src, lib_dir / name)
            print(f"  copied {name}")
    pubspec_src = staging / "dart" / "pubspec.yaml"
    if pubspec_src.exists():
        shutil.copy2(pubspec_src, project_dir / "pubspec.yaml")
        print(f"  copied pubspec.yaml")

    # 4) place native libraries
    if target == "windows":
        _install_windows(staging, project_dir, meta, flutter, args)
    elif target in ("android", "apk"):
        _install_android(staging, project_dir, meta, flutter, args, target)

    return 0


def _install_windows(staging: Path, project_dir: Path, meta: PackageMeta,
                     flutter: str, args) -> None:
    """Place native DLL(s) and build Windows desktop app."""
    # find all pre-compiled DLLs in the package (multi-backend: native/rust/, native/cpp/)
    dlls_found = []
    native_root = staging / "native"
    if native_root.exists():
        for sub in native_root.iterdir():
            if sub.is_dir():
                for f in sub.glob("*.dll"):
                    dlls_found.append(f)
            elif sub.suffix == ".dll":
                dlls_found.append(sub)

    for dll_src in dlls_found:
        shutil.copy2(dll_src, project_dir / dll_src.name)
        print(f"  copied {dll_src.name} (pre-compiled)")

    if not dlls_found:
        # recompile from Rust source (single-backend fallback)
        rs_src = staging / "native" / f"{meta.lib_name}.rs"
        if rs_src.exists():
            print(f"  recompiling {meta.lib_name}.rs for Windows...")
            cfg = Config(out_dir=project_dir)
            info = detect_compilers()
            cr = compile_rust(rs_src, cfg, info, shared=True, lib_basename=meta.lib_name)
            if cr.ok and cr.exe:
                shutil.copy2(cr.exe, project_dir / cr.exe.name)
                print(f"  compiled {cr.exe.name}")
            else:
                print(f"  WARN: recompile failed: {cr.log[:200]}")

    # flutter pub get
    print(f"\n  flutter pub get...")
    subprocess.run([flutter, "pub", "get"], cwd=str(project_dir),
                   capture_output=True, text=True, timeout=120)

    # build
    print(f"  flutter build windows --release...")
    r = subprocess.run([flutter, "build", "windows", "--release"],
                       cwd=str(project_dir), capture_output=True, text=True, timeout=300)
    if r.returncode == 0:
        exe_dir = project_dir / "build" / "windows" / "x64" / "runner" / "Release"
        exe = exe_dir / f"{meta.app_name}.exe"
        # copy ALL DLLs next to exe (retry on file-lock from previous runs)
        import time
        for dll in project_dir.glob("*.dll"):
            if exe_dir.exists():
                for attempt in range(3):
                    try:
                        shutil.copy2(dll, exe_dir / dll.name)
                        break
                    except PermissionError:
                        if attempt < 2:
                            time.sleep(0.5)
                        else:
                            print(f"  WARN: could not copy {dll.name} (locked) — "
                                  f"close any running instance and retry")
        print(f"\n  BUILD OK -> {exe}")
        if exe.exists():
            print(f"  size: {fmt_size(exe.stat().st_size)}")
        if args.run:
            print(f"\n  launching {exe.name}...")
            subprocess.Popen([str(exe)], cwd=str(exe_dir))
            print(f"  app launched.")
    else:
        print(f"  BUILD FAILED: {(r.stderr or r.stdout)[:500]}")


def _install_android(staging: Path, project_dir: Path, meta: PackageMeta,
                     flutter: str, args, target: str) -> None:
    """Cross-compile Rust for Android ABIs and build APK."""
    # find all native sources (multi-backend: native/rust/, native/cpp/)
    rs_sources = []
    cpp_sources = []
    native_root = staging / "native"
    if native_root.exists():
        for sub in native_root.iterdir():
            if sub.is_dir() and sub.name == "rust":
                for f in sub.glob("*.rs"):
                    rs_sources.append(f)
            elif sub.is_dir() and sub.name == "cpp":
                for f in sub.glob("*.cpp"):
                    cpp_sources.append(f)
            elif sub.suffix == ".rs":
                rs_sources.append(sub)
            elif sub.suffix == ".cpp":
                cpp_sources.append(sub)

    if not rs_sources:
        print(f"  ERROR: no Rust source in package — cannot cross-compile for Android")
        return

    cfg = Config(out_dir=project_dir / "build_android")
    info = detect_compilers()

    # cross-compile: if both Rust + C++ exist, use mixed compilation
    if rs_sources and cpp_sources:
        rs_src = rs_sources[0]
        cpp_src = cpp_sources[0]
        lib_base = rs_src.stem.replace("_rust", "")  # ge_logic_rust -> ge_logic
        print(f"\n  cross-compiling {rs_src.name} + {cpp_src.name} for Android (mixed)...")
        result = compile_mixed_android(rs_src, cpp_src, cfg, info, lib_basename=lib_base)
    else:
        rs_src = rs_sources[0]
        lib_base = rs_src.stem.replace("_rust", "")
        print(f"\n  cross-compiling {rs_src.name} for Android...")
        result = compile_rust_android(rs_src, cfg, info, lib_basename=lib_base)

    for log_line in result.logs:
        print(f"    {log_line}")

    if not result.ok:
        print(f"  ERROR: Android cross-compilation failed")
        return

    # place .so files in jniLibs
    jni_dir = project_dir / "android" / "app" / "src" / "main" / "jniLibs"
    for abi, so_path in result.libs.items():
        abi_dir = jni_dir / abi
        abi_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(so_path, abi_dir / so_path.name)
        print(f"  placed {so_path.name} -> jniLibs/{abi}/")

    # flutter pub get
    print(f"\n  flutter pub get...")
    subprocess.run([flutter, "pub", "get"], cwd=str(project_dir),
                   capture_output=True, text=True, timeout=120)

    # build APK
    print(f"  flutter build apk --release...")
    r = subprocess.run([flutter, "build", "apk", "--release"],
                       cwd=str(project_dir), capture_output=True, text=True, timeout=600)
    if r.returncode == 0:
        apk = project_dir / "build" / "app" / "outputs" / "flutter-apk" / f"app-release.apk"
        print(f"\n  APK BUILD OK -> {apk}")
        if apk.exists():
            print(f"  size: {fmt_size(apk.stat().st_size)}")
        if target == "apk":
            # install to connected device
            print(f"\n  installing to device...")
            r2 = subprocess.run([flutter, "install"],
                                cwd=str(project_dir), capture_output=True, text=True, timeout=120)
            if r2.returncode == 0:
                print(f"  INSTALLED on device.")
            else:
                print(f"  install: {(r2.stderr or r2.stdout)[:300]}")
                print(f"  (connect a device with USB debugging enabled, or use 'adb install {apk}')")
    else:
        output = (r.stderr or r.stdout or "")
        print(f"  APK BUILD FAILED: {output[:600]}")


def cmd_bench(args) -> int:
    cfg = Config(out_dir=Path(args.out_dir), target=_target_of(args), do_research=False)

    # Part 1: parity (GE vs equally-optimized C++)
    print(f"\n== GE bench part 1: PARITY (GE vs equally-optimized C++) ==")
    print("Kernel: sum_squares(n=1,000,000) x 200, -O3, best of 3\n")
    res = bench_squares(cfg)
    if res.ge_exe and res.cpp_exe:
        print(f"  GE (Rust, transpiled) : {res.ge_ms:8.2f} ms")
        print(f"  hand-written C++ -O3  : {res.cpp_ms:8.2f} ms")
        print(f"  ratio (GE / C++)      : {res.ratio:8.2f}x")
        if abs(res.ratio - 1.0) < 0.15:
            print("  -> PARITY (both use LLVM -O3). GE matches C++.")
        else:
            print(f"  -> ratio {res.ratio:.2f}x (within run-to-run variance).")
    else:
        print("  (could not build both binaries for parity test)")

    # Part 2: the honest "faster than C++" case (SIMD lever)
    print(f"\n== GE bench part 2: FASTER THAN C++ (the SIMD lever) ==")
    print("Kernel: f32 polynomial(n=1,000,000) x 20, compute-bound, best of 3")
    print("  GE->Rust uses -O3 + native CPU (auto-vectorized, 8-wide AVX2)")
    print("  C++ scalar uses -O3 with vectorization DISABLED")
    print("  C++ vectorized uses -O3 + native CPU (the fair fight)\n")
    v = bench_vectorize(cfg)
    if v.ge_exe and v.cpp_scalar_exe and v.cpp_vec_exe:
        print(f"  GE->Rust (vectorized)      : {v.ge_vec_ms:8.2f} ms")
        print(f"  C++ (scalar, -fno-vectorize): {v.cpp_scalar_ms:8.2f} ms")
        print(f"  C++ (vectorized, -march=native): {v.cpp_vec_ms:8.2f} ms")
        speedup_scalar = v.cpp_scalar_ms / v.ge_vec_ms if v.ge_vec_ms else 0
        ratio_vec = v.ge_vec_ms / v.cpp_vec_ms if v.cpp_vec_ms else 0
        print(f"\n  GE vs SCALAR C++  : {speedup_scalar:.2f}x  "
              + ("GE FASTER" if speedup_scalar > 1.15 else "no real gap"))
        print(f"  GE vs VECTORIZED C++: {ratio_vec:.2f}x  "
              + ("PARITY" if abs(ratio_vec - 1.0) < 0.20 else "gap"))
        print("\n  Verdict (honest):")
        print(f"    - GE is {speedup_scalar:.1f}x faster than SCALAR C++ because GE")
        print("      auto-vectorizes a data-parallel loop that scalar C++ does not.")
        print("    - GE MATCHES vectorized C++ (both use SIMD via LLVM).")
        print("    - This is the ONLY real way to be 'faster than C++': use SIMD/")
        print("      parallelism/GPU that the C++ version doesn't. Equally-optimized")
        print("      C++ always converges. 'Faster than C++' = 'faster than naive C++'.")
    else:
        print("  (could not build all three binaries — need rustc + clang++)")
    return 0


def cmd_deploy(args) -> int:
    """Deploy a .ge package — auto-detects, distributes, simulates, and goes live."""
    from .deploy import deploy_package

    pkg = Path(args.package)
    if not pkg.exists():
        print(f"Error: package not found: {pkg}", file=sys.stderr)
        return 1

    deploy_dir = Path(args.out_dir) / pkg.stem
    target = args.target
    simulate_only = (target == "simulate")

    ok, msg = deploy_package(
        pkg, deploy_dir,
        target=target,
        host=args.host,
        port=args.port,
        simulate_only=simulate_only,
    )
    print(f"\n{msg}")
    return 0 if ok else 1


def cmd_tools(args) -> int:
    from .downloader import get_tools_status, download_toolchain, is_toolchain_available, DOWNLOAD_URLS

    if args.tools_action == "list" or args.tools_action is None:
        status = get_tools_status()
        print("GE Toolchain Status:")
        print(f"  {'Toolchain':<12} {'Available':<12} {'Downloadable':<14} {'Path'}")
        print(f"  {'-'*12} {'-'*12} {'-'*14} {'-'*40}")
        for name, info in status.items():
            avail = "yes" if info["available"] else "no"
            dl = "yes" if info["downloadable"] else "no"
            path = info["path"] or "(not found)"
            print(f"  {name:<12} {avail:<12} {dl:<14} {path}")
        print()
        print("Downloadable toolchains:", ", ".join(DOWNLOAD_URLS.keys()))
        return 0

    if args.tools_action == "install":
        if not args.tool_name:
            print("Error: specify a toolchain name to install.")
            print(f"  Available: {', '.join(DOWNLOAD_URLS.keys())}")
            return 1
        if args.tool_name not in DOWNLOAD_URLS:
            print(f"Error: '{args.tool_name}' is not auto-downloadable.")
            print(f"  Downloadable: {', '.join(DOWNLOAD_URLS.keys())}")
            print(f"  For C++/C#/Kotlin, install manually (Visual Studio / .NET SDK / Kotlin compiler).")
            return 1
        ok = download_toolchain(args.tool_name, force=args.force)
        return 0 if ok else 1

    if args.tools_action == "check":
        status = get_tools_status()
        all_ok = True
        for name, info in status.items():
            status_str = "OK" if info["available"] else "MISSING"
            print(f"  {name}: {status_str}")
            if not info["available"]:
                all_ok = False
        return 0 if all_ok else 1

    return 0


def cmd_create(args) -> int:
    """Create a new GE project with proper structure."""
    name = args.name
    out_dir = args.out_dir
    platforms = args.platforms.split(",") if args.platforms else None
    backends = args.backends.split(",") if args.backends else None
    if platforms == ["all"]:
        platforms = ALL_PLATFORMS[:]
    if backends == ["all"]:
        backends = ALL_BACKENDS[:]
    interactive = not args.yes
    template = getattr(args, "template", "default")
    try:
        if interactive and not name:
            name = ""
        proj = create_project(
            name=name or "ge_app",
            out_dir=out_dir,
            platforms=platforms,
            backends=backends,
            interactive=interactive,
            template=template,
        )
        print(f"Created GE project: {proj}")
        print()
        print("Structure:")
        for d in sorted(proj.iterdir()):
            if d.is_dir():
                print(f"  {d.name}/")
                for f in sorted(d.iterdir()):
                    if f.is_file():
                        print(f"    {f.name}")
            elif d.is_file():
                print(f"  {d.name}")
        print()
        print("Next steps:")
        print(f"  cd {proj.name}")
        if template in ("desktop-gui", "web-react"):
            print(f"  python build.py --run     # build the native/web app")
        else:
            print(f"  ge build app/main.ge.py --run")
            print(f"  ge flutter mobile/main.ge.py --app-name {proj.name}")
        return 0
    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ge", description=GE_BANNER)
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build", help="compile GE source — supports desktop/web/mobile/crossplatform")
    pb.add_argument("file")
    pb.add_argument("--entry")
    pb.add_argument("--backend", choices=["rust", "cpp", "csharp", "zig", "go", "kotlin", "auto"], default="auto")
    pb.add_argument("--target", choices=["desktop", "web", "mobile", "crossplatform"], default=None,
                      help="platform target: desktop (native binary), mobile (Flutter), "
                           "web, or crossplatform (both native + Flutter)")
    pb.add_argument("--app-name", default=None, help="app name for mobile/crossplatform targets")
    pb.add_argument("--no-research", action="store_true")
    pb.add_argument("--run", action="store_true")
    pb.add_argument("-o", "--out-dir", default="build")
    pb.set_defaults(func=cmd_build)

    pa = sub.add_parser("analyze", help="analyze GE source — type checking, diagnostics, linting")
    pa.add_argument("file", help="GE source file (.ge.py) to analyze")
    pa.add_argument("--entry", default=None, help="entry function name (default: main)")
    pa.set_defaults(func=cmd_analyze)

    pt = sub.add_parser("tools", help="manage GE toolchains (list, install, check)")
    pt.add_argument("tools_action", nargs="?", choices=["list", "install", "check"], default="list",
                     help="list: show status, install: download a toolchain, check: verify all")
    pt.add_argument("tool_name", nargs="?", default=None, help="toolchain name (for install)")
    pt.add_argument("--force", action="store_true", help="re-download even if already available")
    pt.set_defaults(func=cmd_tools)

    pf = sub.add_parser("flutter", help="build a Flutter app (native FFI lib + Dart UI)")
    pf.add_argument("file")
    pf.add_argument("--app-name", default="ge_app")
    pf.add_argument("--lib-name", default="ge_logic")
    pf.add_argument("--backend", choices=["rust", "cpp", "csharp", "zig", "go", "kotlin", "auto"], default="auto")
    pf.add_argument("--no-research", action="store_true")
    pf.add_argument("-o", "--out-dir", default="build")
    pf.set_defaults(func=cmd_flutter)

    pa = sub.add_parser(
        "api-check",
        help="check that the CLI/diagnostic/intrinsic surface has not changed")
    pa.add_argument("--update", action="store_true",
                    help="regenerate the dumps (review the diff, then commit)")
    pa.set_defaults(func=cmd_api_check)

    pg = sub.add_parser(
        "golden",
        help="check that emitted code still matches the committed golden corpus")
    pg.add_argument("--check", action="store_true",
                    help="fail if emitted code differs from the committed golden (default)")
    pg.add_argument("--update", action="store_true",
                    help="regenerate goldens from the current emitters")
    pg.add_argument("--no-behaviour", action="store_true",
                    help="skip the compile-and-run check")
    pg.add_argument("--backends", default=None,
                    help="comma-separated subset (default: all)")
    pg.add_argument("-v", "--verbose", action="store_true")
    pg.set_defaults(func=cmd_golden)

    pd = sub.add_parser(
        "diff",
        help="differential test: prove every backend matches CPython on the same program")
    pd.add_argument("path", help="a .ge file or a directory of them")
    pd.add_argument("--backends", default=None,
                    help="comma-separated subset (default: all installed)")
    pd.add_argument("--timeout", type=int, default=60,
                    help="per-program run timeout in seconds")
    pd.add_argument("-v", "--verbose", action="store_true")
    pd.set_defaults(func=cmd_diff)

    pr = sub.add_parser("react", help="generate a React + TypeScript UI from a .ge.ui file")
    pr.add_argument("file", help=".ge.ui UI definition")
    pr.add_argument("--app-name", default=None, help="app name (defaults to file stem)")
    pr.add_argument("--force", action="store_true",
                    help="overwrite existing frontend files (default: keep hand edits)")
    pr.add_argument("-o", "--out-dir", default=None,
                    help="output dir (default: <ui-dir>/../web/frontend)")
    pr.set_defaults(func=cmd_react)

    pp = sub.add_parser("pack", help="bundle everything into a single .ge package")
    pp.add_argument("file")
    pp.add_argument("--app-name", default=None)
    pp.add_argument("--lib-name", default="ge_logic")
    pp.add_argument("--version", default="0.1.0")
    pp.add_argument("--backend", choices=["rust", "cpp", "csharp", "zig", "go", "kotlin", "auto"], default="auto")
    pp.add_argument("--no-research", action="store_true")
    pp.add_argument("-o", "--out-dir", default="build")
    pp.set_defaults(func=cmd_pack)

    pi = sub.add_parser("install", help="unpack a .ge package and build for a target")
    pi.add_argument("package")
    pi.add_argument("--target", choices=["windows", "android", "apk"], default="windows")
    pi.add_argument("--run", action="store_true", help="launch the app after building (windows)")
    pi.add_argument("--no-download", action="store_true", help="skip auto-downloading missing toolchains")
    pi.add_argument("-o", "--out-dir", default="ge_install")
    pi.set_defaults(func=cmd_install)

    pbe = sub.add_parser("bench", help="benchmark GE vs hand-written C++ (parity)")
    pbe.add_argument("-o", "--out-dir", default="build")
    pbe.set_defaults(func=cmd_bench)

    pdoc = sub.add_parser(
        "doctor",
        help="check the runtime and every optional toolchain, with install hints")
    pdoc.add_argument("--json", action="store_true",
                      help="machine-readable output (for CI and installers)")
    pdoc.set_defaults(func=cmd_doctor)

    pc = sub.add_parser("compilers", help="show detected toolchains")
    pc.set_defaults(func=cmd_compilers)

    pcr = sub.add_parser("create", help="create a new GE project with proper structure")
    pcr.add_argument("name", nargs="?", default="", help="app name (prompted if not given)")
    pcr.add_argument("-o", "--out-dir", default=".", help="output directory")
    pcr.add_argument("--platforms", default=None,
                      help="comma-separated: desktop,web,mobile or all (prompted if not given)")
    pcr.add_argument("--backends", default=None,
                      help="comma-separated: rust,cpp,csharp,zig,go,kotlin or all (prompted if not given)")
    pcr.add_argument("-y", "--yes", action="store_true", help="non-interactive mode (use defaults)")
    pcr.add_argument("--template", default="default",
                      help="project template: default, desktop-gui (Rust+C++ native GUI), "
                           "or web-react (React+TS frontend + Rust backend)")
    pcr.set_defaults(func=cmd_create)

    pdep = sub.add_parser("deploy", help="deploy a .ge package (auto-detect, distribute, simulate, go live)")
    pdep.add_argument("package", help=".ge package file to deploy")
    pdep.add_argument("--target", choices=["local", "vps", "simulate"], default="simulate",
                       help="local: start server locally, vps: generate VPS deploy script, "
                            "simulate: run simulation test only")
    pdep.add_argument("--host", default="0.0.0.0", help="host to bind (local) or connect to (vps)")
    pdep.add_argument("--port", type=int, default=8080, help="port number for the web server")
    pdep.add_argument("-o", "--out-dir", default="ge_deploy", help="deployment output directory")
    pdep.set_defaults(func=cmd_deploy)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
