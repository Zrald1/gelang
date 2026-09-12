"""End-to-end pipelines.

`build`        — transpile to a native executable (console).
`build_flutter`— transpile logic to a C-ABI shared lib + generate a Flutter
                 project (Dart FFI bindings + widget UI) from the same Python.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .analyzer import FuncUnit, parse_source, parse_source_full, ClassUnit
from .compiler import CompileResult, compile_cpp, compile_rust, compile_csharp, compile_zig, compile_go, compile_kotlin
from .config import CompilerInfo, Config, detect_compilers
from .dartgen import generate_bindings, generate_main, generate_pubspec
from .diagnostics import ErrorReporter, report_compile_error, report_missing_entry
from .emitters import emit_cpp, emit_rust, emit_dart_functions, emit_csharp, emit_zig, emit_go, emit_kotlin
from . import ffi as ffi_mod
from .researcher import Decision, decide_program
from .typecheck import check_source
from .ui import parse_ui, collect_state


@dataclass
class UnitReport:
    unit: FuncUnit
    decision: Decision | None = None
    emitted: str = ""
    source_file: Path | None = None


@dataclass
class BuildReport:
    source: Path
    units: list[UnitReport] = field(default_factory=list)
    program_decision: Decision | None = None
    compilers: CompilerInfo | None = None
    rust_program: str = ""
    cpp_program: str = ""
    csharp_program: str = ""
    zig_program: str = ""
    go_program: str = ""
    kotlin_program: str = ""
    rust_src: Path | None = None
    cpp_src: Path | None = None
    csharp_src: Path | None = None
    zig_src: Path | None = None
    go_src: Path | None = None
    kotlin_src: Path | None = None
    rust_compile: CompileResult | None = None
    cpp_compile: CompileResult | None = None
    csharp_compile: CompileResult | None = None
    zig_compile: CompileResult | None = None
    go_compile: CompileResult | None = None
    kotlin_compile: CompileResult | None = None
    errors: ErrorReporter = field(default_factory=ErrorReporter)
    #: source frontend that produced the IR ("python" or "typescript")
    frontend: str = "python"
    #: functions renamed because their name is a target-language keyword
    renamed_functions: dict[str, str] = field(default_factory=dict)


@dataclass
class NativeMixedReport:
    """Result of a mixed-backend native build.

    GE's native backends interoperate through the C ABI, so a desktop app can
    put the memory-owning shell in Rust and hot code/rendering in C++ and
    still ship one executable.
    """
    source: Path
    entry: str | None = None
    #: backend -> number of functions emitted
    group_sizes: dict[str, int] = field(default_factory=dict)
    #: backend -> emitted source path
    srcs: dict[str, Path] = field(default_factory=dict)
    #: companion object files linked into the executable
    objects: dict[str, Path] = field(default_factory=dict)
    exe: Path | None = None
    compile_ok: bool = False
    compile_log: str = ""
    errors: ErrorReporter = field(default_factory=ErrorReporter)
    frontend: str = "python"



def build(source_path: Path, cfg: Config, entry: str | None = None) -> BuildReport:
    source = source_path.read_text(encoding="utf-8")
    # lower non-Python source flavours (.ge hybrid, .ge.ts) before analysis
    from .frontends import frontend_for
    from .frontends.typescript import TypeScriptSyntaxError
    from .modules import _lower_source
    frontend = frontend_for(source_path)
    lowered_source = source
    if frontend != "python":
        try:
            lowered_source = _lower_source(source, source_path)
        except TypeScriptSyntaxError as exc:
            report = BuildReport(source=source_path, compilers=detect_compilers())
            report.errors.error("GE010", str(exc), file=str(source_path.name),
                                line=exc.line)
            return report
    # resolve imports (merge imported functions into the compilation unit)
    from .modules import resolve_imports, get_last_constants, get_last_preamble
    units, classes, import_warnings = resolve_imports(source, source_path)
    constants = get_last_constants()
    preamble = get_last_preamble()
    info = detect_compilers()
    report = BuildReport(source=source_path, compilers=info)
    report.frontend = frontend

    # report import warnings
    for w in import_warnings:
        report.errors.warning("GE001", w, file=str(source_path.name))

    # report unsupported features with structured diagnostics
    src_lines = lowered_source.splitlines()
    for u in units:
        if not u.supported and u.unsupported_reasons:
            reason = u.unsupported_reasons[0]
            source_line = src_lines[u.lineno - 1] if 0 < u.lineno <= len(src_lines) else ""
            # module-level code is a warning (functions still compile)
            if "module-level" in reason:
                report.errors.warning("GE001", f"unsupported: {reason}",
                                     file=str(source_path.name), line=u.lineno,
                                     source_line=source_line)
            # @dart functions are intentionally not compiled to native — info only
            elif "dart backend" in reason:
                pass  # not an error, the dart emitter handles these
            # build() is a UI function, not meant for native compilation
            elif u.name == "build":
                pass  # UI function, handled by Flutter generator
            else:
                report.errors.error("GE001", f"unsupported: {reason}",
                                  file=str(source_path.name), line=u.lineno,
                                  source_line=source_line)

    # run type checker before emission (on the lowered Python form)
    entry_name = entry or "main"
    type_errors = check_source(lowered_source, file=str(source_path.name),
                               entry=entry_name, classes=classes, units=units)
    for d in type_errors.diagnostics:
        src_line = src_lines[d.line - 1] if 0 < d.line <= len(src_lines) else ""
        if d.severity == "error":
            report.errors.error(d.code, d.message, file=d.file, line=d.line,
                              column=d.column, source_line=src_line)
        else:
            report.errors.warning(d.code, d.message, file=d.file, line=d.line,
                                column=d.column, source_line=src_line)

    supported = [u for u in units if u.supported and u.name != "build"]
    prog_dec, per_fn = decide_program(units, cfg.do_research, cfg.research_timeout, cfg.force_backend)
    report.program_decision = prog_dec

    for u, d in zip(units, per_fn):
        rep = UnitReport(unit=u, decision=d)
        u.backend = d.backend
        report.units.append(rep)

    # Rename any function whose name is a reserved word in a target language.
    # Done here, on the shared IR, so definitions, call sites and the
    # cross-backend `extern "C"` declarations all agree on one symbol.
    from .idents import rename_reserved_functions
    active_backends = {u.backend for u in supported if u.backend}
    if prog_dec and prog_dec.backend:
        active_backends.add(prog_dec.backend)
    renamed = rename_reserved_functions(supported, active_backends)
    if renamed:
        report.renamed_functions = renamed
        for old_name, new_name in renamed.items():
            report.errors.warning(
                "GE011",
                f"renamed '{old_name}' -> '{new_name}': reserved word in "
                f"a target language",
                file=str(source_path.name))

    if not supported:
        return report

    # check for missing entry point
    if entry:
        if not any(u.name == entry for u in supported):
            report.errors.error("GE008", f"entry point '{entry}' not found",
                              file=str(source_path.name))
            return report

    backend = prog_dec.backend
    if backend == "rust":
        prog, emitted_map = emit_rust(supported, entry, classes=classes, constants=constants, preamble=preamble)
        report.rust_program = prog
        report.rust_src = cfg.out("backend", "rust_main.rs")
        report.rust_src.write_text(prog, encoding="utf-8")
    elif backend == "cpp":
        prog, emitted_map = emit_cpp(supported, entry, classes=classes, constants=constants, preamble=preamble)
        report.cpp_program = prog
        report.cpp_src = cfg.out("backend", "cpp_main.cpp")
        report.cpp_src.write_text(prog, encoding="utf-8")
    elif backend == "csharp":
        prog, emitted_map = emit_csharp(supported, entry, classes=classes, constants=constants, preamble=preamble)
        report.csharp_program = prog
        report.csharp_src = cfg.out("backend", "csharp_main.cs")
        report.csharp_src.write_text(prog, encoding="utf-8")
    elif backend == "zig":
        prog, emitted_map = emit_zig(supported, entry, classes=classes, constants=constants, preamble=preamble)
        report.zig_program = prog
        report.zig_src = cfg.out("backend", "zig_main.zig")
        report.zig_src.write_text(prog, encoding="utf-8")
    elif backend == "go":
        prog, emitted_map = emit_go(supported, entry, classes=classes, constants=constants, preamble=preamble)
        report.go_program = prog
        report.go_src = cfg.out("backend", "go_main.go")
        report.go_src.write_text(prog, encoding="utf-8")
    elif backend == "kotlin":
        prog, emitted_map = emit_kotlin(supported, entry, classes=classes, constants=constants, preamble=preamble)
        report.kotlin_program = prog
        report.kotlin_src = cfg.out("backend", "kotlin_main.kt")
        report.kotlin_src.write_text(prog, encoding="utf-8")
    else:
        # default to rust
        prog, emitted_map = emit_rust(supported, entry, classes=classes, constants=constants, preamble=preamble)
        report.rust_program = prog
        report.rust_src = cfg.out("backend", "rust_main.rs")
        report.rust_src.write_text(prog, encoding="utf-8")

    for u in supported:
        for r in report.units:
            if r.unit is u:
                r.emitted = emitted_map.get(u.name, "")

    # Production: report functions that became unsupported during emission
    # (e.g. the emitter found a construct it couldn't translate)
    for u in supported:
        if not u.supported and u.unsupported_reasons:
            for reason in u.unsupported_reasons:
                source_line = src_lines[u.lineno - 1] if 0 < u.lineno <= len(src_lines) else ""
                report.errors.error("GE009", f"emission failed: {reason}",
                                  file=str(source_path.name), line=u.lineno,
                                  source_line=source_line)

    if report.rust_src:
        report.rust_compile = compile_rust(report.rust_src, cfg, info)
        if not report.rust_compile.ok:
            d = report_compile_error("Rust", report.rust_compile.log)
            report.errors.error(d.code, d.message, file=str(source_path.name), line=d.line)
    if report.cpp_src:
        report.cpp_compile = compile_cpp(report.cpp_src, cfg, info)
        if not report.cpp_compile.ok:
            d = report_compile_error("C++", report.cpp_compile.log)
            report.errors.error(d.code, d.message, file=str(source_path.name), line=d.line)
    if report.csharp_src:
        report.csharp_compile = compile_csharp(report.csharp_src, cfg, info)
        if not report.csharp_compile.ok:
            d = report_compile_error("C#", report.csharp_compile.log)
            report.errors.error(d.code, d.message, file=str(source_path.name), line=d.line)
    if report.zig_src:
        report.zig_compile = compile_zig(report.zig_src, cfg, info)
        if not report.zig_compile.ok:
            d = report_compile_error("Zig", report.zig_compile.log)
            report.errors.error(d.code, d.message, file=str(source_path.name), line=d.line)
    if report.go_src:
        report.go_compile = compile_go(report.go_src, cfg, info)
        if not report.go_compile.ok:
            d = report_compile_error("Go", report.go_compile.log)
            report.errors.error(d.code, d.message, file=str(source_path.name), line=d.line)
    if report.kotlin_src:
        report.kotlin_compile = compile_kotlin(report.kotlin_src, cfg, info)
        if not report.kotlin_compile.ok:
            d = report_compile_error("Kotlin", report.kotlin_compile.log)
            report.errors.error(d.code, d.message, file=str(source_path.name), line=d.line)

    return report


# ---------------------------------------------------------------------------
# Flutter pipeline
# ---------------------------------------------------------------------------

@dataclass
class FlutterReport:
    source: Path
    project_dir: Path
    backend: str = "rust"
    # multi-backend: one lib per native backend
    lib_srcs: dict[str, Path] = field(default_factory=dict)  # backend -> .rs/.cpp source
    lib_binaries: dict[str, Path] = field(default_factory=dict)  # backend -> .dll
    lib_compiles: dict[str, CompileResult] = field(default_factory=dict)  # backend -> result
    # legacy single-backend fields (for backward compat)
    lib_src: Path | None = None
    lib_binary: Path | None = None
    lib_compile: CompileResult | None = None
    bindings_dart: Path | None = None
    main_dart: Path | None = None
    pubspec: Path | None = None
    ffi_exports: list[str] = field(default_factory=list)
    state_fields: list[str] = field(default_factory=list)
    ui_tree: dict | None = None
    errors: list[str] = field(default_factory=list)
    # per-function backend mapping (function name -> backend)
    func_backends: dict[str, str] = field(default_factory=dict)
    # @dart functions transpiled to Dart source (merged into main.dart)
    dart_source: str = ""


def build_native_mixed(source_path: Path, cfg: Config,
                       entry: str | None = None) -> NativeMixedReport:
    """Build one native executable from a mix of backends.

    The entry module (and everything it imports) is split by backend:

      * Rust functions become the program's Rust source. The entry point
        lives here, so this group is compiled last and produces the exe.
      * Every other native backend (C++ today) is emitted in library mode
        with `extern "C"` exports and compiled to an object file.
      * The Rust link step pulls those objects in, so both groups end up in
        one binary with no shared library to deploy.

    This is what `ge build <entry> --target desktop` uses when the program
    mixes backends, e.g. a Rust shell over C++ rendering.
    """
    import ast as _ast
    from .modules import resolve_imports, get_last_constants, get_last_preamble
    from .emitters import emit_cpp, emit_rust
    from .frontends import frontend_for
    from .frontends.typescript import TypeScriptSyntaxError

    report = NativeMixedReport(source=source_path, entry=entry)
    info = detect_compilers()

    source = source_path.read_text(encoding="utf-8")
    frontend = frontend_for(source_path)
    report.frontend = frontend
    if frontend != "python":
        from .modules import _lower_source
        try:
            _lower_source(source, source_path)
        except TypeScriptSyntaxError as exc:
            report.errors.error("GE010", str(exc), file=str(source_path.name),
                                line=exc.line)
            return report

    units, classes, import_warnings = resolve_imports(source, source_path)
    constants = get_last_constants()
    preamble = get_last_preamble()
    for w in import_warnings:
        report.errors.warning("GE001", w, file=str(source_path.name))

    # report unsupported units before doing any work
    for u in units:
        if not u.supported and u.unsupported_reasons:
            reason = u.unsupported_reasons[0]
            if u.name == "build":
                continue
            if "module-level" in reason:
                # docstrings / ge_preamble calls at file scope are expected
                report.errors.warning("GE001", f"unsupported: {reason}",
                                      file=str(source_path.name), line=u.lineno)
                continue
            report.errors.error("GE001", f"unsupported: {reason}",
                                file=str(source_path.name), line=u.lineno)

    supported = [u for u in units if u.supported and u.body is not None]

    # assign a backend to every function: explicit decorator wins, otherwise
    # the config default, otherwise auto-selection.
    from .autoselect import select_backend
    groups: dict[str, list[FuncUnit]] = {}
    for u in supported:
        if u.forced_backend in ("rust", "cpp", "csharp", "zig", "go", "kotlin"):
            backend = u.forced_backend
        elif cfg.force_backend:
            backend = cfg.force_backend
        elif u.name == "main":
            # the entry point must live in the backend that links the exe
            backend = "rust"
        else:
            backend, _reasons = select_backend(u)
        groups.setdefault(backend, []).append(u)

    if not groups:
        report.errors.error("GE008", "no compilable functions found",
                            file=str(source_path.name))
        return report

    # rename reserved-word functions before any emitter runs, so the C ABI
    # symbol is identical on both sides of a cross-backend call
    from .idents import rename_reserved_functions
    renamed = rename_reserved_functions(supported, set(groups))
    if renamed:
        report.renamed_functions = renamed
        # grouping keys are unchanged (backend), but unit names moved
        for old_name, new_name in renamed.items():
            report.errors.warning(
                "GE011",
                f"renamed '{old_name}' -> '{new_name}': reserved word in "
                f"a target language",
                file=str(source_path.name))

    # the executable-producing backend: prefer rust, then cpp
    exe_backend = "rust" if "rust" in groups else next(iter(groups))
    companion_backends = [b for b in groups if b != exe_backend]

    # ---- cross-backend call analysis -----------------------------------
    # A companion backend may call into the entry backend and vice versa.
    # Each side needs `extern "C"` declarations for the functions it calls,
    # and the callee side needs its symbols exported with C linkage.
    def _called_from(group_units: list[FuncUnit],
                     candidates: set[str]) -> list[FuncUnit]:
        """Functions from `candidates` that `group_units` actually calls."""
        found: list[FuncUnit] = []
        seen: set[str] = set()
        for u in group_units:
            for node in _ast.walk(u.body):
                if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name):
                    fname = node.func.id
                    if fname in candidates and fname not in seen:
                        seen.add(fname)
                        target = name_to_unit.get(fname)
                        if target is not None:
                            found.append(target)
        return found

    name_to_unit = {u.name: u for u in supported}
    entry_names = {u.name for u in groups.get(exe_backend, [])}
    companion_names: set[str] = set()
    for b in companion_backends:
        companion_names.update(u.name for u in groups.get(b, []))

    # Raw preamble code (ge_preamble) can also call across the boundary —
    # e.g. a Rust shell's WndProc calling C++ helpers — so scan it too.
    def _names_in_preamble(backend: str, candidates: set[str]) -> set[str]:
        import re as _re
        text = preamble.get(backend, "")
        if not text:
            return set()
        hits: set[str] = set()
        for name in candidates:
            if _re.search(rf"\b{_re.escape(name)}\s*\(", text):
                hits.add(name)
        return hits

    entry_preamble_names = _names_in_preamble(exe_backend, companion_names)

    companion_calls_entry: list[FuncUnit] = []
    entry_calls_companion: list[FuncUnit] = []
    for b in companion_backends:
        companion_preamble_names = _names_in_preamble(b, entry_names)
        companion_calls_entry.extend(
            name_to_unit[n] for n in companion_preamble_names
            if n in name_to_unit)
        companion_calls_entry.extend(
            _called_from(groups.get(b, []), entry_names))
        entry_calls_companion.extend(
            _called_from(groups.get(exe_backend, []), companion_names))
    entry_calls_companion.extend(
        name_to_unit[n] for n in entry_preamble_names if n in name_to_unit)
    # de-duplicate while keeping order
    companion_calls_entry = list({u.name: u for u in companion_calls_entry}.values())
    entry_calls_companion = list({u.name: u for u in entry_calls_companion}.values())

    out_dir = cfg.backend_dir()

    # ---- 1) companion backends -> object files -------------------------
    for backend in companion_backends:
        group = groups[backend]
        report.group_sizes[backend] = len(group)
        if backend == "cpp":
            prog, _ = emit_cpp(group, entry=None, library_mode=True,
                               extern_fns=companion_calls_entry or [],
                               classes=classes,
                               constants=constants, preamble=preamble)
            src = out_dir / "mixed_companion.cpp"
            src.write_text(prog, encoding="utf-8")
            report.srcs["cpp"] = src

            if not info.cpp:
                report.errors.error("GE005", "no C++ compiler found",
                                    file=str(source_path.name))
                return report
            obj = cfg.obj_dir() / "mixed_companion.o"
            if info.cpp_kind == "msvc":
                cmd = [info.cpp, "/O2", "/EHsc", "/std:c++17", "/c",
                       f"/Fo{obj}", str(src)]
            else:
                cmd = [info.cpp, "-O2", "-std=c++17", "-w", "-c",
                       "-o", str(obj), str(src)]
            import subprocess as _sp
            r = _sp.run(cmd, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                report.compile_log = (r.stdout or "") + (r.stderr or "")
                report.errors.error("GE005", "C++ companion compilation failed",
                                    file=str(src.name))
                return report
            report.objects["cpp"] = obj
        else:
            report.errors.warning(
                "GE001", f"mixed build: backend '{backend}' is not yet "
                         f"linkable as a companion; its functions are skipped",
                file=str(source_path.name))

    # ---- 2) executable backend ----------------------------------------
    group = groups[exe_backend]
    report.group_sizes[exe_backend] = len(group)

    if exe_backend == "rust":
        prog, _ = emit_rust(group, entry=entry, classes=classes,
                            constants=constants, preamble=preamble,
                            extern_fns=entry_calls_companion or None,
                            export_fns=[u.name for u in companion_calls_entry] or None)
        src = out_dir / "mixed_main.rs"
        src.write_text(prog, encoding="utf-8")
        report.srcs["rust"] = src

        if not info.rustc:
            report.errors.error("GE005", "rustc not found on PATH",
                                file=str(source_path.name))
            return report
        exe = cfg.bin_dir() / ("mixed_main.exe" if _is_windows() else "mixed_main")
        cmd = [info.rustc, "-C", f"opt-level={cfg.opt_level}", "-A", "warnings",
               "-o", str(exe), str(src)]
        for obj in report.objects.values():
            cmd += ["-C", f"link-arg={obj}"]
        if _is_windows():
            # Win32 GUI + audio + HTTP are used by the desktop templates
            for lib in ("user32.lib", "gdi32.lib", "winmm.lib", "winhttp.lib"):
                cmd += ["-C", f"link-arg={lib}"]
        import subprocess as _sp
        r = _sp.run(cmd, capture_output=True, text=True, timeout=600)
        report.compile_log = (r.stdout or "") + (r.stderr or "")
        report.compile_ok = r.returncode == 0
        report.exe = exe if report.compile_ok else None
        if not report.compile_ok:
            report.errors.error("GE005", "Rust link failed",
                                file=str(src.name))
    else:
        report.errors.warning(
            "GE001", f"mixed build: entry backend '{exe_backend}' has no "
                     f"executable path; nothing linked",
            file=str(source_path.name))

    return report


def _is_windows() -> bool:
    import sys
    return sys.platform == "win32"


def build_flutter(source_path: Path, cfg: Config, app_name: str = "pyeffic_app",
                  lib_basename: str = "pyeffic_logic") -> FlutterReport:
    source = source_path.read_text(encoding="utf-8")
    info = detect_compilers()
    # A Flutter project is always a mobile-target artifact, whatever the
    # caller's config says:
    #     build/mobile/<app>/backend/  native sources
    #     build/mobile/<app>/ui/       generated Dart UI
    #     build/mobile/<app>/lib/      compiled library
    project_dir = cfg.out_dir / "mobile" / app_name
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "backend").mkdir(exist_ok=True)
    (project_dir / "ui").mkdir(exist_ok=True)
    (project_dir / "lib").mkdir(exist_ok=True)
    report = FlutterReport(source=source_path, project_dir=project_dir)

    # 1) parse logic + tag FFI (with import resolution)
    from .modules import resolve_imports, get_last_constants, get_last_preamble
    units, classes, import_warnings = resolve_imports(source, source_path)
    constants = get_last_constants()
    preamble = get_last_preamble()
    for w in import_warnings:
        report.errors.append(w)
    logic_units = [u for u in units if u.name != "build"]
    ffi_mod.tag_ffi(logic_units)
    supported = [u for u in logic_units if u.supported]

    # 2) pick default backend for unannotated functions
    prog_dec, _ = decide_program(logic_units, cfg.do_research, cfg.research_timeout,
                                 cfg.force_backend)
    report.backend = prog_dec.backend

    # 3) assign backends: use forced_backend if set, else auto-select per function
    from .autoselect import select_backend
    for u in supported:
        if u.forced_backend:
            backend = u.forced_backend
        elif cfg.force_backend:
            backend = cfg.force_backend
        else:
            # auto-select best backend for this function
            backend, _reasons = select_backend(u)
        # all native backends (not dart — dart stays in Dart)
        if backend in ("rust", "cpp", "csharp", "zig", "go", "kotlin"):
            report.func_backends[u.name] = backend
            u.backend = backend

    # 4) split functions by backend and emit each group
    backend_groups: dict[str, list] = {}
    for u in supported:
        b = report.func_backends.get(u.name)
        if b and b in ("rust", "cpp", "csharp", "zig", "go", "kotlin"):
            backend_groups.setdefault(b, []).append(u)

    # detect cross-backend calls: which functions from backend A are called by backend B
    import ast as _ast
    all_names = {u.name: u for u in supported}
    backend_name_sets = {b: {u.name for u in group} for b, group in backend_groups.items()}

    # find cross-backend calls: for each backend, which functions from OTHER backends does it call?
    cross_calls: dict[str, list[FuncUnit]] = {}  # backend -> list of FuncUnits it calls from other backends
    for backend, group_units in backend_groups.items():
        called = []
        other_names = set()
        for other_b, names in backend_name_sets.items():
            if other_b != backend:
                other_names.update(names)
        for u in group_units:
            for node in _ast.walk(u.body):
                if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name):
                    fname = node.func.id
                    if fname in other_names and all_names.get(fname):
                        if all_names[fname] not in called:
                            called.append(all_names[fname])
        cross_calls[backend] = called

    # for backward compat with existing Rust/C++ specific linking logic
    cpp_called_from_rust = cross_calls.get("rust", [])
    rust_called_from_cpp = cross_calls.get("cpp", [])

    multi = len(backend_groups) > 1

    # emit each backend group with cross-backend extern declarations
    for backend, group_units in backend_groups.items():
        lib_name = f"{lib_basename}_{backend}" if multi else lib_basename
        extern_fns = cross_calls.get(backend, [])
        if backend == "rust":
            export_names = [u.name for u in group_units
                          if any(u.name in {c.name for c in cross_calls.get(b, [])}
                                for b in backend_groups if b != "rust")] if multi else None
            prog, _ = emit_rust(group_units, entry=None, library_mode=True,
                                extern_fns=extern_fns if extern_fns else None,
                                export_fns=export_names, classes=classes, constants=constants, preamble=preamble)
            src_path = project_dir / "backend" / f"{lib_name}.rs"
            src_path.write_text(prog, encoding="utf-8")
            report.lib_srcs["rust"] = src_path
        elif backend == "cpp":
            prog, _ = emit_cpp(group_units, entry=None, library_mode=True,
                               extern_fns=extern_fns if extern_fns else None,
                               classes=classes, constants=constants, preamble=preamble)
            src_path = project_dir / "backend" / f"{lib_name}.cpp"
            src_path.write_text(prog, encoding="utf-8")
            report.lib_srcs["cpp"] = src_path
        elif backend == "csharp":
            prog, _ = emit_csharp(group_units, entry=None, library_mode=True,
                                  classes=classes, constants=constants, preamble=preamble)
            src_path = project_dir / "backend" / f"{lib_name}.cs"
            src_path.write_text(prog, encoding="utf-8")
            report.lib_srcs["csharp"] = src_path
        elif backend == "zig":
            prog, _ = emit_zig(group_units, entry=None, library_mode=True,
                               classes=classes, constants=constants, preamble=preamble)
            src_path = project_dir / "backend" / f"{lib_name}.zig"
            src_path.write_text(prog, encoding="utf-8")
            report.lib_srcs["zig"] = src_path
        elif backend == "go":
            prog, _ = emit_go(group_units, entry=None, library_mode=True,
                              classes=classes, constants=constants, preamble=preamble)
            src_path = project_dir / "backend" / f"{lib_name}.go"
            src_path.write_text(prog, encoding="utf-8")
            report.lib_srcs["go"] = src_path
        elif backend == "kotlin":
            prog, _ = emit_kotlin(group_units, entry=None, library_mode=True,
                                  classes=classes, constants=constants, preamble=preamble)
            src_path = project_dir / "backend" / f"{lib_name}.kt"
            src_path.write_text(prog, encoding="utf-8")
            report.lib_srcs["kotlin"] = src_path

    # compile: if multi-backend, compile C++ to object file and link into Rust DLL
    if multi and "rust" in backend_groups and "cpp" in backend_groups:
        # compile C++ to object file
        cpp_src = report.lib_srcs["cpp"]
        cpp_obj = cpp_src.with_suffix(".obj" if info.cpp_kind == "msvc" else ".o")
        if info.cpp_kind == "msvc":
            cmd = [info.cpp, "/O2", "/EHsc", "/std:c++17", "/c",
                   f"/Fo:{cpp_obj}", str(cpp_src)]
        else:
            # on Windows, clang++ targets MSVC and doesn't support -fPIC
            import os as _os
            is_windows = _os.name == "nt"
            cmd = [info.cpp, "-O2", "-std=c++17", "-w", "-c"]
            if not is_windows:
                cmd += ["-fPIC"]
            cmd += ["-o", str(cpp_obj), str(cpp_src)]
        import subprocess
        r = subprocess.run(cmd, capture_output=True, timeout=120,
                          text=True, encoding="utf-8", errors="replace")
        cpp_ok = r.returncode == 0
        report.lib_compiles["cpp"] = CompileResult(cpp_ok, cpp_obj if cpp_ok else None,
                                                    (r.stdout or "") + (r.stderr or ""))

        # compile Rust cdylib, linking the C++ object file
        rust_src = report.lib_srcs["rust"]
        rust_lib_name = lib_basename  # single DLL: use the base name
        rust_out = rust_src.parent / f"{rust_lib_name}.dll"
        link_arg = str(cpp_obj) if cpp_ok else ""
        cmd = [info.rustc, "-C", f"opt-level={cfg.opt_level}", "-A", "warnings",
               "--crate-type", "cdylib"]
        if link_arg:
            cmd += ["-C", f"link-arg={link_arg}"]
        cmd += ["-o", str(rust_out), str(rust_src)]
        r = subprocess.run(cmd, capture_output=True, timeout=120,
                          text=True, encoding="utf-8", errors="replace")
        rust_ok = r.returncode == 0
        report.lib_compiles["rust"] = CompileResult(rust_ok, rust_out if rust_ok else None,
                                                     (r.stdout or "") + (r.stderr or ""))
        if rust_ok:
            report.lib_binaries["rust"] = rust_out
            # single DLL — use base name for bindings
            report.func_backends = {name: "rust" for name in report.func_backends}
    else:
        # single backend: compile normally
        for backend, group_units in backend_groups.items():
            lib_name = f"{lib_basename}_{backend}" if multi else lib_basename
            if backend == "rust":
                cr = compile_rust(report.lib_srcs["rust"], cfg, info,
                                  shared=True, lib_basename=lib_name)
                report.lib_compiles["rust"] = cr
                if cr.ok and cr.exe:
                    report.lib_binaries["rust"] = cr.exe
            elif backend == "cpp":
                cr = compile_cpp(report.lib_srcs["cpp"], cfg, info,
                                 shared=True, lib_basename=lib_name)
                report.lib_compiles["cpp"] = cr
                if cr.ok and cr.exe:
                    report.lib_binaries["cpp"] = cr.exe

    # backward compat: set legacy fields from the primary backend
    if report.lib_srcs:
        primary = "rust" if "rust" in report.lib_srcs else "cpp"
        report.lib_src = report.lib_srcs.get(primary)
        report.lib_binary = report.lib_binaries.get(primary)
        report.lib_compile = report.lib_compiles.get(primary)

    # 5) parse UI + generate Dart
    try:
        tree = parse_ui(source)
        report.ui_tree = tree
        report.state_fields = sorted(collect_state(tree))
    except Exception as e:
        report.errors.append(f"UI parse failed: {e}")
        tree = {"kind": "Column", "children": [
            {"kind": "Text", "text": f"UI parse error: {e}", "style": "body", "state": ""}], "align": "center"}

    ffi_units = [u for u in supported if getattr(u, "ffi_export", False)]
    report.ffi_exports = [u.name for u in ffi_units]

    # collect @dart functions and transpile them to Dart source
    dart_units = [u for u in logic_units if u.forced_backend == "dart" and u.body is not None]
    dart_source = ""
    if dart_units:
        dart_source = emit_dart_functions(dart_units)
        report.dart_source = dart_source

    # generate bindings with multi-backend support
    # when multi-backend is linked into a single DLL, all functions load from lib_basename
    if multi and "rust" in backend_groups and "cpp" in backend_groups:
        # single DLL — all functions load from lib_basename
        bindings = generate_bindings(ffi_units, lib_basename, None, None)
    else:
        lib_names = {}
        for b in backend_groups:
            lib_names[b] = f"{lib_basename}_{b}" if multi else lib_basename
        bindings = generate_bindings(ffi_units, lib_basename, report.func_backends, lib_names)
    report.bindings_dart = project_dir / "lib" / "bindings.dart"
    report.bindings_dart.write_text(bindings, encoding="utf-8")
    # also copy to ui/ folder for structured output
    (project_dir / "ui" / "bindings.dart").write_text(bindings, encoding="utf-8")

    main_dart = generate_main(tree, ffi_units, app_title=app_name,
                              dart_source=dart_source)
    report.main_dart = project_dir / "lib" / "main.dart"
    report.main_dart.write_text(main_dart, encoding="utf-8")
    # also copy to ui/ folder for structured output
    (project_dir / "ui" / "main.dart").write_text(main_dart, encoding="utf-8")

    pubspec = generate_pubspec(app_name)
    report.pubspec = project_dir / "pubspec.yaml"
    report.pubspec.write_text(pubspec, encoding="utf-8")

    # place the compiled libs next to the Dart project root for easy loading
    for b, binary in report.lib_binaries.items():
        if binary:
            target = project_dir / binary.name
            try:
                target.write_bytes(binary.read_bytes())
            except Exception:
                pass

    return report
