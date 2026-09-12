"""Parse Python source into typed function units and classify features.

Uses Python's ast module. Each top-level function (and methods of classes that
look like plain data containers) becomes a `FuncUnit` with:
  - typed signature (from PEP 484 hints; untyped params default to f64)
  - a feature profile used by the researcher to pick a backend
  - a `supported` flag: True if it lives in the transpilable subset.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

# Types we understand. Anything else -> unsupported (falls back to CPython).
SCALAR_TYPES = {"int", "float", "bool", "str"}
CONTAINER_TYPES = {"list", "tuple", "range", "dict", "set"}


@dataclass
class FuncUnit:
    name: str
    lineno: int
    params: list[tuple[str, str]]  # (name, pytype) pytype is normalized
    ret_type: str
    features: set[str] = field(default_factory=set)
    supported: bool = True
    unsupported_reasons: list[str] = field(default_factory=list)
    body: ast.FunctionDef | None = None
    source: str = ""
    backend: str = "rust"  # filled in by researcher
    emitted: str = ""  # filled in by emitter
    ffi_export: bool = False  # filled in by ffi.tag_ffi
    forced_backend: str | None = None  # set by @rust/@cpp/@dart decorator
    class_name: str = ""  # set for methods: the owning class name
    is_method: bool = False  # True if this is a class method
    # Production: track container element types for heterogeneous containers
    # e.g. {"vals": "str"} means vals is list[str] -> element type is str
    param_elem_types: dict[str, str] = field(default_factory=dict)
    # dict key/value types: {"d": ("str", "int")} means d is dict[str, int]
    param_dict_types: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Number of leading parameters without a default. Calls may
    # supply between n_required_params and len(params) arguments.
    n_required_params: int = 0
    # Default expressions per parameter name, as source text.
    param_defaults: dict[str, str] = field(default_factory=dict)

    def mark_unsupported(self, reason: str) -> None:
        self.supported = False
        self.unsupported_reasons.append(reason)


@dataclass
class ClassUnit:
    """A class definition collected from source."""
    name: str
    lineno: int
    fields: list[tuple[str, str]] = field(default_factory=list)  # (name, type)
    methods: list[str] = field(default_factory=list)  # method names
    constructor_params: list[tuple[str, str]] = field(default_factory=list)
    source: str = ""
    bases: list[str] = field(default_factory=list)  # parent class names
    properties: list[str] = field(default_factory=list)  # @property method names
    static_methods: list[str] = field(default_factory=list)  # @staticmethod names
    class_methods: list[str] = field(default_factory=list)  # @classmethod names


def _norm_type(node: ast.AST | None) -> str:
    """Normalize an annotation node to a simple type string we track."""
    if node is None:
        return "int"  # default for untyped numerics
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    if isinstance(node, ast.Subscript):
        # list[int], list[float], list[str], etc.
        base = _norm_type(node.value)
        return base
    if isinstance(node, ast.BinOp):  # PEP 604 int | None etc.
        return "any"
    return "any"


def _container_elem_type(node: ast.AST | None) -> str:
    """Extract the element type from a container annotation like list[str]."""
    if node is None:
        return "int"
    if isinstance(node, ast.Subscript):
        # list[str] -> str, dict[str, int] -> str (key type)
        sl = node.slice
        if isinstance(sl, ast.Tuple) and sl.elts:
            return _norm_type(sl.elts[0])
        return _norm_type(sl)
    return "int"


def _dict_kv_types(node: ast.AST | None) -> tuple[str, str]:
    """Extract key and value types from a dict annotation like dict[str, int]."""
    if node is None:
        return ("str", "int")
    if isinstance(node, ast.Subscript):
        sl = node.slice
        if isinstance(sl, ast.Tuple) and len(sl.elts) == 2:
            return (_norm_type(sl.elts[0]), _norm_type(sl.elts[1]))
        if isinstance(sl, ast.Name):
            return ("str", _norm_type(sl))
    return ("str", "int")


def _classify_features(func: FuncUnit, fn: ast.FunctionDef) -> None:
    """Walk the function body to record workload features and support."""
    for node in ast.walk(fn):
        # --- feature signals ---
        if isinstance(node, ast.For):
            if isinstance(node.iter, ast.Call) and getattr(node.iter.func, "id", None) == "range":
                func.features.add("numeric_loop")
            else:
                func.features.add("container_iter")
        if isinstance(node, (ast.List, ast.ListComp)):
            func.features.add("list_alloc")
        if isinstance(node, ast.Subscript):
            func.features.add("indexing")
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None)
            if fname in {"sum", "min", "max", "abs", "pow", "round"}:
                func.features.add("math_builtin")
            elif fname == "len":
                func.features.add("len_builtin")
            elif fname == "print":
                func.features.add("io_print")
            elif fname == "append" or (isinstance(node.func, ast.Attribute) and node.func.attr == "append"):
                func.features.add("list_append")
            elif fname in {"enumerate", "zip", "map", "filter", "sorted", "reversed", "any", "all"}:
                func.features.add("iter_builtin")
            elif fname in {"bin", "hex", "oct", "chr", "ord", "repr", "hash", "format", "divmod"}:
                func.features.add("conv_builtin")
            elif fname == "isinstance":
                func.features.add("type_check")
            elif fname == "input":
                func.features.add("io_input")
            elif fname == "range":
                func.features.add("range_call")
            elif fname in ("ge_inline", "ge_raw"):
                func.features.add("inline_code")
                # Security: mark that this function uses inline code injection
                # This is a known RCE vector — callers should validate the source
        if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv)):
            func.features.add("arithmetic")
        if isinstance(node, ast.Compare):
            func.features.add("comparison")
        if isinstance(node, ast.While):
            func.features.add("while_loop")
        if isinstance(node, ast.ClassDef):
            func.features.add("class_use")

        # --- unsupported constructs ---
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None)
            if fname in {"eval", "exec", "compile", "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr", "hasattr", "type"}:
                func.mark_unsupported(f"{fname}() dynamic call")
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            pass  # generators are now supported (lowered to list-building functions)
        if isinstance(node, ast.Lambda):
            pass  # lambdas are now supported by emitters
        if isinstance(node, (ast.AsyncFunctionDef, ast.Await)):
            func.mark_unsupported("async")
        if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            func.mark_unsupported("imports inside function")
        if isinstance(node, ast.Global) or isinstance(node, ast.Nonlocal):
            func.mark_unsupported("global/nonlocal")
        if isinstance(node, ast.With):
            pass  # with statements are now supported by emitters
        if isinstance(node, ast.Attribute) and node.attr in {"__class__", "__dict__", "__mro__"}:
            func.mark_unsupported("runtime introspection")
        if isinstance(node, ast.Starred):
            pass  # *args now supported (limited)
        # del, raise, assert, match are now supported by emitters
        if isinstance(node, ast.Delete):
            func.features.add("del_stmt")
        if isinstance(node, ast.Raise):
            func.features.add("raise_stmt")
        if isinstance(node, ast.Assert):
            func.features.add("assert_stmt")
        if isinstance(node, ast.Match):
            func.features.add("match_stmt")


def parse_source(source: str) -> list[FuncUnit]:
    """Parse source into a list of FuncUnits. Backward-compatible API."""
    units, _classes = parse_source_full(source)
    return units


def collect_constants(source: str) -> dict[str, object]:
    """Extract module-level constant assignments (NAME: type = value).

    Returns a dict mapping constant name to its literal value.
    Only simple scalar constants (int, float, bool, str) are collected.
    These are inlined into native code by the emitter.
    """
    tree = ast.parse(source)
    constants: dict[str, object] = {}
    for node in tree.body:
        # AnnAssign: NAME: type = value  (annotated assignment)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, (int, float, bool, str)):
                    constants[node.target.id] = node.value.value
        # Assign: NAME = value  (plain assignment)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                    if isinstance(node.value.value, (int, float, bool, str)):
                        constants[target.id] = node.value.value
    return constants


def collect_preamble(source: str) -> dict[str, str]:
    """Extract module-level ge_preamble("backend", "raw code") calls.

    Returns a dict mapping backend name to raw code string.
    This code is injected at file scope, after the prelude but before
    function definitions. Used for platform-specific code like Win32 GUI
    that requires file-scope function definitions.

    Example GE source:
        ge_preamble("cpp", '#include <windows.h>\\nvoid win32_helper() { ... }')

    The C++ emitter will insert this code after includes, before functions.
    """
    tree = ast.parse(source)
    preamble: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            fname = getattr(call.func, "id", None)
            if fname == "ge_preamble" and len(call.args) >= 2:
                if (isinstance(call.args[0], ast.Constant)
                        and isinstance(call.args[0].value, str)
                        and isinstance(call.args[1], ast.Constant)
                        and isinstance(call.args[1].value, str)):
                    backend = call.args[0].value
                    code = call.args[1].value
                    # accumulate: multiple preamble calls for same backend are concatenated
                    if backend in preamble:
                        preamble[backend] += "\n" + code
                    else:
                        preamble[backend] = code
    return preamble


def parse_source_full(source: str) -> tuple[list[FuncUnit], list[ClassUnit]]:
    """Parse source into FuncUnits and ClassUnits.

    Returns (function_units, class_units) so emitters can emit struct definitions.
    """
    tree = ast.parse(source)
    units: list[FuncUnit] = []
    classes: list[ClassUnit] = []
    src_lines = source.splitlines()

    # pre-scan: collect class names so function params can use class types
    _class_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            _class_names.add(node.name)

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            params: list[tuple[str, str]] = []
            defaults = node.args.defaults
            # defaults align to the last N args
            n_defaults = len(defaults)
            n_args = len(node.args.args)
            param_elem_types: dict[str, str] = {}
            param_dict_types: dict[str, tuple[str, str]] = {}
            for i, arg in enumerate(node.args.args):
                ptype = _norm_type(arg.annotation)
                if ptype not in SCALAR_TYPES and ptype not in CONTAINER_TYPES and ptype not in _class_names:
                    ptype = "any"
                # if no annotation but has a default, infer from default
                if ptype == "any" and i >= n_args - n_defaults:
                    default_idx = i - (n_args - n_defaults)
                    d = defaults[default_idx]
                    if isinstance(d, ast.Constant):
                        if isinstance(d.value, bool):
                            ptype = "bool"
                        elif isinstance(d.value, int):
                            ptype = "int"
                        elif isinstance(d.value, float):
                            ptype = "float"
                        elif isinstance(d.value, str):
                            ptype = "str"
                # track container element type for heterogeneous containers
                if ptype in CONTAINER_TYPES and arg.annotation is not None:
                    elem_t = _container_elem_type(arg.annotation)
                    if elem_t not in SCALAR_TYPES and elem_t not in CONTAINER_TYPES:
                        elem_t = "int"
                    param_elem_types[arg.arg] = elem_t
                    # track dict key/value types for heterogeneous dicts
                    if ptype == "dict":
                        key_t, val_t = _dict_kv_types(arg.annotation)
                        if key_t not in SCALAR_TYPES and key_t not in CONTAINER_TYPES:
                            key_t = "str"
                        if val_t not in SCALAR_TYPES and val_t not in CONTAINER_TYPES:
                            val_t = "int"
                        param_dict_types[arg.arg] = (key_t, val_t)
                params.append((arg.arg, ptype))
            # handle *args (vararg) — typed as list
            if node.args.vararg:
                ptype = _norm_type(node.args.vararg.annotation)
                if ptype not in SCALAR_TYPES and ptype not in CONTAINER_TYPES:
                    ptype = "list"
                params.append((node.args.vararg.arg, ptype))
            ret = _norm_type(node.returns)
            if ret not in SCALAR_TYPES and ret not in CONTAINER_TYPES and ret != "None" and ret not in _class_names:
                ret = "any"
            # Default arguments: a call may supply between n_required and
            # len(params) arguments; the rest are filled in at the call site.
            _args = node.args.args
            _n_defaults = len(node.args.defaults)
            _n_required = len(_args) - _n_defaults
            _param_defaults: dict[str, str] = {}
            for _i, _a in enumerate(_args):
                if _i >= _n_required:
                    _d = node.args.defaults[_i - _n_required]
                    try:
                        _param_defaults[_a.arg] = ast.unparse(_d)
                    except Exception:
                        _param_defaults[_a.arg] = ""
            unit = FuncUnit(
                name=node.name,
                lineno=node.lineno,
                params=params,
                ret_type=ret,
                body=node,
                source="\n".join(src_lines[node.lineno - 1 : node.end_lineno]),
                param_elem_types=param_elem_types,
                param_dict_types=param_dict_types,
                n_required_params=_n_required,
                param_defaults=_param_defaults,
            )
            # parse @rust/@cpp/@dart/@csharp/@zig/@go decorators for per-function backend selection
            for dec in node.decorator_list:
                dec_name = None
                if isinstance(dec, ast.Name):
                    dec_name = dec.id
                elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                    dec_name = dec.func.id
                if dec_name in ("rust", "cpp", "dart", "csharp", "zig", "go", "kotlin"):
                    unit.forced_backend = dec_name
                    unit.backend = dec_name
                    if dec_name == "dart":
                        # @dart functions stay in Dart — not compiled to native
                        # but still tracked for Dart code generation
                        unit.supported = False
                        unit.unsupported_reasons = ["dart backend (stays in Dart)"]
            # type sanity: any 'any' -> unsupported unless it's None ret
            for _, t in params:
                if t == "any":
                    unit.mark_unsupported("untyped/complex parameter")
            if ret == "any":
                unit.mark_unsupported("untyped/complex return")
            _classify_features(unit, node)
            if not unit.features:
                unit.features.add("plain")
            units.append(unit)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            # imports are fine at module level; ignored by transpiler
            continue
        elif isinstance(node, ast.ClassDef):
            # collect base class names
            base_names: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_names.append(base.id)
            # collect class fields (annotated assignments without value)
            class_fields: list[tuple[str, str]] = []
            constructor_params: list[tuple[str, str]] = []
            property_names: list[str] = []
            static_method_names: list[str] = []
            class_method_names: list[str] = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    ft = _norm_type(item.annotation)
                    if ft not in SCALAR_TYPES and ft not in CONTAINER_TYPES:
                        ft = "any"
                    class_fields.append((item.target.id, ft))
            # collect constructor params if __init__ exists
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    for arg in item.args.args:
                        if arg.arg == "self":
                            continue
                        ptype = _norm_type(arg.annotation)
                        if ptype not in SCALAR_TYPES and ptype not in CONTAINER_TYPES:
                            ptype = "any"
                        constructor_params.append((arg.arg, ptype))
            # detect @property, @staticmethod, @classmethod
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    for dec in item.decorator_list:
                        dec_name = None
                        if isinstance(dec, ast.Name):
                            dec_name = dec.id
                        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                            dec_name = dec.func.id
                        if dec_name == "property":
                            property_names.append(item.name)
                        elif dec_name == "staticmethod":
                            static_method_names.append(item.name)
                        elif dec_name == "classmethod":
                            class_method_names.append(item.name)
            # register the class
            cls_unit = ClassUnit(
                name=node.name,
                lineno=node.lineno,
                fields=class_fields,
                methods=[],
                constructor_params=constructor_params,
                source="\n".join(src_lines[node.lineno - 1 : node.end_lineno]),
                bases=base_names,
                properties=property_names,
                static_methods=static_method_names,
                class_methods=class_method_names,
            )
            classes.append(cls_unit)
            # emit class methods as standalone functions with `self` param
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    # skip __init__ (handled by constructor emission)
                    if item.name == "__init__":
                        continue
                    # check decorators
                    is_static = item.name in static_method_names
                    is_class = item.name in class_method_names
                    is_prop = item.name in property_names
                    cls_unit.methods.append(item.name)
                    params: list[tuple[str, str]] = []
                    if not is_static and not is_class:
                        # add self as first param (typed as the class name)
                        # use _self instead of self (self is reserved in Rust)
                        params.append(("_self", node.name))
                    elif is_class:
                        # classmethod: first param is the class
                        params.append(("_cls", node.name))
                    for arg in item.args.args:
                        if arg.arg in ("self", "cls"):
                            continue
                        ptype = _norm_type(arg.annotation)
                        if ptype not in SCALAR_TYPES and ptype not in CONTAINER_TYPES and ptype != node.name:
                            ptype = "any"
                        params.append((arg.arg, ptype))
                    ret = _norm_type(item.returns)
                    if ret not in SCALAR_TYPES and ret not in CONTAINER_TYPES and ret != "None" and ret != node.name:
                        ret = "any"
                    sub = FuncUnit(
                        name=f"{node.name}.{item.name}",
                        lineno=item.lineno,
                        params=params,
                        ret_type=ret,
                        body=item,
                        source="\n".join(src_lines[item.lineno - 1 : item.end_lineno]),
                        class_name=node.name,
                        is_method=True,
                    )
                    _classify_features(sub, item)
                    if not sub.features:
                        sub.features.add("plain")
                    units.append(sub)
        else:
            # module-level code that isn't a function -> unsupported, runs in CPython
            units.append(
                FuncUnit(
                    name=f"<module@{getattr(node, 'lineno', 0)}>",
                    lineno=getattr(node, "lineno", 0),
                    params=[],
                    ret_type="None",
                    supported=False,
                    unsupported_reasons=["module-level non-function code"],
                    source=ast.get_source_segment(source, node) or "",
                )
            )
    return units, classes
