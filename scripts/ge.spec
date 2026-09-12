# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building GE as a standalone ge.exe binary.

Usage:
    pip install pyinstaller
    pyinstaller ge.spec

Output:
    dist/ge/ge.exe          (standalone binary, ~30MB)
    dist/ge/_internal/      (support files)

The binary bundles the Python runtime + pyeffic package. It does NOT bundle
the language toolchains (rustc, clang++, dotnet, zig, go, kotlinc) — those
must be installed separately or placed in a tools/ directory next to ge.exe.

Build with installer:
    pyinstaller ge.spec
    # then run Inno Setup:
    iscc installer/ge.iss
"""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['ge_entry.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Include any non-Python data files if needed
        # ('README.md', '.'),
        # ('GE_LANG.md', '.'),
        # ('AGENTS.md', '.'),
    ],
    hiddenimports=[
        'pyeffic',
        'pyeffic.ge_cli',
        'pyeffic.analyzer',
        'pyeffic.autoselect',
        'pyeffic.researcher',
        'pyeffic.pipeline',
        'pyeffic.compiler',
        'pyeffic.config',
        'pyeffic.backends',
        'pyeffic.diagnostics',
        'pyeffic.ffi',
        'pyeffic.dartgen',
        'pyeffic.ui_dsl',
        'pyeffic.packer',
        'pyeffic.bench',
        'pyeffic.cli',
        'pyeffic.emitters',
        'pyeffic.emitters.base',
        'pyeffic.emitters.rust',
        'pyeffic.emitters.cpp',
        'pyeffic.emitters.csharp',
        'pyeffic.emitters.zig',
        'pyeffic.emitters.go',
        'pyeffic.emitters.kotlin',
        'pyeffic.emitters.dart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # exclude modules we don't need to keep the binary small
        'tkinter',
        'unittest',
        'pydoc',
        'doctest',
        'pdb',
        'profile',
        'pstats',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ge',
)
