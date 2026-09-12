"""Identifier safety across target languages.

GE identifiers are Python names, so they may collide with a target
language's reserved words (`double` is a C++ type, `base` is a C# keyword,
`match` is a Rust keyword, ...).

Two kinds of identifier need different treatment:

* **Function names** can cross the C ABI (Rust calling a C++ function), so
  every side must agree on the symbol. These are renamed once in the shared
  IR by `rename_reserved_functions`, before any emitter runs.
* **Locals and parameters** never cross the ABI, so each backend escapes
  them in its own idiom (`@base` in C#, `r#match` in Rust, `base_` in C++
  which has no escape syntax).
"""
from __future__ import annotations

from .analyzer import FuncUnit

# ---------------------------------------------------------------------------
# Reserved word sets
# ---------------------------------------------------------------------------

CPP_RESERVED = {
    # keywords
    "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand", "bitor",
    "bool", "break", "case", "catch", "char", "char8_t", "char16_t",
    "char32_t", "class", "compl", "concept", "const", "consteval",
    "constexpr", "constinit", "const_cast", "continue", "co_await",
    "co_return", "co_yield", "decltype", "default", "delete", "do", "double",
    "dynamic_cast", "else", "enum", "explicit", "export", "extern", "false",
    "float", "for", "friend", "goto", "if", "inline", "int", "long",
    "mutable", "namespace", "new", "noexcept", "not", "not_eq", "nullptr",
    "operator", "or", "or_eq", "private", "protected", "public", "register",
    "reinterpret_cast", "requires", "return", "short", "signed", "sizeof",
    "static", "static_assert", "static_cast", "struct", "switch", "template",
    "this", "thread_local", "throw", "true", "try", "typedef", "typeid",
    "typename", "union", "unsigned", "using", "virtual", "void", "volatile",
    "wchar_t", "while", "xor", "xor_eq",
    # core library type names: a function with one of these names would
    # collide with the type itself
    "std", "string", "vector", "map", "tuple", "pair", "set",
}

RUST_RESERVED = {
    "as", "break", "const", "continue", "crate", "dyn", "else", "enum",
    "extern", "false", "fn", "for", "if", "impl", "in", "let", "loop",
    "match", "mod", "move", "mut", "pub", "ref", "return", "self", "Self",
    "static", "struct", "super", "trait", "true", "type", "unsafe", "use",
    "where", "while", "async", "await", "abstract", "become", "box", "do",
    "final", "macro", "override", "priv", "try", "typeof", "unsized",
    "virtual", "yield",
    # core prelude type names
    "String", "Vec", "Box", "Option", "Result", "Some", "None", "Ok", "Err",
}

CSHARP_RESERVED = {
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch",
    "char", "checked", "class", "const", "continue", "decimal", "default",
    "delegate", "do", "double", "else", "enum", "event", "explicit",
    "extern", "false", "finally", "fixed", "float", "for", "foreach", "goto",
    "if", "implicit", "in", "int", "interface", "internal", "is", "lock",
    "long", "namespace", "new", "null", "object", "operator", "out",
    "override", "params", "private", "protected", "public", "readonly",
    "ref", "return", "sbyte", "sealed", "short", "sizeof", "stackalloc",
    "static", "string", "struct", "switch", "this", "throw", "true", "try",
    "typeof", "uint", "ulong", "unchecked", "unsafe", "ushort", "using",
    "virtual", "void", "volatile", "while",
    # core library type names
    "Console", "Math", "Convert", "String", "Object",
}

GO_RESERVED = {
    "break", "case", "chan", "const", "continue", "default", "defer",
    "else", "fallthrough", "for", "func", "go", "goto", "if", "import",
    "interface", "map", "package", "range", "return", "select", "struct",
    "switch", "type", "var",
    # core prelude type names
    "int", "int64", "float64", "string", "bool", "byte", "rune",
}

KOTLIN_RESERVED = {
    "as", "break", "class", "continue", "do", "else", "false", "for", "fun",
    "if", "in", "interface", "is", "null", "object", "package", "return",
    "super", "this", "throw", "true", "try", "typealias", "typeof", "val",
    "var", "when", "while",
    # core prelude type names
    "Int", "Long", "Double", "String", "Boolean", "List", "Array", "Unit",
}

ZIG_RESERVED = {
    "align", "allowzero", "and", "anyframe", "anytype", "asm", "async",
    "await", "break", "catch", "comptime", "const", "continue", "defer",
    "else", "enum", "errdefer", "error", "export", "extern", "fn", "for",
    "if", "inline", "noalias", "nosuspend", "opaque", "or", "orelse",
    "packed", "pub", "resume", "return", "linksection", "struct", "suspend",
    "switch", "test", "threadlocal", "try", "union", "unreachable",
    "usingnamespace", "var", "volatile", "while",
    # core prelude type names
    "i64", "f64", "bool", "u8", "usize", "std",
}

#: backend name -> reserved words
RESERVED: dict[str, set[str]] = {
    "cpp": CPP_RESERVED,
    "rust": RUST_RESERVED,
    "csharp": CSHARP_RESERVED,
    "go": GO_RESERVED,
    "kotlin": KOTLIN_RESERVED,
    "zig": ZIG_RESERVED,
}

#: how each backend escapes a local/parameter name
ESCAPE_STYLE = {
    "csharp": "prefix_at",   # @base
    "rust": "prefix_r",      # r#match
    "cpp": "suffix",         # base_  (no escape syntax in C++)
    "go": "suffix",
    "kotlin": "suffix",
    "zig": "suffix",
}


def is_reserved(name: str, backend) -> bool:
    """True if `name` is reserved by the given backend (or any of several)."""
    if isinstance(backend, str):
        return name in RESERVED.get(backend, set())
    return any(name in RESERVED.get(b, set()) for b in backend)


def escape_local(name: str, backend: str) -> str:
    """Escape a local/parameter name in the backend's idiom."""
    if not is_reserved(name, backend):
        return name
    style = ESCAPE_STYLE.get(backend, "suffix")
    if style == "prefix_at":
        return "@" + name
    if style == "prefix_r":
        return "r#" + name
    return name + "_"


def safe_function_name(name: str, backends) -> str:
    """A function name that is safe in every one of `backends`.

    Function symbols can cross the C ABI, so the rename has to be decided
    once, for all backends at the same time.
    """
    for backend in backends:
        if is_reserved(name, backend):
            return name + "_"
    return name


# ---------------------------------------------------------------------------
# IR-level rename
# ---------------------------------------------------------------------------

def rename_reserved_functions(units: list[FuncUnit], backends) -> dict[str, str]:
    """Rename functions whose names collide with a target keyword.

    Applies the rename to definitions *and* call sites across every unit, so
    the whole program — including cross-backend `extern "C"` declarations —
    agrees on one symbol. Returns the {old: new} map for reporting.
    """
    import ast

    # `main` is the entry point: emitters resolve it by name, so it is never
    # renamed. (It is not in the reserved sets either.)
    collisions = {u.name for u in units
                  if u.name != "main" and is_reserved(u.name, backends)}
    if not collisions:
        return {}
    mapping = {name: safe_function_name(name, backends) for name in collisions}

    # rename definitions
    for u in units:
        if u.name in mapping:
            u.name = mapping[u.name]

    # rename call sites and any reference
    class _Renamer(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:
            if node.id in mapping:
                node.id = mapping[node.id]
            return node

        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
            if node.name in mapping:
                node.name = mapping[node.name]
            self.generic_visit(node)
            return node

    renamer = _Renamer()
    for u in units:
        body = u.body
        if body is None:
            continue
        # FuncUnit.body is the function node in some paths and the statement
        # list in others; normalise before rewriting.
        if isinstance(body, ast.AST):
            u.body = renamer.visit(body)
        elif isinstance(body, list):
            u.body = [renamer.visit(stmt) for stmt in body]

    return mapping
