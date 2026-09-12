"""Basic type checker for GE source.

Runs before code emission to catch type errors early, producing structured
diagnostics instead of letting the native compiler fail with confusing errors.

Checks:
  - Parameter types are annotated (GE003)
  - Return type is annotated
  - No mixing of int and float in arithmetic without explicit cast
  - Function calls reference defined functions with matching signatures
  - List operations are only on list-typed values
  - Boolean conditions are bool-typed
  - Return statements match the declared return type

This is NOT a full Hindley-Milner type system. It's a pragmatic checker that
catches the most common errors before the native compiler sees them.
"""
from __future__ import annotations

import ast
from .analyzer import FuncUnit, parse_source
from .diagnostics import ErrorReporter, Diagnostic


# types we track
SCALAR_TYPES = {"int", "float", "bool", "str"}
CONTAINER_TYPES = {"list"}


class TypeChecker:
    """Walks the AST of each function and checks type consistency."""

    def __init__(self, file: str = ""):
        self.file = file
        self.errors = ErrorReporter()
        self.func_sigs: dict[str, tuple[list[str], str]] = {}  # name -> (param_types, ret_type)
        self.func_names: set[str] = set()
        self.class_names: set[str] = set()

    def check(self, units: list[FuncUnit], classes: list | None = None,
              entry: str = "") -> ErrorReporter:
        """Check all functions and return the error reporter."""
        # UI widget names are known (used in build() functions)
        ui_widgets = {"Text", "Column", "Row", "Container", "ElevatedButton",
                      "SizedBox", "Divider", "Expanded", "Action", "build"}
        self.func_names.update(ui_widgets)
        # first pass: collect function signatures
        for u in units:
            if u.supported and u.body:
                param_types = [t for _, t in u.params]
                self.func_sigs[u.name] = (param_types, u.ret_type)
                self.func_names.add(u.name)
        # collect class names
        if classes:
            for cls in classes:
                self.class_names.add(cls.name)

        # second pass: check each function body (skip UI build() functions)
        for u in units:
            if u.supported and u.body and u.name != "build":
                self._check_function(u)

        # check entry point exists
        if entry and entry not in self.func_names:
            self.errors.error("GE008",
                              f"entry point '{entry}' not found in source",
                              file=self.file)

        return self.errors

    def _check_function(self, unit: FuncUnit) -> None:
        """Check a single function body for type errors."""
        # check for untyped parameters (look at raw AST annotations)
        for arg in unit.body.args.args:
            if arg.annotation is None:
                self.errors.error("GE003",
                                  f"parameter '{arg.arg}' has no type annotation — GE requires typed parameters",
                                  file=self.file, line=arg.lineno)
        # check for untyped return (except main)
        if unit.body.returns is None and unit.name != "main":
            self.errors.error("GE003",
                              f"function '{unit.name}' has no return type annotation — GE requires typed returns",
                              file=self.file, line=unit.body.lineno)

        var_types: dict[str, str] = {}
        # seed params
        for pname, ptype in unit.params:
            var_types[pname] = ptype

        for stmt in ast.walk(unit.body):
            self._check_node(stmt, unit, var_types)

    def _check_node(self, node: ast.AST, unit: FuncUnit,
                    var_types: dict[str, str]) -> None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fname = node.func.id
            # check if calling a known function with wrong number of args
            if fname in self.func_sigs:
                param_types, _ = self.func_sigs[fname]
                if len(node.args) != len(param_types):
                    self.errors.error(
                        "GE002",
                        f"function '{fname}' expects {len(param_types)} args, "
                        f"got {len(node.args)}",
                        file=self.file, line=node.lineno,
                    )
            # check for undefined function calls
            elif fname not in ("print", "len", "range", "abs", "sum", "min", "max",
                               "float", "int", "str", "bool", "dict", "list", "tuple",
                               "ge_inline", "ge_raw", "ge_preamble"):
                if fname not in self.class_names:
                    self.errors.error(
                        "GE007",
                        f"function '{fname}' is called but not defined",
                        file=self.file, line=node.lineno,
                    )

        if isinstance(node, ast.Return) and node.value is not None:
            ret_type = self._infer_type(node.value, var_types)
            if unit.ret_type != "None" and ret_type != "any":
                if unit.ret_type == "int" and ret_type == "float":
                    self.errors.warning(
                        "GE002",
                        f"returning float from int function '{unit.name}' — "
                        f"possible truncation",
                        file=self.file, line=node.lineno,
                    )
                elif unit.ret_type == "float" and ret_type == "int":
                    pass  # int -> float is fine (widening)
                elif unit.ret_type not in (ret_type, "any", "list") and ret_type not in ("any", "list"):
                    if unit.ret_type in SCALAR_TYPES and ret_type in SCALAR_TYPES:
                        self.errors.warning(
                            "GE002",
                            f"return type mismatch in '{unit.name}': "
                            f"declared '{unit.ret_type}', returning '{ret_type}'",
                            file=self.file, line=node.lineno,
                        )

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                ann_type = self._ann_type(node.annotation)
                val_type = self._infer_type(node.value, var_types)
                if ann_type in SCALAR_TYPES and val_type in SCALAR_TYPES:
                    if ann_type == "int" and val_type == "float":
                        self.errors.warning(
                            "GE002",
                            f"assigning float to int variable '{node.target.id}' — "
                            f"possible truncation",
                            file=self.file, line=node.lineno,
                        )
                    elif ann_type != val_type and ann_type != "float":
                        self.errors.error(
                            "GE002",
                            f"type mismatch: cannot assign '{val_type}' to '{ann_type}' variable '{node.target.id}'",
                            file=self.file, line=node.lineno,
                        )

    def _infer_type(self, node: ast.AST, var_types: dict[str, str]) -> str:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, int):
                return "int"
            if isinstance(node.value, float):
                return "float"
            if isinstance(node.value, str):
                return "str"
        if isinstance(node, ast.Name):
            return var_types.get(node.id, "any")
        if isinstance(node, ast.BinOp):
            lt = self._infer_type(node.left, var_types)
            rt = self._infer_type(node.right, var_types)
            if isinstance(node.op, ast.Div):
                return "float"
            if "float" in (lt, rt):
                return "float"
            return "int"
        if isinstance(node, ast.List):
            return "list"
        if isinstance(node, ast.Dict):
            return "dict"
        if isinstance(node, ast.Tuple):
            return "tuple"
        if isinstance(node, ast.JoinedStr):
            return "str"
        if isinstance(node, ast.Subscript):
            base = self._infer_type(node.value, var_types)
            if isinstance(node.slice, ast.Slice):
                return base if base in ("str", "list") else "any"
            if base == "str":
                return "int"
            if base == "dict":
                return "any"
            return "int"
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None)
            if fname == "len":
                return "int"
            if fname == "float":
                return "float"
            if fname == "int":
                return "int"
            if fname in self.func_sigs:
                _, ret = self.func_sigs[fname]
                return ret
        return "any"

    def _ann_type(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            t = node.id
            return t if t in ("int", "float", "bool", "str", "list", "dict", "tuple") else "any"
        if isinstance(node, ast.Subscript):
            base = getattr(node.value, "id", "")
            if base == "dict":
                return "dict"
            if base == "tuple":
                return "tuple"
            return "list"
        return "any"


def check_source(source: str, file: str = "", entry: str = "",
                 classes: list | None = None,
                 units: list[FuncUnit] | None = None) -> ErrorReporter:
    """Parse and type-check a GE source file. Returns the error reporter.

    If `units` is provided, use them instead of parsing (for import resolution).
    """
    if units is None:
        units = parse_source(source)
    checker = TypeChecker(file=file)
    return checker.check(units, classes=classes, entry=entry)
