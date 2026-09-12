"""TypeScript to Python transpiler for the GE language subset.

Users can write GE source in either Python or TypeScript. Both convert to
Rust/C++/Dart via the same pipeline:

  TypeScript (.ts) → Python source → [existing GE pipeline] → Rust/C++/Dart
  Python (.ge.py)  → [existing GE pipeline] → Rust/C++/Dart

Supported TS subset:
  - Functions with typed params and return types
  - let/const variable declarations with types
  - if/else, for, while control flow
  - Arithmetic, comparison, logical operators
  - Array literals, indexing, .length, .push()
  - Widget DSL (build() function with widget constructors)
  - CSS-like style strings
  - console.log() → print()
  - Math.idiv(a, b) → a // b (integer division, GE extension)

Type mappings:
  number → int (GE default: integer arithmetic for financial calc)
  int → int, float → float, string → str, boolean → bool, void → None
  T[] → list, Widget → None
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# ---- Type mappings ----
TS_TO_PY_TYPES = {
    "number": "int",
    "int": "int",
    "float": "float",
    "string": "str",
    "boolean": "bool",
    "bool": "bool",
    "void": "None",
    "Widget": "None",
}

# Widget names (for DSL translation: object args → keyword args)
WIDGETS = {"Text", "Column", "Row", "Container", "ElevatedButton",
           "SizedBox", "Divider", "Expanded"}

# camelCase → snake_case mapping for widget kwargs
CAMEL_TO_SNAKE = {
    "onClick": "on_click",
    "children": "children",
}

# Positional arg keys (first positional in Python widget DSL)
POSITIONAL_KEYS = {"children", "text", "label"}


@dataclass
class Token:
    kind: str
    value: str
    line: int


# ---- Tokenizer ----

_MASTER_RE = re.compile(r'''
    (?P<COMMENT_LINE>//[^\n]*)
  | (?P<COMMENT_BLOCK>/\*.*?\*/)
  | (?P<TEMPLATE>`(?:[^`\\]|\\.)*`)
  | (?P<STRING>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<NUMBER>\d+\.\d+|\d+)
  | (?P<OP>===|!==|==|!=|<=|>=|&&|\|\||\+\+|--|\+=|-=|[+\-*/%<>=!&|])
  | (?P<PUNCT>[(){}\[\];:,.])
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<SKIP>\s+)
  | (?P<UNKNOWN>.)
''', re.VERBOSE | re.DOTALL)


def tokenize(source: str) -> List[Token]:
    tokens = []
    line = 1
    for m in _MASTER_RE.finditer(source):
        kind = m.lastgroup
        value = m.group()
        line += value.count('\n')
        if kind in ("SKIP", "COMMENT_LINE", "COMMENT_BLOCK"):
            continue
        if kind == "TEMPLATE":
            # treat template strings like regular strings
            kind = "STRING"
        if kind == "UNKNOWN":
            continue
        tokens.append(Token(kind, value, line - value.count('\n')))
    tokens.append(Token("EOF", "", line))
    return tokens


# ---- Parser (recursive descent → Python source) ----

class TSParser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        self.lines: List[str] = []
        self.indent = 0

    def emit(self, line: str = ""):
        self.lines.append("    " * self.indent + line)

    # --- token helpers ---
    def peek(self, offset=0) -> Optional[Token]:
        i = self.pos + offset
        return self.tokens[i] if i < len(self.tokens) else None

    def consume(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def match(self, value: str) -> bool:
        t = self.peek()
        return t is not None and t.value == value

    def match_kind(self, kind: str) -> bool:
        t = self.peek()
        return t is not None and t.kind == kind

    def accept(self, value: str) -> Optional[Token]:
        if self.match(value):
            return self.consume()
        return None

    def expect(self, value: str) -> Token:
        if not self.match(value):
            t = self.peek()
            raise SyntaxError(
                f"Expected '{value}', got '{t.value if t else 'EOF'}' at line {t.line if t else '?'}")
        return self.consume()

    # --- program ---
    def parse_program(self) -> str:
        while self.peek() and self.peek().kind != "EOF":
            if self.match("import"):
                self.parse_import()
            elif self.match("function"):
                self.parse_function()
            elif self.peek().value in ("let", "const"):
                self.parse_module_var()
            else:
                # skip unknown module-level code
                self.consume()
        return "\n".join(self.lines)

    def parse_import(self):
        self.consume()  # import
        if self.accept("{"):
            names = []
            while not self.match("}"):
                names.append(self.consume().value)
                self.accept(",")
            self.expect("}")
            self.expect("from")
            mod = self.consume().value.strip('"\'`')
            self.accept(";")
            if "widgets" in mod:
                self.emit(f"from pyeffic.widgets import {', '.join(names)}")
        else:
            # default import — skip
            self.consume()
            self.expect("from")
            self.consume()
            self.accept(";")

    def parse_module_var(self):
        self.consume()  # let/const
        name = self.consume().value
        vtype = ""
        if self.accept(":"):
            vtype = self.parse_type()
        self.expect("=")
        val = self.parse_expr()
        self.accept(";")
        if vtype:
            self.emit(f"{name}: {vtype} = {val}")
        else:
            self.emit(f"{name} = {val}")

    # --- functions ---
    def parse_function(self):
        self.consume()  # function
        name = self.consume().value
        self.expect("(")
        params = self.parse_params()
        self.expect(")")
        ret_type = "None"
        if self.accept(":"):
            ret_type = self.parse_type()
        self.expect("{")
        self.emit(f"def {name}({params}) -> {ret_type}:")
        self.indent += 1
        self.parse_stmts()
        self.indent -= 1
        self.expect("}")
        self.emit()  # blank line after function

    def parse_params(self) -> str:
        params = []
        while not self.match(")"):
            name = self.consume().value
            ptype = ""
            if self.accept(":"):
                ptype = self.parse_type()
            if ptype:
                params.append(f"{name}: {ptype}")
            else:
                params.append(name)
            self.accept(",")
        return ", ".join(params)

    def parse_type(self) -> str:
        base = self.consume().value
        py_type = TS_TO_PY_TYPES.get(base, base)
        # handle T[] (array type)
        while self.accept("["):
            self.expect("]")
            py_type = "list"
        return py_type

    # --- statements ---
    def parse_stmts(self):
        while not self.match("}") and self.peek().kind != "EOF":
            self.parse_stmt()

    def parse_stmt(self):
        t = self.peek()
        if t is None or t.kind == "EOF":
            return
        if t.value in ("let", "const"):
            self.parse_var_decl()
        elif t.value == "if":
            self.parse_if()
        elif t.value == "for":
            self.parse_for()
        elif t.value == "while":
            self.parse_while()
        elif t.value == "return":
            self.parse_return()
        else:
            # expression statement or assignment
            expr = self.parse_expr()
            if self.match("="):
                self.consume()
                val = self.parse_expr()
                self.emit(f"{expr} = {val}")
            else:
                self.emit(expr)
            self.accept(";")

    def parse_var_decl(self):
        self.consume()  # let/const
        name = self.consume().value
        vtype = ""
        if self.accept(":"):
            vtype = self.parse_type()
        self.expect("=")
        val = self.parse_expr()
        self.accept(";")
        if vtype:
            self.emit(f"{name}: {vtype} = {val}")
        else:
            self.emit(f"{name} = {val}")

    def parse_if(self):
        self.consume()  # if
        self.expect("(")
        cond = self.parse_expr()
        self.expect(")")
        self.expect("{")
        self.emit(f"if {cond}:")
        self.indent += 1
        self.parse_stmts()
        self.indent -= 1
        self.expect("}")
        while self.match("else"):
            self.consume()  # else
            if self.match("if"):
                self.consume()  # if
                self.expect("(")
                cond = self.parse_expr()
                self.expect(")")
                self.expect("{")
                self.emit(f"elif {cond}:")
                self.indent += 1
                self.parse_stmts()
                self.indent -= 1
                self.expect("}")
            else:
                self.expect("{")
                self.emit("else:")
                self.indent += 1
                self.parse_stmts()
                self.indent -= 1
                self.expect("}")
                break

    def parse_for(self):
        self.consume()  # for
        self.expect("(")
        # parse init: let i = start
        var = None
        start = "0"
        if self.peek().value in ("let", "const"):
            self.consume()
            var = self.consume().value
            self.accept(":")
            if self.match_kind("IDENT"):
                self.parse_type()  # consume type annotation
            self.expect("=")
            start = self.parse_expr()
        elif self.peek().kind == "IDENT":
            var = self.consume().value
            self.accept("=")
            start = self.parse_expr()
        self.expect(";")
        # parse condition: var < end  or  var <= end
        cond_var = self.consume().value
        op = self.consume().value
        end = self.parse_expr()
        self.expect(";")
        # parse update: var++ or var += n
        self.consume()  # var name
        step = "1"
        if self.accept("++"):
            pass
        elif self.accept("--"):
            step = "-1"
        elif self.accept("+="):
            step = self.parse_expr()
        elif self.accept("-="):
            step = "-" + self.parse_expr()
        self.expect(")")
        self.expect("{")

        # build range
        if op == "<=":
            end_expr = f"{end} + 1"
        else:
            end_expr = end

        # handle .length in condition: i < arr.length → len(arr)
        if step != "1":
            self.emit(f"for {var} in range({start}, {end_expr}, {step}):")
        else:
            self.emit(f"for {var} in range({start}, {end_expr}):")
        self.indent += 1
        self.parse_stmts()
        self.indent -= 1
        self.expect("}")

    def parse_while(self):
        self.consume()  # while
        self.expect("(")
        cond = self.parse_expr()
        self.expect(")")
        self.expect("{")
        self.emit(f"while {cond}:")
        self.indent += 1
        self.parse_stmts()
        self.indent -= 1
        self.expect("}")

    def parse_return(self):
        self.consume()  # return
        if self.match(";") or self.match("}"):
            self.emit("return")
        else:
            val = self.parse_expr()
            self.emit(f"return {val}")
        self.accept(";")

    # --- expressions (recursive descent) ---
    def parse_expr(self) -> str:
        return self.parse_or()

    def parse_or(self) -> str:
        left = self.parse_and()
        while self.match("||"):
            self.consume()
            right = self.parse_and()
            left = f"{left} or {right}"
        return left

    def parse_and(self) -> str:
        left = self.parse_not()
        while self.match("&&"):
            self.consume()
            right = self.parse_not()
            left = f"{left} and {right}"
        return left

    def parse_not(self) -> str:
        if self.match("!"):
            self.consume()
            return f"not {self.parse_not()}"
        return self.parse_comparison()

    def parse_comparison(self) -> str:
        left = self.parse_add()
        while self.peek() and self.peek().value in ("==", "===", "!=", "!==", "<", ">", "<=", ">="):
            op = self.consume().value
            op = "==" if op == "===" else ("!=" if op == "!==" else op)
            right = self.parse_add()
            left = f"{left} {op} {right}"
        return left

    def parse_add(self) -> str:
        left = self.parse_mul()
        while self.peek() and self.peek().value in ("+", "-"):
            op = self.consume().value
            right = self.parse_mul()
            left = f"{left} {op} {right}"
        return left

    def parse_mul(self) -> str:
        left = self.parse_unary()
        while self.peek() and self.peek().value in ("*", "/", "%"):
            op = self.consume().value
            right = self.parse_unary()
            left = f"{left} {op} {right}"
        return left

    def parse_unary(self) -> str:
        if self.match("-"):
            self.consume()
            return f"-{self.parse_unary()}"
        if self.match("+"):
            self.consume()
            return self.parse_unary()
        return self.parse_postfix()

    def parse_postfix(self) -> str:
        expr = self.parse_primary()
        while True:
            if self.match("["):
                self.consume()
                idx = self.parse_expr()
                self.expect("]")
                expr = f"{expr}[{idx}]"
            elif self.match("."):
                self.consume()
                member = self.consume().value
                if self.match("("):
                    self.consume()  # (
                    if member == "length":
                        # arr.length() — unusual but handle it
                        self.expect(")")
                        expr = f"len({expr})"
                    elif member == "push":
                        args = self.parse_args()
                        self.expect(")")
                        expr = f"{expr}.append({args})"
                    else:
                        args = self.parse_args()
                        self.expect(")")
                        expr = self._method_call(expr, member, args)
                else:
                    if member == "length":
                        expr = f"len({expr})"
                    else:
                        expr = f"{expr}.{member}"
            elif self.match("("):
                self.consume()
                if expr in WIDGETS or expr == "Action":
                    args = self.parse_widget_args(expr)
                else:
                    args = self.parse_args()
                self.expect(")")
                expr = self._function_call(expr, args)
            else:
                break
        return expr

    def _method_call(self, obj: str, method: str, args: str) -> str:
        """Translate special method calls."""
        if obj == "Math":
            if method == "idiv":
                # Math.idiv(a, b) → (a // b)
                parts = [p.strip() for p in args.split(",", 1)]
                if len(parts) == 2:
                    return f"({parts[0]} // {parts[1]})"
            if method == "floor":
                return f"int({args})"
            if method == "abs":
                return f"abs({args})"
            if method == "max":
                return f"max({args})"
            if method == "min":
                return f"min({args})"
            if method == "sqrt":
                return f"({args} ** 0.5)"
        return f"{obj}.{method}({args})"

    def _function_call(self, name: str, args: str) -> str:
        """Translate special function calls."""
        if name == "console":
            # console.log(...) → print(...)
            # strip the .log part — console was parsed as name, log as method
            pass
        return f"{name}({args})"

    def parse_args(self) -> str:
        args = []
        while not self.match(")") and self.peek().kind != "EOF":
            args.append(self.parse_expr())
            self.accept(",")
        return ", ".join(args)

    def parse_widget_args(self, widget_name: str) -> str:
        """Parse widget constructor args: { key: value } → key=value."""
        # if not an object literal, use regular args
        if not self.match("{"):
            return self.parse_args()

        self.consume()  # {
        kwargs = []
        positional = None

        while not self.match("}") and self.peek().kind != "EOF":
            key = self.consume().value
            self.expect(":")
            val = self.parse_expr()

            # convert camelCase to snake_case
            py_key = CAMEL_TO_SNAKE.get(key, key)

            # handle positional args
            if key in POSITIONAL_KEYS:
                positional = val
            else:
                kwargs.append(f"{py_key}={val}")

            self.accept(",")

        self.expect("}")

        parts = []
        if positional is not None:
            parts.append(positional)
        parts.extend(kwargs)
        return ", ".join(parts)

    def parse_primary(self) -> str:
        t = self.peek()
        if t is None or t.kind == "EOF":
            raise SyntaxError("Unexpected end of input")

        if t.kind == "NUMBER":
            self.consume()
            # ensure float literals have a decimal point in Python
            if "." not in t.value:
                return t.value  # integer literal
            return t.value

        if t.kind == "STRING":
            self.consume()
            return t.value  # already has quotes

        if t.value == "true":
            self.consume()
            return "True"
        if t.value == "false":
            self.consume()
            return "False"
        if t.value in ("null", "undefined"):
            self.consume()
            return "None"

        if t.value == "(":
            self.consume()
            expr = self.parse_expr()
            self.expect(")")
            return f"({expr})"

        if t.value == "[":
            self.consume()
            elements = []
            while not self.match("]") and self.peek().kind != "EOF":
                elements.append(self.parse_expr())
                self.accept(",")
            self.expect("]")
            return "[" + ", ".join(elements) + "]"

        if t.kind == "IDENT":
            self.consume()
            name = t.value
            # handle console.log → print
            if name == "console":
                if self.match("."):
                    self.consume()
                    method = self.consume().value
                    if method == "log":
                        self.expect("(")
                        args = self.parse_args()
                        self.expect(")")
                        return f"print({args})"
            # handle Math.* calls
            if name == "Math":
                if self.match("."):
                    self.consume()
                    method = self.consume().value
                    if self.match("("):
                        self.consume()
                        args = self.parse_args()
                        self.expect(")")
                        return self._method_call("Math", method, args)
            return name

        raise SyntaxError(f"Unexpected token: {t.value} at line {t.line}")


# ---- Public API ----

def transpile(ts_source: str) -> str:
    """Transpile TypeScript source to Python source (GE subset).

    Delegates to the canonical TypeScript frontend
    (pyeffic.frontends.typescript) so there is a single lowering
    implementation. Falls back to the legacy parser in this module if the
    frontend rejects the input (e.g. widget-DSL syntax), which keeps older
    sources working.
    """
    try:
        from .frontends.typescript import ts_to_python
        return ts_to_python(ts_source)
    except Exception:
        tokens = tokenize(ts_source)
        parser = TSParser(tokens)
        return parser.parse_program()


def transpile_file(ts_path, force: bool = False) -> "Path":
    """Transpile a .ts file to a .ge.py file. Returns the Python file path.

    If a .ge.py with the same stem already exists (e.g. user has both
    myrent.ts and myrent.ge.py), the transpiled output goes to myrent.ts.ge.py
    to avoid clobbering the hand-written Python source.
    """
    from pathlib import Path
    ts_path = Path(ts_path)
    py_source = transpile(ts_path.read_text(encoding="utf-8"))
    py_path = ts_path.with_suffix(".ge.py")
    if py_path.exists() and not force:
        # don't clobber a hand-written .ge.py — use .ts.ge.py instead
        py_path = ts_path.with_suffix(".ts.ge.py")
    py_path.write_text(py_source, encoding="utf-8")
    return py_path
