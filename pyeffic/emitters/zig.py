"""Zig backend spec + program assembly.

Zig compiles to native code with no runtime. Exports C ABI functions with
the `export` keyword. Interops seamlessly with C/C++/Rust via the C ABI.
"""
from __future__ import annotations

import ast

from .base import Emitter, Spec
from ..analyzer import FuncUnit

SPEC = Spec(
    name="zig",
    types={"int": "i64", "float": "f64", "bool": "bool", "str": "[]const u8", "None": "void"},
    list_type="std.ArrayList({T})",
    list_param_type="*std.ArrayList(i64)",
    list_elem_type="i64",
    list_slice="geListSlice(i64, {x}.items, @as(usize, @intCast({start})), @as(usize, @intCast({stop})))",
    list_copy="geListCopy(i64, {x}.items)",
    borrow_list_arg=False,
    range_call="({lo}..{hi})",
    range_step_call="({lo}..{hi})",
    len_call="@as(i64, @intCast({x}.items.len))",
    list_len="@as(i64, @intCast({x}.items.len))",
    print_int='std.io.getStdOut().writer().print("{{d}}\\n", .{{{v}}}) catch unreachable',
    print_float='std.io.getStdOut().writer().print("{{d}}\\n", .{{{v}}}) catch unreachable',
    print_str='std.io.getStdOut().writer().print("{{s}}\\n", .{{{v}}}) catch unreachable',
    print_bool='std.io.getStdOut().writer().print("{{s}}\\n", .{{if ({v}) "True" else "False"}}) catch unreachable',
    print_generic='std.io.getStdOut().writer().print("{{any}}\\n", .{{{v}}}) catch unreachable',
    list_sort="std.mem.sort(i64, {x}.items, {{}}, std.sort.asc(i64))",
    list_reverse="std.mem.reverse(i64, {x}.items)",
    print_list='gePrintList({v}.items)',
    int_cast="@as(i64, {x})",
    int_cast_float="@as(i64, @intFromFloat({x}))",
    float_cast="@as(f64, {x})",
    float_div="(@as(f64, {l}) / @as(f64, {r}))",
    floor_div="@divFloor({l}, {r})",
    sum_call="blk: {{ var s: i64 = 0; for ({it}.items) |v| {{ s += v; }} break :blk s; }}",
    abs_int="@as(i64, @intCast(if ({x} < 0) -{x} else {x}))",
    abs_float="@abs({x})",
    min2_call="@min({a}, {b})",
    max2_call="@max({a}, {b})",
    min_call="blk: {{ var __m = {it}.items[0]; for ({it}.items) |v| {{ if (v < __m) __m = v; }} break :blk __m; }}",
    max_call="blk: {{ var __m = {it}.items[0]; for ({it}.items) |v| {{ if (v > __m) __m = v; }} break :blk __m; }}",
    pow_call="std.math.pow(i64, {l}, {r})",
    pow_int="std.math.pow(i64, {l}, {r})",
    pow_float="std.math.pow(f64, {l}, {r})",
    append_call="{x}.append({v}) catch unreachable",
    index_call="{x}.items[@as(usize, @intCast({i}))]",
    comment="//",
    fn_template="{sig} {{\n{body}\n}}",
    main_template="",
    var_decl_template="var {target}: {nt} = {val};",
    ffi_prefix="export fn ",
    indent="    ",
    str_concat="{l} ++ {r}",
    str_len="{x}.len",
    str_index="({x})[@as(usize, @intCast({i}))..][0..1]",
    str_slice="{x}[{start}..{end}]",
    str_slice_start="{x}[{start}..]",
    str_slice_end="{x}[..{end}]",
    list_concat="geListConcat(i64, {l}.items, {r}.items)",
    str_split="geStrSplit({x}, {sep})",
    str_join="geStrJoin({x}.items, {sep})",
    str_upper="geStrUpper({x})",
    str_lower="geStrLower({x})",
    str_replace="geStrReplace({x}, {a}, {b})",
    foreach_template="for ({iter}.items) |{var}|",
    try_template="// try/except limited in Zig\n// {body}\n// {handler}",
    struct_template="const {name} = struct {{\n{fields}\n}};",
    struct_field_template="    {type}: {name},",
    struct_new_template="fn {name}_new({params}) {name} {{\n{body}\n}}",
    dict_type="std.StringHashMap({V})",
    set_type="std.AutoHashMap(i64, void)",
    dict_get="{d}.get({k}).?",
    dict_set="{d}.put({k}, {v}) catch unreachable",
    dict_contains="{d}.contains({k})",
    set_len="@as(i64, @intCast({x}.count()))",
    dict_len="@as(i64, @intCast({x}.count()))",
    tuple_type="[2]{T}",
    tuple_get="{t}[{i}]",
)


class ZigEmitter(Emitter):
    def __init__(self, spec):
        super().__init__(spec)
        self.mutated: set[str] = set()

    def _try_stmt(self, node, ind):
        """Zig doesn't have try/catch — emit body directly, comment handler."""
        self.lines.append(f"{ind}// try/except: Zig has no exceptions")
        for s in node.body:
            self.stmt(s)
        if node.handlers:
            self.lines.append(f"{ind}// except handler (not emitted in Zig):")
            for s in node.handlers[0].body:
                save = self.lines
                self.lines = []
                self.stmt(s)
                for line in self.lines:
                    save.append(f"{ind}// {line.strip()}")
                self.lines = save
        if node.finalbody:
            for s in node.finalbody:
                self.stmt(s)

    def expr(self, node):  # type: ignore[override]
        # Zig requires @rem for signed integer modulo
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            left = self.expr(node.left)
            right = self.expr(node.right)
            return f"@rem({left}, {right})"
        return super().expr(node)

    def _find_mutated_vars(self, body: list) -> set[str]:
        """Scan AST body for variables that are mutated (AugAssign, re-assign, append, subscript assign)."""
        mutated: set[str] = set()
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name):
                    mutated.add(node.target.id)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        mutated.add(t.id)
                    elif isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                        mutated.add(t.value.id)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "append" and isinstance(node.func.value, ast.Name):
                    mutated.add(node.func.value.id)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                # passing a list to a callee that mutates it counts as a
                # mutation here, so the local must be `var`
                for idx in self.func_mutated_params.get(node.func.id, ()):
                    if idx < len(node.args):
                        arg = node.args[idx]
                        if isinstance(arg, ast.Name):
                            mutated.add(arg.id)
        return mutated

    def emit(self, unit: FuncUnit) -> str:
        """Emit a function.

        A list parameter is a `*std.ArrayList(i64)`, so no conversion is
        needed: the callee mutates the caller's list directly. Only scalar
        parameters that are reassigned need a mutable local, because Zig
        parameters are immutable.
        """
        self.mutated = self._find_mutated_vars(unit.body)
        self.mutated_list_params = {
            pname for pname, ptype in unit.params
            if ptype == "list" and pname in self.mutated
        }
        self.mutated_params = {
            pname for pname, ptype in unit.params
            if pname in self.mutated and ptype != "list"
        }
        result = super().emit(unit)
        if self.mutated_params:
            lines = result.split("\n")
            insert = [f"    var {p}_ = {p};" for p in sorted(self.mutated_params)]
            for i, line in enumerate(lines):
                if "fn" in line and "{" in line:
                    for j, il in enumerate(insert):
                        lines.insert(i + 1 + j, il)
                    break
            result = "\n".join(lines)
            import re
            for pname in self.mutated_params:
                result = re.sub(r"\b" + pname + r"\b", pname + "_", result)
                result = re.sub(r"\b" + pname + r"_: ", pname + ": ", result, count=1)
                result = result.replace(f"var {pname}_ = {pname}_;",
                                        f"var {pname}_ = {pname};")
        return result

    def _is_mutated(self, var: str) -> bool:
        return var in self.mutated

    def _decl_keyword(self, var: str) -> str:
        """Return 'var' for mutated variables, 'const' for unmutated."""
        return "var" if self._is_mutated(var) else "const"

    def stmt(self, node):  # type: ignore[override]
        """Override to use const/var based on mutation tracking."""
        ind = self.spec.indent * self.indent_lvl
        # Zig requires non-void return values to be used or discarded with `_ = `
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            fname = getattr(node.value.func, "id", None)
            if fname != "print":
                self.lines.append(f"{ind}_ = {self.expr(node.value)};")
                return
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            # bare `list` gets its element type from the value
            target = node.target.id if isinstance(node.target, ast.Name) else self.expr(node.target)
            t = self._ann_type(node.annotation) if isinstance(node.target, ast.Name) else self.infer_type(node.value)
            if isinstance(node.target, ast.Name):
                self.var_types[target] = t
                self.declared.add(target)
            nt = self.py_to_native(t)
            if t == "list":
                # a bare `list` annotation carries no element type; take it
                # from the value so `"a,b".split(",")` is a string list
                elem = self._list_elem_of_value(node.value)
                if elem and elem != self.spec.list_elem_type:
                    nt = self.spec.list_type.format(T=elem)
            kw = self._decl_keyword(target)
            self.lines.append(f"{ind}{kw} {target}: {nt} = {self.expr(node.value)};")
            return
        if isinstance(node, ast.Assign):
            val = self.expr(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    t = self.infer_type(node.value)
                    self.var_types[target.id] = t
                    nt = self.py_to_native(t)
                    if target.id in self.declared:
                        self.lines.append(f"{ind}{target.id} = {val};")
                    else:
                        self.declared.add(target.id)
                        kw = self._decl_keyword(target.id)
                        self.lines.append(f"{ind}{kw} {target.id}: {nt} = {val};")
                elif isinstance(target, ast.Subscript):
                    target_type = self.infer_type(target.value)
                    if target_type == "dict":
                        key = self.expr(target.slice)
                        d = self.expr(target.value)
                        self.lines.append(f"{ind}{self.spec.dict_set.format(d=d, k=key, v=val)};")
                    else:
                        self.lines.append(f"{ind}{self.expr(target)} = {val};")
                else:
                    self.lines.append(f"{ind}// unsupported assign target")
            return
        super().stmt(node)

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
            # loop variables are always mutated (incremented)
            self.lines.append(f"{ind}var {var}: i64 = {lo};")
            self.lines.append(f"{ind}while ({var} < {hi}) : ({var} += 1) {{")
        else:
            iter_s = self.expr(it)
            if self.infer_type(it) == "dict":
                # Zig has no allocator here, so walk the map's key iterator
                # instead of materialising a key list.
                self.var_types[var] = "str"
                self.lines.append(f"{ind}var __keys_{var} = {iter_s}.keyIterator();")
                self.lines.append(f"{ind}while (__keys_{var}.next()) |__kp_{var}| {{")
                self.lines.append(f"{ind}    const {var} = __kp_{var}.*;")
            else:
                self.var_types[var] = "long"
                self.lines.append(f"{ind}for ({iter_s}.items) |{var}| {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        self.lines.append(f"{ind}}}")

    def signature(self, unit: FuncUnit) -> str:
        emit_name = unit.name.replace(".", "_")
        params = []
        for pname, ptype in unit.params:
            nt = self.param_native_type(ptype, pname)
            # A parameter this function does not mutate is borrowed const, so
            # the caller may keep its own binding `const`.
            if (ptype == "list" and nt.startswith("*std.ArrayList")
                    and pname not in self.mutated_list_params):
                nt = "*const " + nt[1:]
            params.append(f"{pname}: {nt}")
        ret = self.py_to_native(unit.ret_type) if unit.ret_type != "None" else "void"
        param_str = ", ".join(params)
        if ret == "void":
            return f"fn {emit_name}({param_str}) void"
        return f"fn {emit_name}({param_str}) {ret}"


def _entry_unit(units: list[FuncUnit], entry: str | None) -> FuncUnit:
    if entry:
        for u in units:
            if u.name == entry:
                return u
    for u in units:
        if u.name == "main":
            return u
    return units[0]


def _emit_structs_zig(classes: list) -> str:
    """Emit Zig struct definitions and constructors for ClassUnits."""
    out: list[str] = []
    for cls in classes:
        fields_str = ""
        for fname, ftype in cls.fields:
            nt = SPEC.types.get(ftype, SPEC.types.get("float"))
            if ftype == "list":
                nt = "[]const i64"
            fields_str += f"    {fname}: {nt},\n"
        out.append(f"const {cls.name} = struct {{\n{fields_str}}};\n")
        if cls.constructor_params:
            params_str = ", ".join(
                f"{pname}: {SPEC.types.get(ptype, 'f64')}"
                for pname, ptype in cls.constructor_params
            )
            init_lines = "\n".join(
                f"        .{fname} = {fname}," for fname, _ in cls.constructor_params
            )
            out.append(f"fn {cls.name}_new({params_str}) {cls.name} {{\n"
                        f"    return .{{\n{init_lines}\n    }};\n}}\n")
        else:
            out.append(f"fn {cls.name}_new() {cls.name} {{\n"
                        f"    return .{{}};\n}}\n")
    return "\n".join(out)


def _precompute_mutated_params(emitter, units) -> None:
    """Record which parameters each function mutates.

    The emitter normally learns this as it emits each unit, so a function
    defined after its caller would not be known yet. Doing it up front makes
    call-site handling independent of definition order.
    """
    for u in units:
        if u.body is None:
            continue
        mutated = emitter._find_mutated_vars(u.body.body)
        indices = {i for i, (pname, _pt) in enumerate(u.params)
                   if pname in mutated}
        if indices:
            emitter.func_mutated_params[u.name] = indices


def emit_zig(units: list[FuncUnit], entry: str | None,
             library_mode: bool = False,
             extern_fns: list[FuncUnit] | None = None,
             classes: list | None = None,
             constants: dict | None = None,
             preamble: dict | None = None) -> tuple[str, dict[str, str]]:
    """Return (full_program_source, {func_name: emitted_source}).

    In library_mode: emit `export fn` for C ABI FFI.
    extern_fns: functions from other backends that this Zig code calls.
    """
    emitter = ZigEmitter(SPEC)
    emitter.func_signatures = {
        u.name: ([p for p, _t in u.params],
                 dict(getattr(u, 'param_defaults', {})))
        for u in units
    }
    emitter.library_mode = library_mode
    emitter.constants = constants or {}
    _precompute_mutated_params(emitter, units)
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
        'const std = @import("std");\n\n'
    )

    # emit extern declarations for cross-backend calls
    if extern_fns:
        decls = []
        for u in extern_fns:
            if not u.supported:
                continue
            params = ", ".join(
                f"{'[]const i64' if ptype == 'list' else SPEC.types.get(ptype, 'f64')} {pname}"
                for pname, ptype in u.params)
            ret = SPEC.types.get(u.ret_type, "void") if u.ret_type != "None" else "void"
            decls.append(f'extern fn {u.name}({params}) {ret};')
        prelude += "\n// cross-backend declarations\n" + "\n".join(decls) + "\n\n"

    # emit struct definitions
    if classes:
        struct_code = _emit_structs_zig(classes)
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
            # prefix with `export` for C ABI
            code = code.replace(f"fn {u.name.replace('.', '_')}(", f"export fn {u.name.replace('.', '_')}(")
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
            wrapper = ("pub fn main() void {\n"
                       "    defer _ = ge_arena.deinit();\n"
                       "    " + entry_u.name + "();\n}\n")
        else:
            wrapper = (f"pub fn main() void {{\n"
                       f"    defer _ = ge_arena.deinit();\n"
                       f"    _ = {entry_u.name}();\n}}\n")
        fns.append(wrapper)
    elif not fns:
        # the entry function was rejected during emission; the pipeline
        # already has the reason, so emit a stub rather than crashing
        return prelude, emitted
    else:
        # Zig main() must return void (or u8 for exit code)
        # Rename the user's main() to __ge_main() and add a wrapper that also
        # releases the arena.
        if entry_u.ret_type != "None":
            fns[-1] = fns[-1].replace(f"fn {entry_u.name}(", "fn __ge_main(")
            wrapper = ("pub fn main() void {\n"
                       "    defer _ = ge_arena.deinit();\n"
                       "    _ = __ge_main();\n}\n")
        else:
            fns[-1] = fns[-1].replace(f"fn {entry_u.name}(", "fn __ge_main(")
            wrapper = ("pub fn main() void {\n"
                       "    defer _ = ge_arena.deinit();\n"
                       "    __ge_main();\n}\n")
        fns.append(wrapper)

    program = prelude + "\n".join(fns) + "\n"
    # inject stdlib runtime
    from ..stdlib import get_runtime
    runtime = get_runtime("zig")
    if runtime:
        program = runtime + "\n" + program
    return program, emitted
