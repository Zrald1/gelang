"""C# backend spec + program assembly.

Compiles via .NET NativeAOT to a native shared library that exports C ABI
functions via [UnmanagedCallersOnly]. Interops with Rust/C++/Zig/Go through
the C ABI boundary.
"""
from __future__ import annotations

import ast

from .base import Emitter, Spec
from ..analyzer import FuncUnit

SPEC = Spec(
    name="csharp",
    types={"int": "long", "float": "double", "bool": "bool", "str": "string", "None": "void"},
    list_type="List<{T}>",
    list_param_type="List<long>",
    list_elem_type="long",
    list_sort="{x}.Sort()",
    list_reverse="{x}.Reverse()",
    str_split="{x}.Split({sep}).ToList()",
    str_upper="{x}.ToUpper()",
    str_lower="{x}.ToLower()",
    str_replace="{x}.Replace({a}, {b})",
    str_join="string.Join({sep}, {x})",
    list_slice="{x}.GetRange((int)({start}), (int)(({stop}) - ({start})))",
    list_copy="new List<long>({x})",
    borrow_list_arg=False,
    range_call="({lo}..{hi})",
    range_step_call="({lo}..{hi}).Step({step})",
    len_call="{x}.Length",
    list_len="{x}.Count",
    # Dictionary and HashSet expose Count, not Length; len()
    # fell back to len_call and emitted an invalid member.
    dict_len="{x}.Count",
    set_len="{x}.Count",
    print_int='Console.WriteLine({v})',
    print_float='Console.WriteLine({v})',
    print_str='Console.WriteLine({v})',
    print_bool='Console.WriteLine({v})',
    print_generic='Console.WriteLine({v})',
    print_list='Console.WriteLine("[" + string.Join(", ", {v}) + "]")',
    int_cast="(long)({x})",
    float_cast="(double)({x})",
    float_div="((double)({l}) / (double)({r}))",
    floor_div="({l} / {r})",
    sum_call="{it}.Sum()",
    abs_int="Math.Abs({x})",
    abs_float="Math.Abs({x})",
    min2_call="Math.Min({a}, {b})",
    max2_call="Math.Max({a}, {b})",
    min_call="{it}.Min()",
    max_call="{it}.Max()",
    pow_call="Math.Pow({l}, {r})",
    pow_int="(long)Math.Pow({l}, {r})",
    pow_float="Math.Pow({l}, {r})",
    append_call="{x}.Add({v})",
    index_call="{x}[(int)({i})]",
    comment="//",
    fn_template="{sig}\n{{\n{body}\n}}",
    main_template="",
    ffi_prefix="[UnmanagedCallersOnly]\npublic static ",
    indent="    ",
    str_concat="{l} + {r}",
    str_len="{x}.Length",
    str_index="({x})[(int)({i})].ToString()",
    str_slice="{x}.Substring({start}, {len})",
    str_slice_start="{x}.Substring({start})",
    str_slice_end="{x}.Substring(0, {end})",
    list_concat="new List<long>({l}).Concat({r}).ToList()",
    foreach_template="foreach (var {var} in {iter})",
    try_template="try {{\n{body}\n}} catch {{\n{handler}\n}}",
    struct_template="struct {name} {{\n{fields}\n}}",
    struct_field_template="    public {type} {name};",
    struct_new_template="static {name} {name}_New({params}) {{\n{body}\n}}",
    dict_type="Dictionary<string, {V}>",
    set_type="HashSet<long>",
    dict_get="{d}[{k}]",
    dict_set="{d}[{k}] = {v}",
    dict_keys="{x}.Keys",
    dict_contains="{d}.ContainsKey({k})",
    tuple_type="({T}, {T})",
    tuple_get="{t}.Item{i1}",
)


class CSharpEmitter(Emitter):
    # C# reserved keywords that need @ prefix when used as identifiers
    _KEYWORDS = {"abstract", "as", "base", "bool", "break", "byte", "case",
                 "catch", "char", "checked", "class", "const", "continue",
                 "decimal", "default", "delegate", "do", "double", "else",
                 "enum", "event", "explicit", "extern", "false", "finally",
                 "fixed", "float", "for", "foreach", "goto", "if", "implicit",
                 "in", "int", "interface", "internal", "is", "lock", "long",
                 "namespace", "new", "null", "object", "operator", "out",
                 "override", "params", "private", "protected", "public",
                 "readonly", "ref", "return", "sbyte", "sealed", "short",
                 "sizeof", "stackalloc", "static", "string", "struct",
                 "switch", "this", "throw", "true", "try", "typeof", "uint",
                 "ulong", "unchecked", "unsafe", "ushort", "using",
                 "virtual", "void", "volatile", "while"}

    def _esc(self, name: str) -> str:
        if name in self._KEYWORDS:
            return "@" + name
        return name

    def _ident(self, name: str) -> str:
        """Escape C# reserved words (e.g. a GE parameter named `base`)."""
        return self._esc(name)

    # note: function names are renamed in the shared IR (pyeffic.idents) so
    # cross-backend symbols agree; _ident only covers locals and parameters.

    def for_loop(self, node, ind):  # type: ignore[override]
        var = node.target.id if isinstance(node.target, ast.Name) else "_"
        it = node.iter
        if isinstance(it, ast.Call) and getattr(it.func, "id", None) == "range":
            args = it.args
            if len(args) == 1:
                lo, hi, step = "0", self.expr(args[0]), "1"
            elif len(args) == 2:
                lo, hi, step = self.expr(args[0]), self.expr(args[1]), "1"
            else:
                lo, hi, step = self.expr(args[0]), self.expr(args[1]), self.expr(args[2])
            self.var_types[var] = "int"
            self.lines.append(f"{ind}for (long {var} = {lo}; {var} < {hi}; {var}++) {{")
        else:
            iter_s = self.expr(it)
            if self.infer_type(it) == "dict":
                self.var_types[var] = "str"
                self.lines.append(f"{ind}foreach (var {var} in {iter_s}.Keys) {{")
            else:
                self.var_types[var] = "long"
                self.lines.append(f"{ind}foreach (var {var} in {iter_s}) {{")
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
            params.append(f"{nt} {self._ident(pname)}")
        ret = self.py_to_native(unit.ret_type) if unit.ret_type != "None" else "void"
        param_str = ", ".join(params)
        base_sig = f"static {ret} {emit_name}({param_str})"
        # add C ABI export prefix in library mode for FFI-exported functions
        if self.library_mode and getattr(unit, "ffi_export", False) and self.spec.ffi_prefix:
            return self.spec.ffi_prefix + base_sig
        return base_sig

    def stmt(self, node):  # type: ignore[override]
        # escape C# keywords in variable declarations
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            # bare `list` gets its element type from the value
            _ann = self._ann_type(node.annotation)
            _elem = (self._list_elem_of_value(node.value)
                     if (_ann == "list" and node.value is not None) else "")
            name = self._esc(node.target.id)
            ann_type = self._ann_type(node.annotation)
            nt = self.py_to_native(ann_type)
            if _elem and _elem != self.spec.list_elem_type:
                nt = self.spec.list_type.format(T=_elem)
            if node.value is not None:
                val = self.expr(node.value)
                self.lines.append(f"{self.spec.indent * self.indent_lvl}{nt} {name} = {val};")
                self.var_types[node.target.id] = ann_type
                self.declared.add(node.target.id)
            else:
                self.lines.append(f"{self.spec.indent * self.indent_lvl}{nt} {name};")
                self.var_types[node.target.id] = ann_type
                self.declared.add(node.target.id)
            return
        super().stmt(node)

    def _try_stmt(self, node, ind):
        """C# try/catch syntax."""
        self.lines.append(f"{ind}try {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        if node.handlers:
            self.lines.append(f"{ind}}} catch {{")
            self.indent_lvl += 1
            for s in node.handlers[0].body:
                self.stmt(s)
            self.indent_lvl -= 1
            self.lines.append(f"{ind}}}")
        else:
            self.lines.append(f"{ind}}} catch {{")
            self.lines.append(f"{ind}}}")
        if node.finalbody:
            self.lines.append(f"{ind}finally {{")
            self.indent_lvl += 1
            for s in node.finalbody:
                self.stmt(s)
            self.indent_lvl -= 1
            self.lines.append(f"{ind}}}")
        if isinstance(node, ast.Name) and node.id in self._KEYWORDS:
            return "@" + node.id
        return super().expr(node)


def _entry_unit(units: list[FuncUnit], entry: str | None) -> FuncUnit:
    if entry:
        for u in units:
            if u.name == entry:
                return u
    for u in units:
        if u.name == "main":
            return u
    return units[0]


def _emit_structs_csharp(classes: list) -> str:
    """Emit C# struct definitions and constructors for ClassUnits."""
    out: list[str] = []
    for cls in classes:
        fields_str = ""
        for fname, ftype in cls.fields:
            nt = SPEC.types.get(ftype, SPEC.types.get("float"))
            if ftype == "list":
                nt = "long[]"
            fields_str += f"    public {nt} {fname};\n"
        out.append(f"struct {cls.name} {{\n{fields_str}}}\n")
        if cls.constructor_params:
            params_str = ", ".join(
                f"{SPEC.types.get(ptype, 'double')} {pname}"
                for pname, ptype in cls.constructor_params
            )
            init_lines = "\n".join(
                f"            {fname} = {fname}," for fname, _ in cls.constructor_params
            )
            out.append(f"static {cls.name} {cls.name}_new({params_str}) {{\n"
                        f"    return new {cls.name} {{\n{init_lines}\n    }};\n}}\n")
        else:
            out.append(f"static {cls.name} {cls.name}_new() {{\n"
                        f"    return new {cls.name}();\n}}\n")
    return "\n".join(out)


def emit_csharp(units: list[FuncUnit], entry: str | None,
                library_mode: bool = False,
                extern_fns: list[FuncUnit] | None = None,
                classes: list | None = None,
                constants: dict | None = None,
                preamble: dict | None = None) -> tuple[str, dict[str, str]]:
    """Return (full_program_source, {func_name: emitted_source}).

    In library_mode: emit [UnmanagedCallersOnly] exports for C ABI FFI.
    extern_fns: functions from other backends that this C# code calls.
    """
    emitter = CSharpEmitter(SPEC)
    emitter.func_signatures = {
        u.name: ([p for p, _t in u.params],
                 dict(getattr(u, 'param_defaults', {})))
        for u in units
    }
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
        "using System;\n"
        "using System.Collections.Generic;\n"
        "using System.Linq;\n\n"
    )

    # emit DllImport declarations for cross-backend calls
    if extern_fns:
        decls = []
        for u in extern_fns:
            if not u.supported:
                continue
            params = ", ".join(
                f"{'long[]' if ptype == 'list' else SPEC.types.get(ptype, 'double')} {pname}"
                for pname, ptype in u.params)
            ret = SPEC.types.get(u.ret_type, "void") if u.ret_type != "None" else "void"
            decls.append(
                f'[DllImport("ge_logic", CallingConvention = CallingConvention.Cdecl)]\n'
                f"static extern {ret} {u.name}({params});"
            )
        prelude += "\n// cross-backend declarations (functions from other backends)\n" + "\n".join(decls) + "\n\n"

    # emit struct definitions (inside the class Program block)
    struct_code = ""
    if classes:
        struct_code = _emit_structs_csharp(classes)
        if struct_code:
            struct_code += "\n"

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

    # C# requires all methods inside a class; wrap in a Program class
    # add struct definitions at the beginning of the class block
    if struct_code:
        fns.insert(0, struct_code)

    if entry_u.name != "main":
        if entry_u.ret_type == "None":
            wrapper = "    static void Main() {\n        " + entry_u.name + "();\n    }\n"
        else:
            wrapper = "    static int Main() {\n        return (int)" + entry_u.name + "();\n    }\n"
        indented_fns = []
        for fn in fns:
            for line in fn.split("\n"):
                indented_fns.append("    " + line)
        indented_fns.append(wrapper.rstrip())
    elif not fns:
        # entry rejected during emission; see the pipeline diagnostic
        return prelude, emitted
    else:
        # rename main to Main for C# entry point
        # C# Main must return void or int (32-bit), not long
        if entry_u.ret_type == "None":
            fns[-1] = fns[-1].replace(f"static void {entry_u.name}(", "static void Main(")
        else:
            # Replace the return type and add a cast at the return
            fns[-1] = fns[-1].replace(f"static long {entry_u.name}(", "static int Main(")
            fns[-1] = fns[-1].replace(f"static int {entry_u.name}(", "static int Main(")
        indented_fns = []
        for fn in fns:
            for line in fn.split("\n"):
                indented_fns.append("    " + line)

    program = prelude + "class Program {\n" + "\n".join(indented_fns) + "\n}\n"
    # inject stdlib runtime (inside the Program class)
    from ..stdlib import get_runtime
    runtime = get_runtime("csharp")
    if runtime:
        # indent runtime code to be inside the class
        indented_runtime = "\n".join("    " + line if line else line for line in runtime.splitlines())
        program = prelude + "class Program {\n" + indented_runtime + "\n" + "\n".join(indented_fns) + "\n}\n"
    return program, emitted
