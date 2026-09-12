"""pyeffic command line interface.

Usage:
  python -m pyeffic build <file.py> [--entry NAME] [--backend rust|cpp|auto]
                                    [--no-research] [--run] [-o DIR]
  python -m pyeffic inspect <file.py> [--no-research]
  python -m pyeffic show <file.py> [--backend rust|cpp|auto] [--no-research]
  python -m pyeffic compilers
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .config import Config, compiler_version, detect_compilers
from .pipeline import build, build_flutter


def _print_compilers() -> int:
    info = detect_compilers()
    print("Detected compilers:")
    print(f"  rustc : {info.rustc or '(not found)'}"
          + (f"  [{compiler_version('rustc')}]" if info.rustc else ""))
    print(f"  c++   : {info.cpp or '(not found)'} ({info.cpp_kind or '-'})"
          + (f"  [{compiler_version(info.cpp)}]" if info.cpp else ""))
    return 0


def _print_report(report) -> None:
    print(f"\n== {report.source} ==")
    info = report.compilers
    print(f"rustc={info.rustc or '-'}  cpp={info.cpp or '-'}")
    pd = report.program_decision
    if pd:
        print(f"\nProgram backend: {pd.backend}  (rust={pd.rust_score:.1f} cpp={pd.cpp_score:.1f}, web={'yes' if pd.web_used else 'no'})")
    print(f"\nFunctions ({len(report.units)}):")
    for r in report.units:
        u = r.unit
        status = "OK " if u.supported else "CPY"
        be = r.decision.backend if r.decision else "cpython"
        print(f"  [{status}] {u.name:<28} -> {be:<4}  L{u.lineno}")
        if not u.supported:
            print(f"         unsupported: {', '.join(u.unsupported_reasons)}")
        elif r.decision:
            print(f"         rust={r.decision.rust_score:.1f} cpp={r.decision.cpp_score:.1f}")
    if pd and pd.reasons:
        print("\nDecision rationale:")
        for reason in pd.reasons[:6]:
            print(f"  - {reason}")
        if len(pd.reasons) > 6:
            print(f"  ... (+{len(pd.reasons)-6} more)")
    if report.rust_src:
        print(f"\nRust source : {report.rust_src}")
        if report.rust_compile:
            print(f"  compile: {'OK' if report.rust_compile.ok else 'FAIL'} -> {report.rust_compile.exe}")
            if not report.rust_compile.ok and report.rust_compile.log.strip():
                print("  " + report.rust_compile.log.strip().replace("\n", "\n  "))
    if report.cpp_src:
        print(f"\nC++ source  : {report.cpp_src}")
        if report.cpp_compile:
            print(f"  compile: {'OK' if report.cpp_compile.ok else 'FAIL'} -> {report.cpp_compile.exe}")
            if not report.cpp_compile.ok and report.cpp_compile.log.strip():
                print("  " + report.cpp_compile.log.strip().replace("\n", "\n  "))


def cmd_build(args) -> int:
    cfg = Config(
        out_dir=Path(args.out_dir),
        force_backend=None if args.backend == "auto" else args.backend,
        do_research=not args.no_research,
        run_after_compile=args.run,
    )
    report = build(Path(args.file), cfg, entry=args.entry)
    _print_report(report)
    if args.run:
        ran = False
        if report.rust_compile and report.rust_compile.ok and report.rust_compile.exe:
            print("\n-- running Rust binary --")
            subprocess.run([str(report.rust_compile.exe)])
            ran = True
        if report.cpp_compile and report.cpp_compile.ok and report.cpp_compile.exe:
            print("\n-- running C++ binary --")
            subprocess.run([str(report.cpp_compile.exe)])
            ran = True
        if not ran:
            print("\n(no compiled binary to run)")
    return 0


def cmd_inspect(args) -> int:
    cfg = Config(do_research=not args.no_research)
    report = build(Path(args.file), cfg)
    _print_report(report)
    return 0


def cmd_show(args) -> int:
    cfg = Config(
        force_backend=None if args.backend == "auto" else args.backend,
        do_research=not args.no_research,
    )
    report = build(Path(args.file), cfg)
    if report.rust_program:
        print("\n===== RUST =====\n")
        print(report.rust_program)
    if report.cpp_program:
        print("\n===== C++ =====\n")
        print(report.cpp_program)
    if not report.rust_program and not report.cpp_program:
        print("(no transpilable functions)")
    return 0


def cmd_flutter(args) -> int:
    cfg = Config(
        out_dir=Path(args.out_dir),
        force_backend=None if args.backend == "auto" else args.backend,
        do_research=not args.no_research,
    )
    report = build_flutter(Path(args.file), cfg, app_name=args.app_name,
                           lib_basename=args.lib_name)
    print(f"\n== Flutter project: {report.project_dir} ==")
    print(f"Backend: {report.backend}")
    print(f"Native lib source : {report.lib_src}")
    if report.lib_compile:
        ok = report.lib_compile.ok
        print(f"Shared lib compile: {'OK' if ok else 'FAIL'} -> {report.lib_binary}")
        if not ok and report.lib_compile.log.strip():
            print("  " + report.lib_compile.log.strip().replace("\n", "\n  "))
    print(f"FFI exports       : {report.ffi_exports}")
    print(f"State fields      : {report.state_fields}")
    print(f"Dart bindings     : {report.bindings_dart}")
    print(f"Dart main         : {report.main_dart}")
    print(f"pubspec.yaml      : {report.pubspec}")
    for e in report.errors:
        print(f"  ! {e}")
    print(f"\nNext: cd {report.project_dir} && flutter pub get && flutter run")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pyeffic", description="Python -> C++/Rust transpiler")
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build", help="transpile, compile, optionally run")
    pb.add_argument("file")
    pb.add_argument("--entry", default=None, help="entry function name (default: first function)")
    pb.add_argument("--backend", choices=["rust", "cpp", "auto"], default="auto")
    pb.add_argument("--no-research", action="store_true", help="skip web research, heuristics only")
    pb.add_argument("--run", action="store_true", help="run compiled binary after build")
    pb.add_argument("-o", "--out-dir", default="pyeffic_build")
    pb.set_defaults(func=cmd_build)

    pi = sub.add_parser("inspect", help="analyze + pick backends, no compile")
    pi.add_argument("file")
    pi.add_argument("--no-research", action="store_true")
    pi.set_defaults(func=cmd_inspect)

    ps = sub.add_parser("show", help="print emitted C++/Rust source")
    ps.add_argument("file")
    ps.add_argument("--backend", choices=["rust", "cpp", "auto"], default="auto")
    ps.add_argument("--no-research", action="store_true")
    ps.set_defaults(func=cmd_show)

    pf = sub.add_parser("flutter", help="build a Flutter app: native FFI lib + Dart UI")
    pf.add_argument("file")
    pf.add_argument("--app-name", default="pyeffic_app", help="Flutter project / app name")
    pf.add_argument("--lib-name", default="pyeffic_logic", help="native library basename")
    pf.add_argument("--backend", choices=["rust", "cpp", "auto"], default="auto")
    pf.add_argument("--no-research", action="store_true")
    pf.add_argument("-o", "--out-dir", default="pyeffic_build")
    pf.set_defaults(func=cmd_flutter)

    pc = sub.add_parser("compilers", help="show detected compilers")
    pc.set_defaults(func=lambda a: _print_compilers())

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
