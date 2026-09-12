"""Go backend spec + program assembly.

Go compiles to a shared library via cgo. Exports C ABI functions with
`//export` directive. Interops with C/C++/Rust/Zig via the C ABI.
"""
from __future__ import annotations

import ast

from .base import Emitter, Spec
from ..analyzer import FuncUnit

SPEC = Spec(
    name="go",
    types={"int": "int64", "float": "float64", "bool": "bool", "str": "string", "None": ""},
    list_type="[]{T}",
    list_param_type="[]int64",
    list_elem_type="int64",
    list_sort="sort.Slice({x}, func(i, j int) bool {{ return {x}[i] < {x}[j] }})",
    list_reverse="sort.Slice({x}, func(i, j int) bool {{ return i > j }})",
    str_split="strings.Split({x}, {sep})",
    str_join="strings.Join({x}, {sep})",
    list_slice="append([]int64(nil), {x}[{start}:{stop}]...)",
    list_copy="append([]int64(nil), {x}...)",
    borrow_list_arg=False,
    range_call="({lo}..{hi})",
    range_step_call="({lo}..{hi})",
    len_call="int64(len({x}))",
    list_len="int64(len({x}))",
    print_int='fmt.Println({v})',
    print_float='fmt.Println({v})',
    print_str='fmt.Println({v})',
    print_bool='fmt.Println(geBoolStr({v}))',
    print_generic='fmt.Println({v})',
    print_list='fmt.Println(geListStr({v}))',
    int_cast="int64({x})",
    float_cast="float64({x})",
    float_div="(float64({l}) / float64({r}))",
    floor_div="({l} / {r})",
    sum_call="func() int64 {{ var s int64; for _, v := range {it} {{ s += v }}; return s }}()",
    abs_int="geAbsInt({x})",
    abs_float="math.Abs({x})",
    min2_call="geMin2({a}, {b})",
    max2_call="geMax2({a}, {b})",
    min_call="func() int64 {{ var m int64; for i, v := range {it} {{ if i == 0 || v < m {{ m = v }} }}; return m }}()",
    max_call="func() int64 {{ var m int64; for i, v := range {it} {{ if i == 0 || v > m {{ m = v }} }}; return m }}()",
    pow_call="int64(math.Pow(float64({l}), float64({r})))",
    pow_int="int64(math.Pow(float64({l}), float64({r})))",
    pow_float="math.Pow({l}, {r})",
    append_call="{x} = append({x}, {v})",
    index_call="{x}[{i}]",
    comment="//",
    fn_template="{sig} {{\n{body}\n}}",
    main_template="",
    var_decl_template="var {target} {nt} = {val}",
    ffi_prefix="//export ",
    indent="\t",
    str_concat="{l} + {r}",
    str_len="int64(len({x}))",
    str_index="int64({x}[{i}])",
    str_slice="{x}[{start}:{end}]",
    str_slice_start="{x}[{start}:]",
    str_slice_end="{x}[:{end}]",
    list_concat="append({l}, {r}...)",
    condition_parens=False,
    foreach_template="for _, {var} := range {iter}",
    try_template="// try/except not supported in Go\n// {body}\n// {handler}",
    struct_template="type {name} struct {{\n{fields}\n}}",
    struct_field_template="\t{type} {name}",
    struct_new_template="func {name}_New({params}) {name} {{\n{body}\n}}",
    dict_type="map[string]{V}",
    set_type="map[int64]bool",
    dict_get="{d}[{k}]",
    dict_set="{d}[{k}] = {v}",
    dict_keys="{x}",
    foreach_dict_template="for {var} := range {iter}",
    dict_contains="dictContains({d}, {k})",
    tuple_type="struct {{ a {T}; b {T} }}",
    tuple_get="{t}.{field}",
)


class GoEmitter(Emitter):
    def _try_stmt(self, node, ind):
        """Go doesn't have try/catch — emit body directly, comment handler."""
        self.lines.append(f"{ind}// try/except: Go has no exceptions")
        for s in node.body:
            self.stmt(s)
        if node.handlers:
            self.lines.append(f"{ind}// except handler (not emitted in Go):")
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

    def _is_mutated_list_param(self, name: str) -> bool:
        """Check if a name is a mutated list parameter."""
        return name in self.mutated_params and self.var_types.get(name) == "list"

    def expr(self, node: ast.AST) -> str:  # type: ignore[override]
        # Go: dereference mutated list params when used as append target
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "append" and isinstance(node.func.value, ast.Name):
                base_name = node.func.value.id
                if self._is_mutated_list_param(base_name):
                    val = self.expr(node.args[0]) if node.args else ""
                    return f"*{base_name} = append(*{base_name}, {val})"
        # Go: pass &var for mutated list params at call sites
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fname = node.func.id
            mutated_indices = self.func_mutated_params.get(fname, set())
            if mutated_indices:
                args = []
                for i, a in enumerate(node.args):
                    if i in mutated_indices and isinstance(a, ast.Name):
                        args.append(f"&{self.expr(a)}")
                    else:
                        args.append(self.expr(a))
                return f"{fname}({', '.join(args)})"
        # Go: dereference mutated list params for subscript access
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            base_name = node.value.id
            if self._is_mutated_list_param(base_name):
                idx = self.expr(node.slice)
                return f"(*{base_name})[{idx}]"
        # Go: dereference mutated list params for len()
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "len":
            if node.args and isinstance(node.args[0], ast.Name):
                base_name = node.args[0].id
                if self._is_mutated_list_param(base_name):
                    return f"int64(len(*{base_name}))"
        return super().expr(node)

    def for_loop(self, node, ind):  # type: ignore[override]
        var = node.target.id if isinstance(node.target, ast.Name) else "_"
        it = node.iter
        is_tuple_target = isinstance(node.target, ast.Tuple)
        if isinstance(it, ast.Call) and getattr(it.func, "id", None) == "range":
            args = it.args
            if len(args) == 1:
                lo, hi = "int64(0)", self.expr(args[0])
            else:
                lo, hi = "int64(" + self.expr(args[0]) + ")", self.expr(args[1])
            self.var_types[var] = "int64"
            self.lines.append(f"{ind}for {var} := {lo}; {var} < {hi}; {var}++ {{")
        elif isinstance(it, ast.Call) and getattr(it.func, "id", None) == "enumerate" and is_tuple_target:
            # for i, x in enumerate(items):
            target = node.target
            idx_var = target.elts[0].id
            val_var = target.elts[1].id
            inner_it = self.expr(it.args[0])
            self.var_types[idx_var] = "int64"
            self.var_types[val_var] = "int64"
            self.lines.append(f"{ind}for {idx_var}, {val_var} := range {inner_it} {{")
        elif isinstance(it, ast.Call) and getattr(it.func, "id", None) == "zip" and is_tuple_target:
            # for a, b in zip(x, y):
            target = node.target
            var_a = target.elts[0].id
            var_b = target.elts[1].id
            it_a = self.expr(it.args[0])
            it_b = self.expr(it.args[1])
            self.var_types[var_a] = "int64"
            self.var_types[var_b] = "int64"
            self.lines.append(f"{ind}for __i := int64(0); __i < int64(len({it_a})) && __i < int64(len({it_b})); __i++ {{")
            self.lines.append(f"{ind}    {var_a} := {it_a}[__i]; {var_b} := {it_b}[__i]")
        else:
            iter_s = self.expr(it)
            if self.infer_type(it) == "dict":
                # range over a map yields keys
                self.var_types[var] = "str"
                self.lines.append(f"{ind}for {var} := range {iter_s} {{")
            else:
                self.var_types[var] = "long"
                self.lines.append(f"{ind}for _, {var} := range {iter_s} {{")
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
            # Go: mutated list params need *[]int64 (pointer to slice) for append to propagate
            if ptype == "list" and pname in self.mutated_params:
                nt = "*[]int64"
            params.append(f"{pname} {nt}")
        ret = self.py_to_native(unit.ret_type) if unit.ret_type != "None" else ""
        param_str = ", ".join(params)
        if ret:
            return f"func {emit_name}({param_str}) {ret}"
        return f"func {emit_name}({param_str})"

    def stmt(self, node: ast.AST) -> None:
        # Go uses `var name type = value` for typed declarations
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            ann_type = self._ann_type(node.annotation)
            nt = self.py_to_native(ann_type)
            if ann_type == "list" and node.value is not None:
                elem = self._list_elem_of_value(node.value)
                if elem and elem != self.spec.list_elem_type:
                    nt = self.spec.list_type.format(T=elem)
            if node.value is not None:
                val = self.expr(node.value)
                self.lines.append(f"{self.spec.indent * self.indent_lvl}var {name} {nt} = {val}")
                self.var_types[name] = ann_type
                self.declared.add(name)
            else:
                self.lines.append(f"{self.spec.indent * self.indent_lvl}var {name} {nt}")
                self.var_types[name] = ann_type
                self.declared.add(name)
            return
        # Go uses `for` instead of `while`
        if isinstance(node, ast.While):
            ind = self.spec.indent * self.indent_lvl
            self.lines.append(f"{ind}for {self._condition(node.test)} {{")
            self.indent_lvl += 1
            for s in node.body:
                self.stmt(s)
            self.indent_lvl -= 1
            self.lines.append(f"{ind}}}")
            return
        super().stmt(node)

    def _ann_type(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            t = node.id
            if t in ("int", "float", "bool", "str", "list", "dict",
                     "tuple", "set"):
                return t
            if t in self.class_names:
                return t
            return "any"
        if isinstance(node, ast.Subscript):
            return "list"
        return "any"


def _entry_unit(units: list[FuncUnit], entry: str | None) -> FuncUnit:
    if entry:
        for u in units:
            if u.name == entry:
                return u
    for u in units:
        if u.name == "main":
            return u
    return units[0]


def _emit_structs_go(classes: list) -> str:
    """Emit Go struct definitions and constructors for ClassUnits."""
    out: list[str] = []
    for cls in classes:
        fields_str = ""
        for fname, ftype in cls.fields:
            nt = SPEC.types.get(ftype, SPEC.types.get("float"))
            if ftype == "list":
                nt = "[]int64"
            elif ftype == "None" or not nt:
                nt = "int64"
            elif ftype not in SPEC.types and ftype not in ("int", "float", "bool", "str"):
                nt = ftype  # class type
            # Go puts field name before type
            fields_str += f"\t{fname} {nt}\n"
        out.append(f"type {cls.name} struct {{\n{fields_str}}}\n")
        if cls.constructor_params:
            params_str = ", ".join(
                f"{pname} {SPEC.types.get(ptype, 'float64')}"
                for pname, ptype in cls.constructor_params
            )
            init_lines = "\n".join(
                f"        {fname}: {fname}," for fname, _ in cls.constructor_params
            )
            out.append(f"func {cls.name}_new({params_str}) {cls.name} {{\n"
                        f"    return {cls.name}{{\n{init_lines}\n    }}\n}}\n")
        else:
            out.append(f"func {cls.name}_new() {cls.name} {{\n"
                        f"    return {cls.name}{{}}\n}}\n")
    return "\n".join(out)


def emit_go(units: list[FuncUnit], entry: str | None,
            library_mode: bool = False,
            extern_fns: list[FuncUnit] | None = None,
            classes: list | None = None,
            constants: dict | None = None,
            preamble: dict | None = None) -> tuple[str, dict[str, str]]:
    """Return (full_program_source, {func_name: emitted_source}).

    In library_mode: emit //export functions for C ABI FFI.
    extern_fns: functions from other backends that this Go code calls.
    """
    emitter = GoEmitter(SPEC)
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
        "package main\n\n"
        'import "fmt"\n'
        'import "strings"\n'
        'import "strconv"\n'
        'import "sort"\n'
        'import "os"\n'
        'import "math"\n'
    )
    # add dictContains helper for dict membership tests
    prelude += "\nfunc dictContains(m map[string]int64, k string) bool {\n    _, ok := m[k]\n    return ok\n}\n"
    # add strContains helper for string membership tests (uses strings import)
    prelude += 'func strContains(s, sub string) bool {\n    return strings.Contains(s, sub)\n}\n'
    prelude += 'var _ = strContains\n'
    prelude += 'var _ = sort.Slice\n'
    prelude += 'var _ = os.ReadFile\n'
    prelude += 'var _ = math.Sqrt\n\n'
    # only add import "C" in library mode (cgo needed for //export)
    if library_mode:
        prelude += 'import "C"\n\n'
    else:
        prelude += "\n"

    # emit extern declarations for cross-backend calls
    if extern_fns:
        decls = []
        for u in extern_fns:
            if not u.supported:
                continue
            ret = SPEC.types.get(u.ret_type, "") if u.ret_type != "None" else ""
            decls.append(f"// {u.name} — from other backend (linked at runtime)")
        prelude += "\n// cross-backend declarations\n" + "\n".join(decls) + "\n\n"

    # emit struct definitions
    if classes:
        struct_code = _emit_structs_go(classes)
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
            # prefix with //export for C ABI
            emit_name = u.name.replace(".", "_")
            code = code.replace(f"func {emit_name}(", f"//export {emit_name}\nfunc {emit_name}(")
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
            wrapper = "func main() {\n\t" + entry_u.name + "()\n}\n"
        else:
            wrapper = f"func main() {{\n\t_ = {entry_u.name}()\n}}\n"
        fns.append(wrapper)
    elif not fns:
        # the entry function was rejected during emission; the pipeline
        # already holds the reason, so return what we have
        return prelude + "\n".join(fns), emitted
    else:
        # Go main() must have no arguments and no return values
        # Rename the user's main() to __ge_main() and add a wrapper
        if entry_u.ret_type != "None":
            fns[-1] = fns[-1].replace(f"func {entry_u.name}(", "func __ge_main(")
            wrapper = "func main() {\n\t__ge_main()\n}\n"
            fns.append(wrapper)
        else:
            fns[-1] = fns[-1].replace(f"func {entry_u.name}(", "func main(")

    program = prelude + "\n".join(fns) + "\n"
    # inject stdlib runtime (after package/imports, before functions)
    from ..stdlib import get_runtime
    runtime = get_runtime("go")
    if runtime:
        program = prelude + runtime + "\n" + "\n".join(fns) + "\n"
    return program, emitted
