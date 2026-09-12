"""Rust backend spec + program assembly."""
from __future__ import annotations

import ast

from .base import Emitter, Spec
from ..analyzer import FuncUnit

SPEC = Spec(
    name="rust",
    types={"int": "i64", "float": "f64", "bool": "bool", "str": "String", "None": "()"},
    list_type="Vec<{T}>",
    list_param_type="&[i64]",
    list_elem_type="i64",
    list_sort="{x}.sort()",
    list_reverse="{x}.reverse()",
    str_split="{x}.split({sep}.as_str()).map(|s| s.to_string()).collect::<Vec<String>>()",
    str_join="{x}.join({sep}.as_str())",
    list_slice="{x}[({start}) as usize..({stop}) as usize].to_vec()",
    list_copy="{x}.clone()",
    borrow_list_arg=True,
    range_call="({lo}..{hi})",
    range_step_call="({lo}..{hi}).step_by({step} as usize)",
    len_call="{x}.len() as i64",
    list_len="{x}.len() as i64",
    print_int='println!("{{}}", {v})',
    print_float='println!("{{}}", {v})',
    print_str='println!("{{}}", {v})',
    print_bool='println!("{{}}", if {v} {{ "True" }} else {{ "False" }})',
    print_generic='println!("{{:?}}", {v})',
    print_list='println!("{{:?}}", {v})',
    int_cast="{x} as i64",
    float_cast="{x} as f64",
    float_div="({l} as f64 / {r} as f64)",
    floor_div="({l} / {r})",
    sum_call="{it}.iter().sum::<i64>()",
    abs_int="i64::abs({x})",
    abs_float="{x}.abs()",
    min2_call="std::cmp::min({a}, {b})",
    max2_call="std::cmp::max({a}, {b})",
    min_call="{it}.iter().min().unwrap()",
    max_call="{it}.iter().max().unwrap()",
    pow_call="{l}.pow({r} as u32)",
    pow_int="i64::pow({l}, {r} as u32)",
    pow_float="f64::powf({l}, {r})",
    append_call="{x}.push({v})",
    index_call="{x}[{i} as usize]",
    comment="//",
    fn_template="{sig} {{\n{body}\n}}",
    main_template="",
    ffi_prefix="#[no_mangle]\npub extern \"C\" ",
    # `String + &String` is not Add in Rust and `a + b` moves `a`, so a
    # format! is used instead — always correct, and it accepts &str too.
    str_concat="format!(\"{{}}{{}}\", {l}, {r})",
    str_len="{x}.len() as i64",
    str_index="{x}.as_bytes()[{i} as usize] as i64",
    str_slice="{x}[{start}..{end}].to_string()",
    str_slice_start="{x}[{start}..].to_string()",
    str_slice_end="{x}[..{end}].to_string()",
    list_concat="{{ let mut t = {l}; t.extend({r}.iter()); t }}",
    condition_parens=False,
    foreach_template="for {var} in {iter}.iter()",
    try_template="// try/except not natively supported in Rust\n// {body}\n// {handler}",
    struct_template="#[derive(Clone)]\nstruct {name} {{\n{fields}\n}}",
    struct_field_template="    {type}: {name},",
    struct_new_template="fn {name}_new({params}) -> {name} {{\n{body}\n}}",
    dict_type="std::collections::HashMap<String, {V}>",
    set_type="std::collections::HashSet<i64>",
    dict_get="{d}.get(&{k}).copied().unwrap_or(0)",
    dict_set="{d}.insert({k}, {v})",
    dict_keys="{x}.keys().cloned().collect::<Vec<String>>()",
    foreach_dict_template="for {var} in {iter}",
    dict_contains="{d}.contains_key(&{k})",
    tuple_type="({T}, {T})",
    tuple_get="{t}.{i}",
)


def _entry_unit(units: list[FuncUnit], entry: str | None) -> FuncUnit:
    if entry:
        for u in units:
            if u.name == entry:
                return u
    for u in units:
        if u.name == "main":
            return u
    return units[0]


def _emit_structs(classes: list) -> str:
    """Emit Rust struct definitions and constructors for ClassUnits."""
    out: list[str] = []
    for cls in classes:
        # struct definition
        fields_str = ""
        for fname, ftype in cls.fields:
            nt = SPEC.types.get(ftype, SPEC.types.get("float"))
            if ftype == "list":
                nt = SPEC.list_type.format(T=SPEC.list_elem_type)
            elif ftype not in SPEC.types:
                nt = f64_default = SPEC.types.get("float")
            fields_str += f"    {fname}: {nt},\n"
        out.append(f"#[derive(Clone)]\nstruct {cls.name} {{\n{fields_str}}}\n")
        # constructor: ClassName_new(params) -> ClassName
        if cls.constructor_params:
            params_str = ", ".join(
                f"{pname}: {SPEC.types.get(ptype, SPEC.types['float'])}"
                for pname, ptype in cls.constructor_params
            )
            init_lines = []
            for fname, ftype in cls.fields:
                init_lines.append(f"            {fname}: {fname},")
            body = "\n".join(init_lines)
            out.append(f"fn {cls.name}_new({params_str}) -> {cls.name} {{\n"
                       f"    {cls.name} {{\n{body}\n    }}\n}}\n")
        else:
            field_inits = "\n".join(
                f"            {fname}: Default::default()," for fname, _ in cls.fields
            )
            out.append(f"fn {cls.name}_new() -> {cls.name} {{\n"
                       f"    {cls.name} {{\n{field_inits}\n    }}\n}}\n")
    return "\n".join(out)


class RustEmitter(Emitter):
    # Rust keywords that are legal GE identifiers; r# escapes them.
    _KEYWORDS = {"as", "break", "const", "continue", "crate", "dyn", "else",
                 "enum", "extern", "false", "fn", "for", "if", "impl", "in",
                 "let", "loop", "match", "mod", "move", "mut", "pub", "ref",
                 "return", "self", "Self", "static", "struct", "super",
                 "trait", "true", "type", "unsafe", "use", "where", "while",
                 "async", "await", "abstract", "become", "box", "do",
                 "final", "macro", "override", "priv", "try", "typeof",
                 "unsized", "virtual", "yield"}

    def _ident(self, name: str) -> str:
        """Escape Rust keywords with the r# form."""
        if name == "self":
            return "_self"
        from ..idents import escape_local
        return escape_local(name, "rust")
    """Rust-specific emitter that handles try/except using catch_unwind."""

    def _try_stmt(self, node, ind):
        """Lower try/except to std::panic::catch_unwind."""
        # Check if try body contains a return statement
        has_return = any(isinstance(s, ast.Return) for s in ast.walk(ast.Module(body=node.body, type_ignores=[])))
        if has_return:
            # Can't use catch_unwind with return inside closure
            # Fall back to direct emission with a comment
            self.lines.append(f"{ind}// try/except: body contains return, cannot use catch_unwind")
            for s in node.body:
                self.stmt(s)
            if node.handlers:
                self.lines.append(f"{ind}// except handler (not emitted — return in try body):")
                for s in node.handlers[0].body:
                    save = self.lines
                    self.lines = []
                    self.stmt(s)
                    for line in self.lines:
                        save.append(f"{ind}// {line.strip()}")
                    self.lines = save
            if node.finalbody:
                self.lines.append(f"{ind}// finally:")
                for s in node.finalbody:
                    self.stmt(s)
            return

        # Use catch_unwind to catch panics
        self.lines.append(f"{ind}let __result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        self.lines.append(f"{ind}}}));")
        if node.handlers:
            self.lines.append(f"{ind}if __result.is_err() {{")
            self.indent_lvl += 1
            for s in node.handlers[0].body:
                self.stmt(s)
            self.indent_lvl -= 1
            self.lines.append(f"{ind}}}")
        if node.finalbody:
            for s in node.finalbody:
                self.stmt(s)


def emit_rust(units: list[FuncUnit], entry: str | None,
              library_mode: bool = False,
              extern_fns: list[FuncUnit] | None = None,
              export_fns: list[str] | None = None,
              classes: list | None = None,
              constants: dict | None = None,
              preamble: dict | None = None) -> tuple[str, dict[str, str]]:
    """Return (full_program_source, {func_name: emitted_source}).

    In library_mode: emit C-ABI exports (no main), for FFI consumption.
    extern_fns: functions from other backends (C++) that this Rust code calls.
                Emits `extern "C"` declarations so the linker can resolve them.
    export_fns: names of Rust functions that are called from other backends (C++).
                These functions are marked `#[no_mangle] pub extern "C"` so the
                linker can resolve cross-backend calls.
    classes: list of ClassUnit objects to emit as struct definitions.
    constants: module-level constants to inline (name -> value).
    """
    emitter = RustEmitter(SPEC)
    emitter.func_signatures = {
        u.name: ([p for p, _t in u.params],
                 dict(getattr(u, 'param_defaults', {})))
        for u in units
    }
    emitter.library_mode = library_mode
    emitter.export_names = set(export_fns) if export_fns else set()
    emitter.constants = constants or {}
    emitted: dict[str, str] = {}
    fns: list[str] = []

    # register class names so constructor calls work
    if classes:
        for cls in classes:
            emitter.class_names.add(cls.name)
            emitter.class_fields[cls.name] = cls.fields
            emitter.class_bases[cls.name] = cls.bases
            emitter.class_properties[cls.name] = cls.properties
            emitter.class_static_methods[cls.name] = cls.static_methods

    # pre-scan all units for mutated list params (so call sites can pass &mut)
    # also build function return type lookup for type inference
    for u in units:
        if not u.supported:
            continue
        emitter.func_return_types[u.name] = u.ret_type
        param_names = {p[0]: i for i, p in enumerate(u.params)}
        mutated = set()
        for node in ast.walk(u.body):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in param_names:
                        mutated.add(param_names[target.id])
                    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id in param_names:
                        mutated.add(param_names[target.value.id])
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id in param_names:
                    mutated.add(param_names[node.target.id])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "append" and isinstance(node.func.value, ast.Name):
                    if node.func.value.id in param_names:
                        mutated.add(param_names[node.func.value.id])
        emitter.func_mutated_params[u.name] = mutated

    # emit struct definitions before functions
    if classes:
        struct_code = _emit_structs(classes)
        if struct_code:
            fns.append(struct_code)

    # inject user preamble (file-scope code from ge_preamble("rust", "..."))
    # placed before functions so preamble code (e.g. Win32 FFI) is visible
    if preamble and "rust" in preamble:
        fns.append("// === user preamble (ge_preamble) ===\n" + preamble["rust"])

    # emit extern "C" declarations for cross-backend calls
    # these are C++ functions that Rust code calls — declared as unsafe externs
    extern_names: set[str] = set()
    if extern_fns:
        for u in extern_fns:
            if not u.supported:
                continue
            ext_params = []
            for pname, ptype in u.params:
                if ptype == "list":
                    ext_params.append(f"{pname}: {SPEC.list_param_type}")
                else:
                    nt = SPEC.types.get(ptype, "f64")
                    ext_params.append(f"{pname}: {nt}")
            ret = SPEC.types.get(u.ret_type, "()") if u.ret_type != "None" else "()"
            ext_sig = ", ".join(ext_params)
            fns.append(f'extern "C" {{\n    fn {u.name}({ext_sig}) -> {ret};\n}}\n')
            extern_names.add(u.name)
    emitter.extern_names = extern_names

    if library_mode:
        for u in units:
            if not u.supported:
                continue
            if u.is_method and u.name.endswith(".__init__"):
                continue  # constructor emitted by _emit_structs
            code = emitter.emit(u)
            if emitter.unsupported_emissions:
                u.supported = False
                u.unsupported_reasons.extend(emitter.unsupported_emissions)
                continue
            emitted[u.name] = code
            fns.append(code)
        return "\n".join(fns) + "\n", emitted

    entry_u = _entry_unit(units, entry)
    for u in units:
        if u.is_method and u.name.endswith(".__init__"):
            continue  # constructor emitted by _emit_structs
        if u is entry_u and u.name == "main":
            # Rust main() must return (). If the source main() returns int,
            # strip the return value by overriding the signature and adding a suffix.
            if u.ret_type == "None":
                code = emitter.emit(u, sig_override="fn main()")
            else:
                # Emit with a wrapper that calls main() and ignores the return
                code = emitter.emit(u, sig_override="fn __ge_main() -> i64")
        else:
            code = emitter.emit(u)
        if emitter.unsupported_emissions:
            u.supported = False
            u.unsupported_reasons.extend(emitter.unsupported_emissions)
            continue
        emitted[u.name] = code
        fns.append(code)

    if entry_u.name != "main":
        if entry_u.ret_type == "None":
            wrapper = f"fn main() {{\n    {entry_u.name}();\n}}\n"
        else:
            wrapper = f"fn main() {{\n    let _ = {entry_u.name}();\n}}\n"
        fns.append(wrapper)
    elif entry_u.ret_type != "None":
        # main() returns int — we renamed it to __ge_main(), add a wrapper
        wrapper = f"fn main() {{\n    let _ = __ge_main();\n}}\n"
        fns.append(wrapper)

    program = "\n".join(fns) + "\n"
    # inject stdlib runtime
    from ..stdlib import get_runtime
    runtime = get_runtime("rust")
    if runtime:
        program = runtime + "\n" + program
    return program, emitted
