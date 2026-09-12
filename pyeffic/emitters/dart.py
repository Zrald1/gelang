"""Dart emitter: transpile Python functions to Dart for the @dart backend.

@dart functions stay in Dart (Flutter's language) instead of being compiled to
native Rust/C++. They run in Flutter's event loop and have direct access to
Flutter widgets, async, and state management.

Supported subset (same as Rust/C++ emitters):
  - Functions with typed params and return types
  - if/else, for (range), while
  - Arithmetic, comparison, logical operators
  - List literals, indexing, .length, .add()
  - print() → print()
  - Integer and float arithmetic

Type mappings:
  int → int, float → double, bool → bool, str → String
  list → List<int> (default), None → void
"""
from __future__ import annotations

import ast
from ..analyzer import FuncUnit

DART_TYPES = {
    "int": "int",
    "float": "double",
    "bool": "bool",
    "str": "String",
    "None": "void",
    "list": "List<int>",
}


class DartEmitter:
    """Transpile Python function AST to Dart source code."""

    def __init__(self):
        self.lines: list[str] = []
        self.indent_lvl = 0
        self.var_types: dict[str, str] = {}

    def emit_function(self, unit: FuncUnit) -> str:
        """Emit a single function as Dart source."""
        self.lines = []
        self.indent_lvl = 1
        self.var_types = {}

        # seed param types
        for pname, ptype in unit.params:
            self.var_types[pname] = ptype

        # build signature
        params = ", ".join(
            f"{DART_TYPES.get(ptype, 'double')} {pname}"
            for pname, ptype in unit.params
        )
        ret_type = DART_TYPES.get(unit.ret_type, "void")
        sig = f"{ret_type} {unit.name}({params}) {{"

        # emit body
        for stmt in unit.body.body:  # type: ignore[attr-defined]
            self.stmt(stmt)

        body = "\n".join(self.lines)
        return f"{sig}\n{body}\n}}\n"

    def stmt(self, node: ast.AST) -> None:
        ind = "  " * self.indent_lvl
        if isinstance(node, ast.Return):
            if node.value is None:
                self.lines.append(f"{ind}return;")
            else:
                self.lines.append(f"{ind}return {self.expr(node.value)};")
        elif isinstance(node, ast.Assign):
            target = node.targets[0]
            val = self.expr(node.value)
            if isinstance(target, ast.Name):
                t = self.infer_type(node.value)
                self.var_types[target.id] = t
                dt = DART_TYPES.get(t, "double")
                self.lines.append(f"{ind}{dt} {target.id} = {val};")
            elif isinstance(target, ast.Subscript):
                self.lines.append(f"{ind}{self.expr(target)} = {val};")
        elif isinstance(node, ast.AugAssign):
            target = self.expr(node.target)
            op = self.binop_symbol(node.op)
            self.lines.append(f"{ind}{target} {op}= {self.expr(node.value)};")
        elif isinstance(node, ast.AnnAssign):
            if node.value is None:
                if isinstance(node.target, ast.Name):
                    t = self._ann_type(node.annotation)
                    self.var_types[node.target.id] = t
                return
            target = node.target.id if isinstance(node.target, ast.Name) else self.expr(node.target)
            t = self._ann_type(node.annotation) if isinstance(node.target, ast.Name) else self.infer_type(node.value)
            if isinstance(node.target, ast.Name):
                self.var_types[target] = t
            dt = DART_TYPES.get(t, "double")
            self.lines.append(f"{ind}{dt} {target} = {self.expr(node.value)};")
        elif isinstance(node, ast.If):
            self.lines.append(f"{ind}if ({self.expr(node.test)}) {{")
            self.indent_lvl += 1
            for s in node.body:
                self.stmt(s)
            self.indent_lvl -= 1
            if node.orelse:
                if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                    self.lines.append(f"{ind}}} else {self._elif(node.orelse[0])}")
                else:
                    self.lines.append(f"{ind}}} else {{")
                    self.indent_lvl += 1
                    for s in node.orelse:
                        self.stmt(s)
                    self.indent_lvl -= 1
                    self.lines.append(f"{ind}}}")
            else:
                self.lines.append(f"{ind}}}")
        elif isinstance(node, ast.For):
            self.for_loop(node, ind)
        elif isinstance(node, ast.While):
            self.lines.append(f"{ind}while ({self.expr(node.test)}) {{")
            self.indent_lvl += 1
            for s in node.body:
                self.stmt(s)
            self.indent_lvl -= 1
            self.lines.append(f"{ind}}}")
        elif isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Call):
                self.lines.append(f"{ind}{self.expr(node.value)};")
        elif isinstance(node, ast.Pass):
            pass
        else:
            self.lines.append(f"{ind}// unsupported stmt: {type(node).__name__}")

    def _elif(self, node: ast.If) -> str:
        head = f"if ({self.expr(node.test)}) {{"
        save = self.lines
        self.lines = []
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        body = "\n".join(self.lines)
        self.lines = save
        tail = ""
        if node.orelse:
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                tail = " } else " + self._elif(node.orelse[0])
            else:
                save2 = self.lines
                self.lines = []
                self.indent_lvl += 1
                for s in node.orelse:
                    self.stmt(s)
                self.indent_lvl -= 1
                tail = " } else {\n" + "\n".join(self.lines) + "\n" + "  " * self.indent_lvl + "}"
                self.lines = save2
        else:
            tail = "\n" + "  " * self.indent_lvl + "}"
        return head + "\n" + body + tail

    def for_loop(self, node: ast.For, ind: str) -> None:
        var = node.target.id if isinstance(node.target, ast.Name) else "_"
        it = node.iter
        if isinstance(it, ast.Call) and getattr(it.func, "id", None) == "range":
            args = it.args
            if len(args) == 1:
                lo, hi = "0", self.expr(args[0])
            elif len(args) == 2:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            else:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            self.var_types[var] = "int"
            self.lines.append(f"{ind}for (int {var} = {lo}; {var} < {hi}; {var}++) {{")
        else:
            iter_s = self.expr(it)
            self.var_types[var] = "int"
            self.lines.append(f"{ind}for (int {var} in {iter_s}) {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        self.lines.append(f"{ind}}}")

    def expr(self, node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, int):
                return str(v)
            if isinstance(v, float):
                return repr(v)
            if isinstance(v, str):
                return "'" + v.replace("'", "\\'") + "'"
            if v is None:
                return "null"
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.BinOp):
            left = self.expr(node.left)
            right = self.expr(node.right)
            if isinstance(node.op, ast.FloorDiv):
                return f"({left} ~/ {right})"
            if isinstance(node.op, ast.Div):
                return f"({left} / {right})"
            if isinstance(node.op, ast.Pow):
                return f"pow({left}, {right})"
            return f"({left} {self.binop_symbol(node.op)} {right})"
        if isinstance(node, ast.UnaryOp):
            operand = self.expr(node.operand)
            if isinstance(node.op, ast.USub):
                return f"(-{operand})"
            if isinstance(node.op, ast.Not):
                return f"(!{operand})"
        if isinstance(node, ast.BoolOp):
            op = "&&" if isinstance(node.op, ast.And) else "||"
            parts = [self.expr(v) for v in node.values]
            return "(" + f" {op} ".join(parts) + ")"
        if isinstance(node, ast.Compare):
            left = self.expr(node.left)
            parts = []
            cur = left
            for op, comp in zip(node.ops, node.comparators):
                sym = self.cmp_symbol(op)
                right = self.expr(comp)
                parts.append(f"({cur} {sym} {right})")
                cur = right
            return "(" + " && ".join(parts) + ")"
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.Subscript):
            base = self.expr(node.value)
            if isinstance(node.slice, ast.Slice):
                sl = node.slice
                start = self.expr(sl.lower) if sl.lower else "0"
                stop = self.expr(sl.upper) if sl.upper else None
                if stop:
                    return f"{base}.substring({start}, {stop})"
                return f"{base}.substring({start})"
            idx = self.expr(node.slice)
            return f"{base}[{idx}]"
        if isinstance(node, ast.List):
            elems = ", ".join(self.expr(e) for e in node.elts)
            return f"[{elems}]"
        if isinstance(node, ast.JoinedStr):
            # Dart string interpolation: "text ${expr} text"
            parts = []
            for val in node.values:
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    parts.append(val.value.replace("$", "\\$").replace("'", "\\'"))
                elif isinstance(val, ast.FormattedValue):
                    parts.append("${" + self.expr(val.value) + "}")
            return "'" + "".join(parts) + "'"
        if isinstance(node, ast.Attribute):
            base = self.expr(node.value)
            return f"{base}.{node.attr}"
        return f"/*unsupported {type(node).__name__}*/"

    def call(self, node: ast.Call) -> str:
        fname = getattr(node.func, "id", None)
        if fname == "print":
            args = ", ".join(self.expr(a) for a in node.args)
            return f"print({args})"
        if fname == "len":
            return f"{self.expr(node.args[0])}.length"
        if fname == "abs":
            return f"{self.expr(node.args[0])}.abs()"
        if fname == "min":
            args = ", ".join(self.expr(a) for a in node.args)
            return f"min({args})"
        if fname == "max":
            args = ", ".join(self.expr(a) for a in node.args)
            return f"max({args})"
        if fname == "int":
            return f"{self.expr(node.args[0])}.toInt()"
        if fname == "float":
            return f"{self.expr(node.args[0])}.toDouble()"
        if isinstance(node.func, ast.Attribute) and node.func.attr == "append":
            base = self.expr(node.func.value)
            return f"{base}.add({self.expr(node.args[0])})"
        args = ", ".join(self.expr(a) for a in node.args)
        return f"{fname}({args})"

    def _ann_type(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            t = node.id
            return t if t in ("int", "float", "bool", "str", "list") else "float"
        if isinstance(node, ast.Subscript):
            return "list"
        return "float"

    def infer_type(self, node: ast.AST) -> str:
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
            return self.var_types.get(node.id, "float")
        if isinstance(node, ast.BinOp):
            lt = self.infer_type(node.left)
            rt = self.infer_type(node.right)
            if isinstance(node.op, ast.Div):
                return "float"
            if "float" in (lt, rt):
                return "float"
            return "int"
        if isinstance(node, ast.List):
            return "list"
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None)
            if fname == "len":
                return "int"
            if fname == "float":
                return "float"
            if fname == "int":
                return "int"
        return "float"

    def binop_symbol(self, op: ast.AST) -> str:
        return {
            ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Mod: "%",
            ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^",
        }.get(type(op), "?")

    def cmp_symbol(self, op: ast.AST) -> str:
        return {
            ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
            ast.Gt: ">", ast.GtE: ">=", ast.Is: "==", ast.IsNot: "!=",
            ast.In: "in", ast.NotIn: "not in",
        }.get(type(op), "?")


def emit_dart_functions(units: list[FuncUnit]) -> str:
    """Emit all @dart functions as Dart source code."""
    emitter = DartEmitter()
    parts = [
        "// AUTO-GENERATED @dart functions — transpiled from Python by GE.",
        "",
    ]
    for u in units:
        if u.forced_backend == "dart" and u.body is not None:
            parts.append(emitter.emit_function(u))
    return "\n".join(parts)
