"""Kotlin backend spec + program assembly.

Kotlin/Native compiles to a native shared library that exports C ABI
functions via `@CName`. Interops with C/C++/Rust/Zig/Go/C# through the
C ABI boundary. Best for Android, Kotlin Multiplatform, and JVM-adjacent code.
"""
from __future__ import annotations

import ast

from .base import Emitter, Spec
from ..analyzer import FuncUnit

SPEC = Spec(
    name="kotlin",
    types={"int": "Long", "float": "Double", "bool": "Boolean", "str": "String", "None": "Unit"},
    list_type="MutableList<Long>",
    list_param_type="MutableList<Long>",
    list_elem_type="Long",
    borrow_list_arg=False,
    range_call="({lo}..{hi})",
    range_step_call="({lo}..{hi} step {step})",
    len_call="{x}.size.toLong()",
    list_len="{x}.size.toLong()",
    print_int='println({v})',
    print_float='println({v})',
    print_str='println({v})',
    print_bool='println({v})',
    print_generic='println({v})',
    int_cast="{x}.toLong()",
    float_cast="{x}.toDouble()",
    float_div="({l}.toDouble() / {r}.toDouble())",
    floor_div="({l} / {r})",
    sum_call="{it}.sum()",
    abs_int="abs({x})",
    abs_float="abs({x})",
    min_call="{it}.minOrNull()!!",
    max_call="{it}.maxOrNull()!!",
    pow_call="Math.pow({l}.toDouble(), {r}.toDouble()).toLong()",
    append_call="{x}.add({v})",
    index_call="{x}[{i}.toInt()]",
    comment="//",
    fn_template="{sig} {{\n{body}\n}}",
    main_template="",
    var_decl_template="var {target}: {nt} = {val};",
    ffi_prefix="@CName(\"{name}\")\n",
    indent="    ",
    str_concat="{l} + {r}",
    str_len="{x}.length.toLong()",
    str_index="{x}[{i}.toInt()].toLong()",
    str_slice="{x}.substring({start}.toInt(), {end}.toInt())",
    str_slice_start="{x}.substring({start}.toInt())",
    str_slice_end="{x}.substring(0, {end}.toInt())",
    list_concat="run {{ val t = mutableListOf<Long>(); t.addAll({l}); t.addAll({r}); t }}",
    foreach_template="for ({var} in {iter})",
    try_template="try {{\n{body}\n}} catch (e: Exception) {{\n{handler}\n}}",
    struct_template="data class {name} {{\n{fields}\n}}",
    struct_field_template="    val {type}: {name},",
    struct_new_template="fun {name}_new({params}): {name} {{\n{body}\n}}",
    dict_type="HashMap<String, {V}>",
    dict_get="{d}[{k}]",
    dict_set="{d}[{k}] = {v}",
    dict_contains="{d}.containsKey({k})",
    tuple_type="Pair<{T}, {T}>",
    tuple_get="{t}.{field}",
)


class KotlinEmitter(Emitter):
    def expr(self, node):  # type: ignore[override]
        # Add L suffix to integer literals for Long compatibility
        # Note: bool is a subclass of int in Python, so exclude it explicitly
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            return f"{node.value}L"
        return super().expr(node)

    def _try_stmt(self, node, ind):
        """Kotlin try/catch syntax."""
        self.lines.append(f"{ind}try {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        if node.handlers:
            self.lines.append(f"{ind}}} catch (e: Exception) {{")
            self.indent_lvl += 1
            for s in node.handlers[0].body:
                self.stmt(s)
            self.indent_lvl -= 1
            self.lines.append(f"{ind}}}")
        else:
            self.lines.append(f"{ind}}} catch (e: Exception) {{")
            self.lines.append(f"{ind}}}")
        if node.finalbody:
            self.lines.append(f"{ind}finally {{")
            self.indent_lvl += 1
            for s in node.finalbody:
                self.stmt(s)
            self.indent_lvl -= 1
            self.lines.append(f"{ind}}}")

    def emit(self, unit: FuncUnit) -> str:
        """Override emit to make mutable copies of parameters that are reassigned."""
        # Find mutated parameters by scanning the body
        param_names = {p[0] for p in unit.params}
        mutated_params = set()
        for node in ast.walk(unit.body):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in param_names:
                        mutated_params.add(t.id)
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id in param_names:
                    mutated_params.add(node.target.id)
        result = super().emit(unit)
        if mutated_params:
            # Insert `var n_ = n` copies at the start of the function body
            import re
            lines = result.split("\n")
            for i, line in enumerate(lines):
                if "{" in line and "fun" in lines[max(0, i)]:
                    for j, pname in enumerate(sorted(mutated_params)):
                        lines.insert(i + 1 + j, f"    var {pname}_ = {pname}")
                    break
            result = "\n".join(lines)
            # Replace param references with mutable version
            for pname in mutated_params:
                result = re.sub(r'\b' + pname + r'\b', pname + "_", result)
                # Fix the signature
                result = result.replace(f"{pname}_: Long", f"{pname}: Long")
                # Fix the copy line
                result = result.replace(f"var {pname}_ = {pname}_", f"var {pname}_ = {pname}")
        return result

    def for_loop(self, node, ind):  # type: ignore[override]
        var = node.target.id if isinstance(node.target, ast.Name) else "_"
        it = node.iter
        if isinstance(it, ast.Call) and getattr(it.func, "id", None) == "range":
            args = it.args
            if len(args) == 1:
                lo, hi = "0", self.expr(args[0])
            else:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            self.var_types[var] = "int"
            # Kotlin 'until' is exclusive (like Python range), '..' is inclusive
            self.lines.append(f"{ind}for ({var} in {lo} until {hi}) {{")
        else:
            iter_s = self.expr(it)
            self.var_types[var] = "long"
            self.lines.append(f"{ind}for ({var} in {iter_s}) {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        self.lines.append(f"{ind}}}")

    def signature(self, unit: FuncUnit) -> str:
        emit_name = unit.name.replace(".", "_")
        params = []
        for pname, ptype in unit.params:
            nt = self.param_native_type(ptype)
            params.append(f"{pname}: {nt}")
        ret = self.py_to_native(unit.ret_type) if unit.ret_type != "None" else "Unit"
        param_str = ", ".join(params)
        if ret == "Unit":
            return f"fun {emit_name}({param_str})"
        return f"fun {emit_name}({param_str}): {ret}"


def _entry_unit(units: list[FuncUnit], entry: str | None) -> FuncUnit:
    if entry:
        for u in units:
            if u.name == entry:
                return u
    for u in units:
        if u.name == "main":
            return u
    return units[0]


def _emit_structs_kotlin(classes: list) -> str:
    """Emit Kotlin data class definitions and constructors for ClassUnits."""
    out: list[str] = []
    for cls in classes:
        fields_str = ""
        for fname, ftype in cls.fields:
            nt = SPEC.types.get(ftype, SPEC.types.get("float"))
            if ftype == "list":
                nt = "LongArray"
            elif ftype == "None" or not nt:
                nt = "Long"
            fields_str += f"    var {fname}: {nt},\n"
        out.append(f"data class {cls.name}(\n{fields_str})\n")
        if cls.constructor_params:
            params_str = ", ".join(
                f"{pname}: {SPEC.types.get(ptype, 'Double')}"
                for pname, ptype in cls.constructor_params
            )
            init_args = ", ".join(fname for fname, _ in cls.constructor_params)
            out.append(f"fun {cls.name}_new({params_str}): {cls.name} {{\n"
                        f"    return {cls.name}({init_args})\n}}\n")
        else:
            out.append(f"fun {cls.name}_new(): {cls.name} {{\n"
                        f"    return {cls.name}()\n}}\n")
    return "\n".join(out)


def emit_kotlin(units: list[FuncUnit], entry: str | None,
               library_mode: bool = False,
               extern_fns: list[FuncUnit] | None = None,
               classes: list | None = None,
               constants: dict | None = None,
               preamble: dict | None = None) -> tuple[str, dict[str, str]]:
    """Return (full_program_source, {func_name: emitted_source}).

    In library_mode: emit @CName exports for C ABI FFI.
    extern_fns: functions from other backends that this Kotlin code calls.
    """
    emitter = KotlinEmitter(SPEC)
    emitter.library_mode = library_mode
    emitter.constants = constants or {}
    emitted: dict[str, str] = {}
    fns: list[str] = []

    # register class names
    if classes:
        for cls in classes:
            emitter.class_names.add(cls.name)
            emitter.class_fields[cls.name] = cls.fields
            emitter.class_bases[cls.name] = cls.bases
            emitter.class_properties[cls.name] = cls.properties
            emitter.class_static_methods[cls.name] = cls.static_methods

    prelude = (
        "import kotlin.math.*\n\n"
    )

    # emit external function declarations for cross-backend calls
    if extern_fns:
        decls = []
        for u in extern_fns:
            if not u.supported:
                continue
            params = ", ".join(
                f"{'LongArray' if ptype == 'list' else SPEC.types.get(ptype, 'Double')} {pname}"
                for pname, ptype in u.params)
            ret = SPEC.types.get(u.ret_type, "Unit") if u.ret_type != "None" else "Unit"
            decls.append(f"external fun {u.name}({params}): {ret}")
        prelude += "\n// cross-backend declarations\n" + "\n".join(decls) + "\n\n"

    # emit struct definitions
    if classes:
        struct_code = _emit_structs_kotlin(classes)
        if struct_code:
            prelude += struct_code + "\n"

    # build function return type lookup for type inference
    for u in units:
        if u.supported:
            emitter.func_return_types[u.name] = u.ret_type

    if library_mode:
        for u in units:
            if not u.supported:
                continue
            if u.is_method and u.name.endswith(".__init__"):
                continue
            code = emitter.emit(u)
            if emitter.unsupported_emissions:
                u.supported = False
                u.unsupported_reasons.extend(emitter.unsupported_emissions)
                continue
            # prefix with @CName for C ABI export
            emit_name = u.name.replace(".", "_")
            code = code.replace(f"fun {emit_name}(", f'@CName("{emit_name}")\nfun {emit_name}(')
            emitted[u.name] = code
            fns.append(code)
        return prelude + "\n".join(fns) + "\n", emitted

    entry_u = _entry_unit(units, entry)
    for u in units:
        if u.is_method and u.name.endswith(".__init__"):
            continue
        code = emitter.emit(u)
        if emitter.unsupported_emissions:
            u.supported = False
            u.unsupported_reasons.extend(emitter.unsupported_emissions)
            continue
        emitted[u.name] = code
        fns.append(code)

    if entry_u.name != "main":
        if entry_u.ret_type == "None":
            wrapper = "fun main() {\n    " + entry_u.name + "()\n}\n"
        else:
            wrapper = f"fun main() {{\n    {entry_u.name}()\n}}\n"
        fns.append(wrapper)
    else:
        # Kotlin main() must return Unit (void)
        # Rename the user's main() to __ge_main() and add a wrapper
        if entry_u.ret_type != "None":
            fns[-1] = fns[-1].replace(f"fun {entry_u.name}(", "fun __ge_main(")
            wrapper = "fun main() {\n    __ge_main()\n}\n"
            fns.append(wrapper)
        else:
            fns[-1] = fns[-1].replace(f"fun {entry_u.name}(", "fun main(")

    program = prelude + "\n".join(fns) + "\n"
    # inject stdlib runtime (after imports, before functions)
    from ..stdlib import get_runtime
    runtime = get_runtime("kotlin")
    if runtime:
        program = prelude + runtime + "\n" + "\n".join(fns) + "\n"
    return program, emitted
