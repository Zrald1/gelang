"""FFI export layer: pick C-ABI-exportable functions and map names.

Only functions whose params and return are scalars (int/float/bool) can cross
the C ABI safely. List/str functions stay internal to the library (callable by
exported functions, but not directly from Dart). This module tags each FuncUnit
with `ffi_export` and provides C-ABI name mapping (snake_case -> camelCase for
Dart).
"""
from __future__ import annotations

from .analyzer import FuncUnit

SCALAR_FFI = {"int", "float", "bool"}


def is_ffi_exportable(u: FuncUnit) -> bool:
    if not u.supported:
        return False
    if u.name == "main":
        return False
    for _, t in u.params:
        if t not in SCALAR_FFI:
            return False
    if u.ret_type not in SCALAR_FFI and u.ret_type != "None":
        return False
    return True


def tag_ffi(units: list[FuncUnit]) -> None:
    for u in units:
        u.ffi_export = is_ffi_exportable(u)  # type: ignore[attr-defined]


def c_name(name: str) -> str:
    """C-ABI symbol name (kept as-is, snake_case)."""
    return name


def dart_name(name: str) -> str:
    """camelCase Dart binding name."""
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# C-ABI / Dart FFI type mapping
DART_FFI_TYPE = {"int": "Int64", "float": "Double", "bool": "Bool", "None": "Void"}
NATIVE_C_TYPE = {"int": "int64_t", "float": "double", "bool": "bool", "None": "void"}
RUST_C_TYPE = {"int": "i64", "float": "f64", "bool": "bool", "None": "()"}
DART_NATIVE_TYPE = {"int": "int", "float": "double", "bool": "bool", "None": "void"}
