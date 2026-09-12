"""Hybrid GE frontend — one `.ge` file, both flavours.

A `.ge` file may mix Python-flavoured and TypeScript-flavoured definitions.
The compiler splits the file into top-level chunks, decides each chunk's
flavour from its syntax, lowers the TypeScript chunks, and concatenates
everything into one Python source for the shared IR.

    main.ge
      |
      +-- def compute(x: int) -> int:      <- python chunk, kept as-is
      |       return x * 2
      |
      +-- export function render(): number {   <- typescript chunk
      |       return compute(3);                    lowered to python
      |   }
      |
      v
    one python source -> shared IR -> every backend

Chunk classification (first significant token of the chunk):

    python        def / async def / from X import / import X / class
                  ge_preamble( / ge_inline( / ge_raw(
                  NAME: type = value
    typescript    function / export ... / let / const / var
                  interface / type / import { .. } from ".."
                  gePreamble( / geInline( / geRaw(

Explicit override, for the rare ambiguous case: put a marker comment on the
line above the chunk.

    # ge:typescript
    const SCALE: number = 2;

    // ge:python
    def helper(x: int) -> int:
        return x

Anything the classifier gets wrong can be pinned this way, so auto-detection
is always escapable.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .typescript import TypeScriptSyntaxError, ts_to_python

# ---------------------------------------------------------------------------
# Line scanning (shared by the splitter)
# ---------------------------------------------------------------------------

#: string/comment states the scanner can be in at the end of a line
_NORMAL = "normal"
_PY_SINGLE = "py_single"
_PY_DOUBLE = "py_double"
_PY_TRIPLE_SINGLE = "py_triple_single"
_PY_TRIPLE_DOUBLE = "py_triple_double"
_TS_SINGLE = "ts_single"
_TS_DOUBLE = "ts_double"
_TS_TEMPLATE = "ts_template"
_BLOCK_COMMENT = "block_comment"


@dataclass
class LineScan:
    """What a single line contributes at top level."""
    state: str
    braces: int      # { minus }
    brackets: int    # ( [ minus ) ]
    colon_at_depth0: int  # index of the last top-level ':' or -1


def _scan_line(line: str, state: str) -> LineScan:
    """Walk one line, tracking string state and top-level bracket depth."""
    braces = 0
    brackets = 0
    last_colon = -1
    depth = 0
    i = 0
    n = len(line)

    while i < n:
        c = line[i]
        nxt = line[i + 1] if i + 1 < n else ""

        if state == _BLOCK_COMMENT:
            if c == "*" and nxt == "/":
                state = _NORMAL
                i += 2
                continue
            i += 1
            continue

        if state == _PY_TRIPLE_DOUBLE:
            if line.startswith('"""', i):
                state = _NORMAL
                i += 3
                continue
            i += 1
            continue
        if state == _PY_TRIPLE_SINGLE:
            if line.startswith("'''", i):
                state = _NORMAL
                i += 3
                continue
            i += 1
            continue

        if state in (_PY_SINGLE, _TS_SINGLE):
            if c == "\\" and nxt:
                i += 2
                continue
            if c == "'":
                state = _NORMAL
            i += 1
            continue
        if state in (_PY_DOUBLE, _TS_DOUBLE):
            if c == "\\" and nxt:
                i += 2
                continue
            if c == '"':
                state = _NORMAL
            i += 1
            continue
        if state == _TS_TEMPLATE:
            if c == "\\" and nxt:
                i += 2
                continue
            if c == "`":
                state = _NORMAL
            i += 1
            continue

        # ---- normal state ----
        if c == "#":
            break  # python comment runs to end of line
        if c == "/" and nxt == "/":
            break  # ts line comment
        if c == "/" and nxt == "*":
            state = _BLOCK_COMMENT
            i += 2
            continue
        if line.startswith('"""', i):
            state = _PY_TRIPLE_DOUBLE
            i += 3
            continue
        if line.startswith("'''", i):
            state = _PY_TRIPLE_SINGLE
            i += 3
            continue
        if c == '"':
            state = _PY_DOUBLE
            i += 1
            continue
        if c == "'":
            state = _PY_SINGLE
            i += 1
            continue
        if c == "`":
            state = _TS_TEMPLATE
            i += 1
            continue
        if c == "{":
            braces += 1
            depth += 1
            i += 1
            continue
        if c == "}":
            braces -= 1
            depth -= 1
            i += 1
            continue
        if c in "([":
            brackets += 1
            depth += 1
            i += 1
            continue
        if c in ")]":
            brackets -= 1
            depth -= 1
            i += 1
            continue
        if c == ":" and depth == 0:
            last_colon = i
            i += 1
            continue
        i += 1

    return LineScan(state, braces, brackets, last_colon)


# ---------------------------------------------------------------------------
# Chunk model
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    flavour: str          # "python" | "typescript"
    text: str
    start_line: int
    explicit: bool = False
    #: name from a `<name> ... </name>` block, or None for a bare chunk
    block_name: str | None = None


# ---------------------------------------------------------------------------
# Named blocks: <name> ... </name>
# ---------------------------------------------------------------------------
#
# A block gives a chunk a name and makes it callable from anywhere else in
# the file (or from another file that imports it):
#
#     <add>
#     def add(a: int, b: int) -> int:
#         return a + b
#     </add>
#
#     <render:typescript>
#     export function render(x: number): number {
#         return @add(x, 1);      // @name(...) calls the block
#     }
#     </render>
#
# The language is detected from the content, or pinned with `:python` /
# `:typescript` (aliases `:py` / `:ts`).

_BLOCK_OPEN_RE = re.compile(
    r"^[ \t]*<(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)(?::(?P<lang>[A-Za-z]+))?>[ \t]*$")
_BLOCK_CLOSE_RE = re.compile(
    r"^[ \t]*</(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)>[ \t]*$")

#: a call to a named block: `@name(...)`
_BLOCK_CALL_RE = re.compile(r"@(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)\s*\(")

_LANG_ALIASES = {
    "python": "python", "py": "python",
    "typescript": "typescript", "ts": "typescript",
}


def _rewrite_block_calls(text: str, resolve: dict[str, str]) -> str:
    """Turn `@block(...)` into `target_function(...)`.

    Only rewrites outside strings and comments, so a literal `@name(` inside
    a string is left alone.
    """
    out_lines: list[str] = []
    state = _NORMAL
    for line in text.splitlines(keepends=True):
        # fast path: nothing to rewrite on this line
        if "@" not in line:
            out_lines.append(line)
            state = _scan_line(line, state).state
            continue

        result: list[str] = []
        i = 0
        n = len(line)
        line_state = state
        while i < n:
            c = line[i]
            if line_state != _NORMAL:
                # inside a string/comment: copy verbatim and let the scanner
                # advance the state by re-scanning this line's remainder
                rest = line[i:]
                scan = _scan_line(rest, line_state)
                result.append(rest)
                line_state = scan.state
                i = n
                break
            if c == "#":
                result.append(line[i:])
                i = n
                break
            if c == "/" and i + 1 < n and line[i + 1] == "/":
                result.append(line[i:])
                i = n
                break
            if c == "@":
                m = _BLOCK_CALL_RE.match(line, i)
                if m:
                    target = resolve.get(m.group("name"), m.group("name"))
                    result.append(target + "(")
                    i = m.end()
                    continue
            # advance one char, tracking entry into strings
            result.append(c)
            if c in "\"'`":
                # let the scanner take over from here
                rest = line[i + 1:]
                scan = _scan_line(c + rest, _NORMAL)
                line_state = scan.state
                result.append(rest)
                i = n
                break
            i += 1
        out_lines.append("".join(result))
        state = line_state
    return "".join(out_lines)


_PY_STARTS = (
    "def ", "async def ", "class ",
    "from ", "import ",
    "ge_preamble(", "ge_inline(", "ge_raw(",
)
_TS_STARTS = (
    "function ", "export ", "let ", "const ", "var ",
    "interface ", "type ", "declare ", "abstract class ",
    "gePreamble(", "geInline(", "geRaw(",
)

_MARKER_RE = re.compile(
    r"^\s*(?:#|//)\s*ge:\s*(python|py|typescript|ts)\s*$", re.IGNORECASE)

#: `def name(params) -> ret:` — a python-style signature
_PY_DEF_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:async[ \t]+)?def[ \t]+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"[ \t]*\((?P<params>.*)\)[ \t]*(?:->[ \t]*(?P<ret>[^:\n]+?))?[ \t]*:[ \t]*$",
    re.DOTALL)


def _py_header_to_ts(header: str) -> str | None:
    """Rewrite `def f(a: int) -> int:` as `function f(a: int): int {`.

    Lets a function use the compact Python signature with a braced body —
    both spellings are accepted in a .ge file.
    """
    stripped = header.rstrip()
    m = _PY_DEF_RE.match(stripped)
    if not m:
        return None
    ret = (m.group("ret") or "").strip()
    ret_part = f": {ret}" if ret and ret != "None" else ""
    return (f"{m.group('indent')}function {m.group('name')}"
            f"({m.group('params').strip()}){ret_part} {{")


#: statement-level TypeScript markers inside a function body
_TS_BODY_RE = re.compile(
    r"^\s*(?:if|while|for|else|switch)\b[^\n]*\)\s*\{|"
    r"^\s*(?:let|const|var)\s+[A-Za-z_]|"
    r"^\s*\}[;,]?\s*$|"
    r";\s*$",
    re.MULTILINE,
)
#: statement-level Python markers inside a function body
_PY_BODY_RE = re.compile(
    r"^\s*(?:if|elif|else|while|for|try|except|finally|with)\b[^\n]*:\s*$|"
    r"^\s*(?:return|pass|break|continue|raise|yield|del|assert)\b[^\n;]*$",
    re.MULTILINE,
)


def _body_flavour(body: str) -> str:
    """Score a function body as TypeScript or Python.

    A function may be written with a Python-style signature but a braced
    body; the body's syntax is the tie-breaker.
    """
    ts_hits = len(_TS_BODY_RE.findall(body))
    py_hits = len(_PY_BODY_RE.findall(body))
    return "typescript" if ts_hits > py_hits else "python"


def _marker_flavour(line: str) -> str | None:
    m = _MARKER_RE.match(line)
    if not m:
        return None
    return "python" if m.group(1).lower() in ("python", "py") else "typescript"


def _is_import_typescript(line: str) -> bool:
    """`import { a } from "./m"` and `import x from "m"` are TS."""
    if not line.lstrip().startswith("import"):
        return False
    return bool(re.search(r"""\bfrom\s+['"]""", line))


def _classify(first: str, header_text: str) -> str:
    """Decide a chunk's flavour from its first significant line."""
    s = first.lstrip()
    if s.startswith("import"):
        return "typescript" if _is_import_typescript(s) else "python"
    for kw in _TS_STARTS:
        if s.startswith(kw):
            return "typescript"
    for kw in _PY_STARTS:
        if s.startswith(kw):
            return "python"
    # `NAME: type = value` is python; `NAME: type;` is ambiguous but rare
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:\s*[^=]+=\s*", s) and ";" not in s:
        return "python"
    # `NAME = value` is python
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", s) and ";" not in s:
        return "python"
    # a bare intrinsic or expression statement: fall back on the header text
    if "gePreamble(" in header_text or "geInline(" in header_text:
        return "typescript"
    return "python"


# ---------------------------------------------------------------------------
# Splitter
# ---------------------------------------------------------------------------

def split_chunks(source: str) -> list[Chunk]:
    """Split a mixed .ge source into classified top-level chunks."""
    lines = source.splitlines(keepends=True)
    chunks: list[Chunk] = []
    i = 0
    n = len(lines)
    pending_marker: str | None = None
    pending_start = 0

    def indent_of(text: str) -> int:
        return len(text) - len(text.lstrip(" \t"))

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # blank line: nothing to attach
        if not stripped:
            i += 1
            continue

        # explicit flavour marker
        marker = _marker_flavour(line)
        if marker is not None:
            pending_marker = marker
            i += 1
            continue

        # named block: <name> ... </name>
        block_open = _BLOCK_OPEN_RE.match(line)
        if block_open:
            block_name = block_open.group("name")
            lang = (block_open.group("lang") or "").lower()
            body_start = i + 1
            k = body_start
            close_idx = -1
            while k < n:
                close = _BLOCK_CLOSE_RE.match(lines[k])
                if close:
                    if close.group("name") != block_name:
                        raise TypeScriptSyntaxError(
                            f"block <{block_name}> closed by </{close.group('name')}>",
                            k + 1)
                    close_idx = k
                    break
                k += 1
            if close_idx < 0:
                raise TypeScriptSyntaxError(
                    f"block <{block_name}> is never closed", i + 1)

            inner = "".join(lines[body_start:close_idx])
            if lang in _LANG_ALIASES:
                flavour = _LANG_ALIASES[lang]
            else:
                # auto-detect from the block's own content
                inner_lines = [ln for ln in lines[body_start:close_idx]
                               if ln.strip()]
                if inner_lines:
                    first_inner = inner_lines[0]
                    head = "".join(inner_lines[:4])
                    flavour = _classify(first_inner, head)
                else:
                    flavour = "python"

            if flavour == "python" and _body_flavour(inner) == "typescript":
                # a python-style signature with a braced body inside a block
                sig_lines = [ln for ln in inner.splitlines(keepends=True)
                             if ln.strip()]
                if sig_lines and _py_header_to_ts(sig_lines[0].rstrip()):
                    ts_header = _py_header_to_ts(sig_lines[0].rstrip())
                    rest = "".join(sig_lines[1:])
                    inner = ts_header + "\n" + rest.rstrip() + "\n}\n"
                    flavour = "typescript"

            chunks.append(Chunk(flavour, inner, body_start + 1, True, block_name))
            i = close_idx + 1
            pending_start = i
            continue

        # comment-only lines attach to the next chunk
        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("/*"):
            if not chunks or chunks[-1].text.endswith("\n"):
                pending_start = pending_start or i
            i += 1
            continue

        # decorators attach to the next chunk
        decorators: list[str] = []
        while i < n and lines[i].lstrip().startswith("@"):
            decorators.append(lines[i])
            i += 1
        if i >= n:
            break

        start = pending_start if decorators else i
        first = lines[i]

        # accumulate the header (signature) lines
        header_parts = list(decorators)
        header_state = _NORMAL
        header_colon = -1
        braces_total = 0
        brackets_total = 0
        j = i

        # header ends at a top-level ':' (python), at '{' (typescript block),
        # or at the end of the first complete line (imports, docstrings,
        # assignments). Only an open bracket, an unterminated string, or a
        # signature without its colon yet keeps the header going.
        while j < n:
            scan = _scan_line(lines[j], header_state)
            header_state = scan.state
            header_parts.append(lines[j])
            braces_total += scan.braces
            brackets_total += scan.brackets
            header_colon = scan.colon_at_depth0 if scan.colon_at_depth0 >= 0 else header_colon
            if scan.braces > 0 and brackets_total == 0:
                break  # typescript body opened
            if header_colon >= 0 and brackets_total == 0 and scan.braces == 0:
                break  # python header complete
            if header_colon < 0 and ";" in lines[j] and scan.braces == 0 and brackets_total == 0:
                break  # typescript statement (var decl / import)
            if header_state != _NORMAL or brackets_total > 0:
                j += 1
                continue  # still inside a string or an open bracket
            break  # complete single-line statement

        header_text = "".join(header_parts)
        flavour = pending_marker or _classify(first, header_text)
        explicit = pending_marker is not None
        pending_marker = None

        header_indent = indent_of(first)

        if flavour == "python":
            # A python-style header followed by a `{` body is a braced
            # function: rewrite the header to TS and let the TS parser
            # handle the whole chunk.
            k = j + 1
            while k < n and not lines[k].strip():
                k += 1
            if k < n and lines[k].lstrip().startswith("{"):
                # decorators are re-emitted separately, so convert only the
                # signature part of the accumulated header
                signature = "".join(header_parts[len(decorators):])
                ts_header = _py_header_to_ts(signature)
                if ts_header is not None:
                    prefix = "".join(decorators)
                    text = prefix + ts_header + "\n" + "".join(lines[j + 1:k])
                    depth = 0
                    m = k
                    while m < n:
                        scan = _scan_line(lines[m], _NORMAL)
                        depth += scan.braces
                        m += 1
                        if depth <= 0:
                            break
                    text += "".join(lines[k:m])
                    if m < n and lines[m].strip() == ";":
                        m += 1
                    chunks.append(Chunk("typescript", text, start + 1, True))
                    i = m
                    pending_start = i
                    continue

            # consume the indented body
            k = j + 1
            while k < n:
                body_line = lines[k]
                if not body_line.strip():
                    k += 1
                    continue
                if indent_of(body_line) > header_indent:
                    k += 1
                    continue
                break
            body = "".join(lines[j + 1:k])

            # A python-style signature may carry a braced (TypeScript) body.
            # The body's syntax decides; if it is TS, rewrite the signature
            # and wrap the body in braces so the TS parser handles it.
            if _body_flavour(body) == "typescript":
                signature = "".join(header_parts[len(decorators):])
                ts_header = _py_header_to_ts(signature)
                if ts_header is not None:
                    text = ("".join(decorators) + ts_header + "\n"
                            + body.rstrip() + "\n}\n")
                    chunks.append(Chunk("typescript", text, start + 1, True))
                    i = k
                    pending_start = i
                    continue

            text = "".join(lines[start:k])
            chunks.append(Chunk("python", text, start + 1, explicit))
            i = k
        else:
            # consume until braces balance (typescript block) or the ';' ends it
            if braces_total > 0:
                depth = braces_total
                k = j + 1
                while k < n and depth > 0:
                    scan = _scan_line(lines[k], _NORMAL)
                    depth += scan.braces
                    k += 1
                # a trailing semicolon after the closing brace
                if k < n and lines[k].strip() == ";":
                    k += 1
            else:
                k = j + 1
            text = "".join(lines[start:k])
            chunks.append(Chunk("typescript", text, start + 1, explicit))
            i = k

        pending_start = i

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _lower_chunk(chunk: Chunk) -> str:
    """Lower one chunk to Python source."""
    if chunk.flavour == "python":
        return chunk.text if chunk.text.endswith("\n") else chunk.text + "\n"
    try:
        return ts_to_python(chunk.text)
    except TypeScriptSyntaxError as exc:
        where = (f"in block <{chunk.block_name}>"
                 if chunk.block_name else "in TypeScript chunk")
        raise TypeScriptSyntaxError(
            f"{where} starting at line {chunk.start_line}: {exc}",
            chunk.start_line) from exc


def _function_names(python_source: str) -> list[str]:
    """Top-level function names defined by a lowered chunk."""
    try:
        tree = ast.parse(python_source)
    except SyntaxError:
        return []
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]


def hybrid_to_python(source: str) -> str:
    """Lower a mixed .ge source into one Python source.

    Two passes: lower every chunk once to learn which function each block
    defines, then rewrite `@block(...)` in the *raw* chunk text and lower
    again. Rewriting the raw text matters because the TypeScript parser
    already accepts `@name(...)` as a call and would drop the marker before
    the block map could be applied.
    """
    chunks = split_chunks(source)
    lowered = [_lower_chunk(c) for c in chunks]

    # block name -> function name
    resolve: dict[str, str] = {}
    for chunk, py in zip(chunks, lowered):
        if not chunk.block_name:
            continue
        names = _function_names(py)
        if chunk.block_name in names:
            resolve[chunk.block_name] = chunk.block_name
        elif len(names) == 1:
            resolve[chunk.block_name] = names[0]
        elif names:
            # several functions: the block name addresses the first one
            resolve[chunk.block_name] = names[0]

    out: list[str] = []
    for chunk, py in zip(chunks, lowered):
        if "@" in chunk.text:
            raw = _rewrite_block_calls(chunk.text, resolve)
            if raw != chunk.text:
                py = _lower_chunk(Chunk(chunk.flavour, raw, chunk.start_line,
                                        chunk.explicit, chunk.block_name))
        out.append(py)
    return "\n".join(out)


def parse_hybrid_source_full(source: str) -> tuple[list, list]:
    """Parse a mixed .ge source into the shared IR."""
    from ..analyzer import parse_source_full
    return parse_source_full(hybrid_to_python(source))


def collect_hybrid_constants(source: str) -> dict:
    from ..analyzer import collect_constants
    return collect_constants(hybrid_to_python(source))


def collect_hybrid_preamble(source: str) -> dict:
    from ..analyzer import collect_preamble
    return collect_preamble(hybrid_to_python(source))


def chunk_flavours(source: str) -> list[tuple[int, str]]:
    """Return (line, flavour) for each chunk — used by `ge analyze` output."""
    return [(c.start_line, c.flavour) for c in split_chunks(source)]
