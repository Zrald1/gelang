"""TypeScript-flavoured GE frontend.

Lowers a strictly-typed TypeScript subset into the same IR the Python-like
frontend produces, so every existing backend (Rust/C++/C#/Zig/Go/Kotlin)
works unchanged.

Design (following foundry-transpile / smelt):
    TypeScript source --tokenize--> --parse--> Python source --ast.parse--> IR

Emitting Python source and reusing `ast.parse` keeps one single source of
truth for the IR and guarantees both frontends behave identically from the
analyzer onward.

Supported subset
----------------
    function f(a: number, b: string): number { ... }
    let x: number = 1;        const Y: string = "s";
    if / else if / else
    while (cond) { ... }
    for (let i: number = 0; i < n; i = i + 1) { ... }
    return expr;
    console.log(x);           -> print(x)
    gePreamble("cpp", "...")  -> ge_preamble(...)
    geInline / geRaw          -> ge_inline / ge_raw
    operators: + - * / % ** === !== == != < <= > >= && || ! & |
    types: number string boolean void any number[] T[]
    template literals: `Hi ${name}` -> f"Hi {name}"
    arrays: [1, 2, 3], indexing a[i], arr.length -> len(arr)

Anything outside the subset raises `TypeScriptSyntaxError` with a line
number, so failures are loud rather than silently wrong.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..analyzer import FuncUnit, parse_source_full, collect_constants, collect_preamble


class TypeScriptSyntaxError(Exception):
    """Raised when the input is outside the supported TypeScript subset."""

    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.line = line
        self.col = col
        loc = f" (line {line})" if line else ""
        super().__init__(f"TypeScript frontend{loc}: {message}")


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

KEYWORDS = {
    "function", "let", "const", "var", "if", "else", "while", "for",
    "return", "true", "false", "null", "undefined", "export", "import",
    "from", "interface", "type", "new", "break", "continue", "class",
}

# longest-first so `===` wins over `==`
OPERATORS = [
    "===", "!==", "**=", "...", "=>",
    "==", "!=", "<=", ">=", "&&", "||", "++", "--",
    "+=", "-=", "*=", "/=", "%=", "**",
    "+", "-", "*", "/", "%", "<", ">", "=", "!", "(", ")", "{", "}",
    "[", "]", ";", ",", ":", ".", "?", "&", "|", "@",
]

_NUM_RE = re.compile(r"(?:0[xX][0-9a-fA-F]+)|(?:\d+\.\d+)|(?:\d+)")
_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0",
    "\\": "\\", '"': '"', "'": "'", "`": "`", "$": "$",
}


def _decode_escape(ch: str) -> str:
    """Decode a single backslash escape from a TS string/template."""
    return _ESCAPES.get(ch, ch)


@dataclass
class Token:
    kind: str  # ident | number | string | template | op | eof
    value: str
    line: int
    col: int

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Token({self.kind},{self.value!r}@{self.line})"


def tokenize(src: str) -> list[Token]:
    """Turn TypeScript source into a token stream."""
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(src)

    def advance(k: int) -> None:
        nonlocal i, line, col
        for ch in src[i:i + k]:
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1
        i += k

    while i < n:
        ch = src[i]

        # whitespace
        if ch in " \t\r\n":
            advance(1)
            continue

        # line comment
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                advance(1)
            continue

        # block comment
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            if end == -1:
                raise TypeScriptSyntaxError("unterminated block comment", line, col)
            advance(end + 2 - i)
            continue

        # string literal
        if ch in "\"'":
            quote = ch
            start_line, start_col = line, col
            advance(1)
            buf: list[str] = []
            while i < n and src[i] != quote:
                if src[i] == "\\" and i + 1 < n:
                    buf.append(_decode_escape(src[i + 1]))
                    advance(2)
                    continue
                if src[i] == "\n":
                    raise TypeScriptSyntaxError("unterminated string", start_line, start_col)
                buf.append(src[i])
                advance(1)
            if i >= n:
                raise TypeScriptSyntaxError("unterminated string", start_line, start_col)
            advance(1)
            tokens.append(Token("string", "".join(buf), start_line, start_col))
            continue

        # template literal
        if ch == "`":
            start_line, start_col = line, col
            advance(1)
            buf = []
            depth = 0
            while i < n:
                c = src[i]
                if c == "\\" and i + 1 < n:
                    # keep escapes verbatim: template content is either raw
                    # target-language code (intrinsics) or an f-string body,
                    # and in both cases the escape must survive to the emitter
                    buf.append(src[i:i + 2])
                    advance(2)
                    continue
                if c == "$" and i + 1 < n and src[i + 1] == "{":
                    depth += 1
                    buf.append("${")
                    advance(2)
                    continue
                if c == "}" and depth > 0:
                    depth -= 1
                    buf.append("}")
                    advance(1)
                    continue
                if c == "`" and depth == 0:
                    break
                buf.append(c)
                advance(1)
            if i >= n:
                raise TypeScriptSyntaxError("unterminated template literal", start_line, start_col)
            advance(1)
            tokens.append(Token("template", "".join(buf), start_line, start_col))
            continue

        # number
        m = _NUM_RE.match(src, i)
        if m:
            tokens.append(Token("number", m.group(0), line, col))
            advance(len(m.group(0)))
            continue

        # identifier / keyword
        m = _IDENT_RE.match(src, i)
        if m:
            tokens.append(Token("ident", m.group(0), line, col))
            advance(len(m.group(0)))
            continue

        # operator
        for op in OPERATORS:
            if src.startswith(op, i):
                tokens.append(Token("op", op, line, col))
                advance(len(op))
                break
        else:
            raise TypeScriptSyntaxError(f"unexpected character {ch!r}", line, col)

    tokens.append(Token("eof", "", line, col))
    return tokens


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

TS_TO_GE_TYPE = {
    "number": "int",
    "string": "str",
    "boolean": "bool",
    "void": "None",
    "any": "any",
    "null": "None",
    "undefined": "None",
}

#: Intrinsic names that map to GE compiler intrinsics.
INTRINSICS = {
    "gePreamble": "ge_preamble",
    "geInline": "ge_inline",
    "geRaw": "ge_raw",
}


def map_type(ts_type: str) -> str:
    """Map a TypeScript type annotation onto a GE type name."""
    t = ts_type.strip()
    if t.endswith("[]"):
        return "list"
    if t.startswith("Array<") and t.endswith(">"):
        return "list"
    return TS_TO_GE_TYPE.get(t, t)


# ---------------------------------------------------------------------------
# Parser -> Python source
# ---------------------------------------------------------------------------

def _strip_outer_parens(text: str) -> str:
    """Drop a single pair of parens that wraps the whole expression.

    `(a + b)` -> `a + b`, but `(a) + (b)` is left alone because the first
    paren does not match the last one.
    """
    if len(text) < 2 or not text.startswith("(") or not text.endswith(")"):
        return text
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                # closes before the end -> the outer parens do not wrap it all
                return text if i != len(text) - 1 else text[1:-1]
    return text


def _py_str(value: str) -> str:
    """Emit a Python double-quoted string literal."""
    escaped = (value
               .replace("\\", "\\\\")
               .replace('"', '\\"')
               .replace("\n", "\\n")
               .replace("\t", "\\t"))
    return f'"{escaped}"'


def _py_raw_string(value: str) -> str:
    """Emit raw target-language code as a Python triple-quoted string.

    Used for gePreamble/geInline/geRaw payloads, which must reach the
    emitter byte-for-byte. Escapes are kept minimal so the code reads the
    same in the lowered form as it did in the source.
    """
    body = value.replace("\\", "\\\\")
    # a literal triple quote would terminate the string early
    body = body.replace('"""', '\\"\\"\\"')
    if body.endswith('"'):
        body += "\\"
    return f'"""{body}"""'

class Parser:
    """Recursive-descent parser producing Python source text."""

    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.pos = 0
        self.indent = 0
        self.lines: list[str] = []
        self._imported_types: set[str] = set()

    # -- token helpers ----------------------------------------------------
    @property
    def cur(self) -> Token:
        return self.toks[self.pos]

    def peek(self, offset: int = 1) -> Token:
        idx = min(self.pos + offset, len(self.toks) - 1)
        return self.toks[idx]

    def at_op(self, *ops: str) -> bool:
        return self.cur.kind == "op" and self.cur.value in ops

    def at_ident(self, *names: str) -> bool:
        return self.cur.kind == "ident" and self.cur.value in names

    def next(self) -> Token:
        tok = self.cur
        self.pos += 1
        return tok

    def expect_op(self, op: str) -> Token:
        if not self.at_op(op):
            raise TypeScriptSyntaxError(
                f"expected {op!r} but found {self.cur.value!r}",
                self.cur.line, self.cur.col)
        return self.next()

    def expect_ident(self, name: str | None = None) -> Token:
        if self.cur.kind != "ident":
            raise TypeScriptSyntaxError(
                f"expected identifier but found {self.cur.value!r}",
                self.cur.line, self.cur.col)
        if name is not None and self.cur.value != name:
            raise TypeScriptSyntaxError(
                f"expected {name!r} but found {self.cur.value!r}",
                self.cur.line, self.cur.col)
        return self.next()

    # -- output helpers ---------------------------------------------------
    def emit(self, text: str) -> None:
        self.lines.append("    " * self.indent + text)

    def emit_blank(self) -> None:
        self.lines.append("")

    # -- program ----------------------------------------------------------
    def parse_program(self) -> str:
        """Parse a whole file into Python source."""
        while self.cur.kind != "eof":
            self.parse_top_level()
        return "\n".join(self.lines) + "\n"

    def parse_top_level(self) -> None:
        tok = self.cur

        if self.at_op("@"):
            self.parse_decorated_function()
            return
        if self.at_ident("import"):
            self.parse_import()
            return
        if self.at_ident("export"):
            self.next()
            return
        if self.at_ident("interface", "type"):
            self.skip_declaration()
            return
        if self.at_ident("const", "let", "var"):
            self.parse_var_decl()
            return
        if self.at_ident("function"):
            self.parse_function()
            return
        if tok.kind == "op" and tok.value == ";":
            self.next()
            return

        # bare expression statement (e.g. a top-level gePreamble call)
        expr = self.parse_expression()
        self.expect_op(";")
        self.emit(expr)
        self.emit_blank()

    def parse_decorators(self) -> list[str]:
        """Collect `@cpp` / `@rust` / ... decorators and return their names."""
        names: list[str] = []
        while self.at_op("@"):
            self.next()
            names.append(self.expect_ident().value)
        return names

    def parse_decorated_function(self) -> None:
        """`@cpp export function f() {}` -> `@cpp` + `def f():`."""
        decorators = self.parse_decorators()
        if self.at_ident("export"):
            self.next()
        if not self.at_ident("function"):
            raise TypeScriptSyntaxError(
                "decorator must precede a function declaration",
                self.cur.line, self.cur.col)
        for d in decorators:
            self.emit(f"@{d}")
        self.parse_function()

    def parse_import(self) -> None:
        """`import { a, b } from "./mod";` -> `from mod import a, b`."""
        self.expect_ident("import")
        names: list[str] = []
        if self.at_op("{"):
            self.next()
            while not self.at_op("}"):
                names.append(self.expect_ident().value)
                if self.at_op(","):
                    self.next()
            self.expect_op("}")
        else:
            names.append(self.expect_ident().value)
        self.expect_ident("from")
        if self.cur.kind not in ("string", "template"):
            raise TypeScriptSyntaxError(
                "import path must be a string literal", self.cur.line, self.cur.col)
        module = self.next().value
        self.expect_op(";")
        # widget imports come from the GE widget library, not a project module
        if "widgets" in module:
            module = "pyeffic.widgets"
        else:
            # ./x -> x, ../y -> y, ../../a/b -> a.b
            # GE's module resolver searches the source dir and its parents,
            # so dropping the relative prefix is enough.
            while module.startswith("./") or module.startswith("../"):
                module = module[2:] if module.startswith("./") else module[3:]
            module = module.replace("/", ".")
        self.emit(f"from {module} import {', '.join(names)}")
        self.emit_blank()

    def skip_declaration(self) -> None:
        """Skip an interface/type declaration (types only, no code)."""
        depth = 0
        while self.cur.kind != "eof":
            if self.at_op("{"):
                depth += 1
            elif self.at_op("}"):
                depth -= 1
                if depth == 0:
                    self.next()
                    if self.at_op(";"):
                        self.next()
                    return
            elif self.at_op(";") and depth == 0:
                self.next()
                return
            self.next()

    # -- declarations -----------------------------------------------------
    def parse_type_annotation(self) -> str:
        """Parse `: Type` (with optional generic/array parts)."""
        self.expect_op(":")
        parts: list[str] = []
        angle = 0
        bracket = 0
        while self.cur.kind != "eof":
            if self.at_op("<"):
                angle += 1
            elif self.at_op(">"):
                angle -= 1
            elif self.at_op("["):
                bracket += 1
            elif self.at_op("]"):
                if bracket == 0:
                    break  # this ] closes an enclosing subscript, not the type
                bracket -= 1
            if angle == 0 and bracket == 0 and self.at_op(",", ")", "=", ";", "{"):
                break
            parts.append(self.next().value)
        return map_type("".join(parts))

    def parse_var_decl(self) -> None:
        """`let x: number = 1;` -> `x: int = 1`."""
        self.next()  # let / const / var
        name = self.expect_ident().value
        ge_type = self.parse_type_annotation() if self.at_op(":") else None
        if self.at_op("="):
            self.next()
            value = self.parse_expression()
        else:
            value = None
        self.expect_op(";")
        if ge_type:
            self.emit(f"{name}: {ge_type} = {value if value is not None else self._zero_for(ge_type)}")
        elif value is not None:
            self.emit(f"{name} = {value}")

    @staticmethod
    def _zero_for(ge_type: str) -> str:
        return {"int": "0", "float": "0.0", "bool": "False", "str": '""'}.get(ge_type, "None")

    def parse_function(self) -> None:
        """`function f(a: number): number { ... }` -> `def f(a: int) -> int:`."""
        self.expect_ident("function")
        name = self.expect_ident().value
        self.expect_op("(")
        params: list[str] = []
        while not self.at_op(")"):
            pname = self.expect_ident().value
            ptype = self.parse_type_annotation() if self.at_op(":") else "any"
            params.append(f"{pname}: {ptype}")
            if self.at_op(","):
                self.next()
        self.expect_op(")")
        ret = self.parse_type_annotation() if self.at_op(":") else "None"
        self.expect_op("{")

        sig = f"def {name}({', '.join(params)})"
        if ret != "None":
            sig += f" -> {ret}"
        self.emit(sig + ":")
        self.indent += 1
        self.parse_block()
        self.indent -= 1
        if not self.lines or self.lines[-1].strip() != "":
            self.emit_blank()

    # -- statements -------------------------------------------------------
    def parse_block(self) -> None:
        """Parse statements until the matching `}`."""
        while not self.at_op("}"):
            if self.cur.kind == "eof":
                raise TypeScriptSyntaxError("unexpected end of file in block", self.cur.line)
            self.parse_statement()
        self.expect_op("}")

    def parse_statement(self) -> None:
        if self.at_op(";"):
            self.next()
            return
        if self.at_ident("let", "const", "var"):
            self.parse_var_decl()
            return
        if self.at_ident("return"):
            self.next()
            if self.at_op(";"):
                self.next()
                self.emit("return")
            else:
                value = self.parse_expression()
                self.expect_op(";")
                self.emit(f"return {value}")
            return
        if self.at_ident("if"):
            self.parse_if()
            return
        if self.at_ident("while"):
            self.parse_while()
            return
        if self.at_ident("for"):
            self.parse_for()
            return
        if self.at_ident("break"):
            self.next()
            self.expect_op(";")
            self.emit("break")
            return
        if self.at_ident("continue"):
            self.next()
            self.expect_op(";")
            self.emit("continue")
            return
        if self.at_ident("function"):
            self.parse_function()
            return

        # expression statement (assignment or call)
        self.parse_expression_statement()

    def parse_expression_statement(self) -> None:
        start = self.pos
        expr = self.parse_expression()
        if self.at_op("=") or self.at_op("+=", "-=", "*=", "/=", "%="):
            op = self.next().value
            rhs = self.parse_expression()
            self.expect_op(";")
            if op == "=":
                self.emit(f"{expr} = {rhs}")
            else:
                self.emit(f"{expr} {op[0]}= {rhs}")
            return
        self.expect_op(";")
        # re-parse the call for print() rewriting
        self.pos = start
        expr = self.parse_expression()
        self.expect_op(";")
        self.emit(expr)

    def parse_if(self) -> None:
        self.expect_ident("if")
        self.expect_op("(")
        cond = self.parse_expression()
        self.expect_op(")")
        self.expect_op("{")
        self.emit(f"if {cond}:")
        self.indent += 1
        self.parse_block()
        self.indent -= 1

        while self.at_ident("else"):
            self.next()
            if self.at_ident("if"):
                self.next()
                self.expect_op("(")
                cond2 = self.parse_expression()
                self.expect_op(")")
                self.expect_op("{")
                self.emit(f"elif {cond2}:")
                self.indent += 1
                self.parse_block()
                self.indent -= 1
            else:
                self.expect_op("{")
                self.emit("else:")
                self.indent += 1
                self.parse_block()
                self.indent -= 1
                break

    def parse_while(self) -> None:
        self.expect_ident("while")
        self.expect_op("(")
        cond = self.parse_expression()
        self.expect_op(")")
        self.expect_op("{")
        self.emit(f"while {cond}:")
        self.indent += 1
        self.parse_block()
        self.indent -= 1

    def parse_for(self) -> None:
        """Classic C-style for -> while (keeps semantics simple and correct)."""
        self.expect_ident("for")
        self.expect_op("(")

        # init
        if self.at_ident("let", "const", "var"):
            self.next()
            name = self.expect_ident().value
            ge_type = self.parse_type_annotation() if self.at_op(":") else "int"
            self.expect_op("=")
            value = self.parse_expression()
            self.emit(f"{name}: {ge_type} = {value}")
        elif self.at_op(";"):
            pass
        else:
            expr = self.parse_expression()
            if self.at_op("="):
                self.next()
                rhs = self.parse_expression()
                self.emit(f"{expr} = {rhs}")
        self.expect_op(";")

        # condition
        cond = self.parse_expression()
        self.expect_op(";")

        # update
        update_parts: list[str] = []
        while not self.at_op(")"):
            target = self.parse_expression()
            if self.at_op("++"):
                self.next()
                update_parts.append(f"{target} = {target} + 1")
            elif self.at_op("--"):
                self.next()
                update_parts.append(f"{target} = {target} - 1")
            elif self.at_op("="):
                self.next()
                rhs = self.parse_expression()
                update_parts.append(f"{target} = {rhs}")
            elif self.at_op("+=", "-=", "*=", "/="):
                op = self.next().value
                rhs = self.parse_expression()
                update_parts.append(f"{target} {op[0]}= {rhs}")
            if self.at_op(","):
                self.next()
        self.expect_op(")")
        self.expect_op("{")

        self.emit(f"while {cond}:")
        self.indent += 1
        self.parse_block()
        for part in update_parts:
            self.emit(part)
        self.indent -= 1

    # -- expressions ------------------------------------------------------
    def parse_expression(self) -> str:
        return _strip_outer_parens(self.parse_binary(0))

    _PRECEDENCE = {
        "||": 1, "&&": 2, "|": 3, "&": 4,
        "==": 5, "!=": 5, "===": 5, "!==": 5,
        "<": 6, "<=": 6, ">": 6, ">=": 6,
        "+": 7, "-": 7,
        "*": 8, "/": 8, "%": 8,
        "**": 9,
    }

    _BINOP_MAP = {
        "===": "==", "!==": "!=",
        "&&": "and", "||": "or",
        "&": "and", "|": "or",
    }

    def parse_binary(self, min_prec: int) -> str:
        left = self.parse_unary()
        while True:
            if self.cur.kind != "op":
                break
            op = self.cur.value
            prec = self._PRECEDENCE.get(op)
            if prec is None or prec < min_prec:
                break
            self.next()
            right = self.parse_binary(prec + 1)
            py_op = self._BINOP_MAP.get(op, op)
            left = f"({left} {py_op} {right})"
        return left

    def parse_unary(self) -> str:
        if self.at_op("@"):
            # `@name(args)` — a call to a named .ge block. Lowered to a plain
            # call; the hybrid frontend rewrites it to the target function.
            self.next()
            name = self.expect_ident().value
            if not self.at_op("("):
                raise TypeScriptSyntaxError(
                    "expected '(' after @block reference", self.cur.line, self.cur.col)
            self.next()
            args: list[str] = []
            while not self.at_op(")"):
                args.append(self.parse_expression())
                if self.at_op(","):
                    self.next()
            self.expect_op(")")
            return f"{name}({', '.join(args)})"
        if self.at_op("!"):
            self.next()
            return f"(not {self.parse_unary()})"
        if self.at_op("-"):
            self.next()
            return f"(-{self.parse_unary()})"
        if self.at_op("+"):
            self.next()
            return self.parse_unary()
        return self.parse_postfix()

    def parse_postfix(self) -> str:
        expr = self.parse_primary()
        while True:
            if self.at_op("."):
                self.next()
                attr = self.expect_ident().value
                if attr == "length":
                    expr = f"len({expr})"
                elif attr == "push":
                    # handled as a call below
                    expr = f"{expr}.append"
                else:
                    expr = f"{expr}.{attr}"
            elif self.at_op("["):
                self.next()
                idx = self.parse_expression()
                self.expect_op("]")
                expr = f"{expr}[{idx}]"
            elif self.at_op("("):
                self.next()
                args: list[str] = []
                while not self.at_op(")"):
                    args.append(self.parse_expression())
                    if self.at_op(","):
                        self.next()
                self.expect_op(")")
                expr = self._apply_call(expr, args)
            else:
                break
        return expr

    def _apply_call(self, callee: str, args: list[str]) -> str:
        """Rewrite known TS APIs onto their GE/Python equivalents."""
        joined = ", ".join(args)
        if callee == "console.log":
            return f"print({joined})"
        if callee in INTRINSICS:
            return f"{INTRINSICS[callee]}({joined})"
        if callee == "Math.floor":
            return f"int({joined})"
        if callee == "Math.abs":
            return f"abs({joined})"
        if callee == "Math.max":
            return f"max({joined})"
        if callee == "Math.min":
            return f"min({joined})"
        if callee == "Math.pow":
            return f"pow({joined})"
        if callee == "Math.idiv":
            if len(args) == 2:
                return f"({args[0]} // {args[1]})"
            return f"int({joined})"
        if callee == "Number":
            return f"int({joined})"
        if callee == "String":
            return f"str({joined})"
        if callee.endswith(".push"):
            base = callee[: -len(".push")]
            return f"{base}.append({joined})"
        if callee.endswith(".toString"):
            base = callee[: -len(".toString")]
            return f"str({base})"
        return f"{callee}({joined})"

    def parse_primary(self) -> str:
        tok = self.cur

        if tok.kind == "number":
            self.next()
            return tok.value
        if tok.kind == "string":
            self.next()
            return _py_str(tok.value)
        if tok.kind == "template":
            self.next()
            return self._template_to_fstring(tok.value)

        if self.at_ident("true"):
            self.next()
            return "True"
        if self.at_ident("false"):
            self.next()
            return "False"
        if self.at_ident("null", "undefined"):
            self.next()
            return "None"

        if self.at_op("("):
            self.next()
            expr = self.parse_expression()
            self.expect_op(")")
            return f"({expr})"

        if self.at_op("["):
            self.next()
            items: list[str] = []
            while not self.at_op("]"):
                items.append(self.parse_expression())
                if self.at_op(","):
                    self.next()
            self.expect_op("]")
            return "[" + ", ".join(items) + "]"

        if self.at_ident("new"):
            self.next()
            ctor = self.expect_ident().value
            self.expect_op("(")
            args: list[str] = []
            while not self.at_op(")"):
                args.append(self.parse_expression())
                if self.at_op(","):
                    self.next()
            self.expect_op(")")
            return f"{ctor}({', '.join(args)})"

        if tok.kind == "ident":
            self.next()
            # intrinsics take raw target-language code; parse their arguments
            # specially so template literals survive verbatim
            if tok.value in INTRINSICS and self.at_op("("):
                return self._parse_intrinsic_call(tok.value)
            return tok.value

        raise TypeScriptSyntaxError(
            f"unexpected token {tok.value!r} in expression", tok.line, tok.col)

    def _parse_intrinsic_call(self, ts_name: str) -> str:
        """Parse gePreamble/geInline/geRaw arguments, keeping raw code intact."""
        self.expect_op("(")
        args: list[str] = []
        while not self.at_op(")"):
            if self.cur.kind == "template":
                raw = self.next().value
                args.append(_py_raw_string(raw))
            else:
                args.append(self.parse_expression())
            if self.at_op(","):
                self.next()
        self.expect_op(")")
        return f"{INTRINSICS[ts_name]}({', '.join(args)})"

    @staticmethod
    def _template_to_fstring(raw: str) -> str:
        """`Hi ${name}` -> f"Hi {name}".

        Backslash escapes are left alone: TS and Python agree on \\n, \\t,
        \\r, \\\\ and \\", so the body survives the round trip unchanged.
        Only unescaped double quotes need protecting, since the literal is
        emitted with double quotes.
        """
        out: list[str] = []
        i = 0
        n = len(raw)
        while i < n:
            c = raw[i]
            if c == "\\" and i + 1 < n:
                out.append(raw[i:i + 2])
                i += 2
                continue
            if c == '"':
                out.append('\\"')
                i += 1
                continue
            out.append(c)
            i += 1
        body = "".join(out)
        body = re.sub(r"\$\{([^}]*)\}", lambda m: "{" + m.group(1) + "}", body)
        return f'f"{body}"'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ts_to_python(source: str) -> str:
    """Lower TypeScript-flavoured GE source into equivalent Python source."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse_program()


def parse_ts_source_full(source: str) -> tuple[list[FuncUnit], list]:
    """Parse TypeScript-flavoured GE source into the shared IR.

    Returns (function_units, class_units) exactly like the Python frontend.
    """
    python_source = ts_to_python(source)
    try:
        return parse_source_full(python_source)
    except SyntaxError as exc:  # pragma: no cover - defensive
        raise TypeScriptSyntaxError(
            f"lowered source is not valid Python: {exc.msg}", exc.lineno or 0) from exc


def collect_ts_constants(source: str) -> dict:
    """Collect module-level constants from TypeScript-flavoured source."""
    return collect_constants(ts_to_python(source))


def collect_ts_preamble(source: str) -> dict:
    """Collect gePreamble(...) blocks from TypeScript-flavoured source."""
    return collect_preamble(ts_to_python(source))
