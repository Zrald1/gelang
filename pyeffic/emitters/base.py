"""Shared AST->code walker. Backends supply a `Spec` of format strings."""
from __future__ import annotations

import ast
from dataclasses import dataclass

from ..analyzer import FuncUnit


def _ann_base(node: ast.Subscript) -> str:
    """Extract base type name from a subscript annotation like list[int]."""
    if isinstance(node.value, ast.Name):
        return node.value.id
    return "list"


@dataclass
class Spec:
    name: str
    types: dict[str, str]
    list_type: str  # e.g. "Vec<{T}>" with {T} placeholder
    list_param_type: str  # borrowed form for params, e.g. "&[i64]"
    list_elem_type: str  # scalar int type used as list element, e.g. "i64"/"int64_t"
    borrow_list_arg: bool  # prefix `&` at call sites for list args (Rust)
    range_call: str  # "({lo}..{hi})" / range step variant handled separately
    range_step_call: str
    len_call: str  # "{x}.len()" / "{x}.size()"
    print_int: str
    print_float: str
    print_str: str
    print_bool: str
    print_generic: str  # fallback
    int_cast: str  # "{x} as i64" / "static_cast<int64_t>({x})"
    float_cast: str  # "{x} as f64" / "static_cast<double>({x})"
    float_div: str  # how to render true division
    floor_div: str
    sum_call: str  # "{it}.sum()" / accumulate
    abs_int: str
    abs_float: str
    min_call: str
    max_call: str
    pow_call: str
    append_call: str  # "{x}.push({v})" / "{x}.push_back({v})"
    index_call: str  # "{x}[{i}]" (rust needs *no* change; cpp same)
    comment: str  # "//" or "//"
    fn_template: str  # full function template with {sig},{body}
    main_template: str  # program wrapper
    var_decl_template: str = "{nt} {target} = {val};"  # typed variable declaration
    ffi_prefix: str = ""  # decoration for C-ABI exports in library mode
    indent: str = "    "
    # Type-aware exponentiation. Integer `**` and float `**` need different
    # target syntax in most languages; when these are empty the emitter falls
    # back to pow_call.
    pow_int: str = ""
    pow_float: str = ""
    # two-argument min(a, b) / max(a, b). Most targets have no plain
    # min/max function, so these carry the target-specific spelling.
    min2_call: str = ""
    max2_call: str = ""
    # List slicing. `{x}` is the list, `{start}` and `{stop}` are integer
    # bounds. list_copy is the full-slice form (`xs[:]`), which Python
    # defines as a shallow copy.
    # str.split(sep) / sep.join(list). Empty means unsupported.
    str_split: str = ""
    str_join: str = ""
    list_slice: str = ""
    list_copy: str = ""
    # Iterating a dict in Python yields its keys. `dict_keys` is an
    # expression producing those keys; `foreach_dict_template` is the
    # loop head to use with it (Go ranges a map differently).
    dict_keys: str = ""
    foreach_dict_template: str = ""
    # Printing a sequence. Python renders lists as `[1, 2, 3]`, so every
    # backend must match that rather than its own native format.
    print_list: str = ""
    # string operations
    str_concat: str = "{l} + {r}"  # string concatenation
    str_len: str = "{x}.length()"  # string length (C++ style)
    str_index: str = "{x}[{i}]"  # string char index
    str_slice: str = "{x}.substr({start}, {len})"  # string slice (start, len)
    str_slice_start: str = "{x}.substr({start})"  # string slice from start
    str_slice_end: str = "{x}.substr(0, {end})"  # string slice to end
    # list concatenation (list + list -> new list)
    list_concat: str = "{l} + {r}"  # default; overridden per backend
    # for-in list iteration
    foreach_template: str = "for (auto {var} : {iter})"  # C++ style
    # try/except
    try_template: str = "try {{\n{body}\n}} catch (...) {{\n{handler}\n}}"
    # struct definition
    struct_template: str = "struct {name} {{\n{fields}\n}};"
    struct_field_template: str = "    {type} {name};"
    # whether if/while conditions need parentheses (C++/C#/Zig/Kotlin yes, Rust/Go no)
    condition_parens: bool = True
    struct_new_template: str = "{name} {name}_new({params}) {{\n{body}\n}}"
    # dict support
    dict_type: str = "std::map<std::string, {V}>"
    dict_get: str = "{d}.at({k})"
    dict_set: str = "{d}[{k}] = {v}"
    dict_contains: str = "({d}.find({k}) != {d}.end())"
    # tuple support
    tuple_type: str = "std::tuple<{T}>"
    set_type: str = ""  # native set type
    tuple_get: str = "std::get<{i}>({t})"
    # list length (separate from len_call which may be used for strings)
    list_len: str = "{x}.size()"


class Emitter:
    def __init__(self, spec: Spec):
        self.spec = spec
        self.lines: list[str] = []
        self.indent_lvl = 0
        # type environment for local vars (inferred from assignments)
        self.var_types: dict[str, str] = {}
        self.declared: set[str] = set()  # vars already given a `let`/type decl
        self.params: set[str] = set()  # param names (already borrowed if list)
        self.library_mode: bool = False  # emit C-ABI exports instead of a main()
        self.extern_names: set[str] = set()  # extern "C" fns from other backends
        # {name: ([param names], {param: default source text})} so a call site
        # that omits defaults can fill them in.
        self.func_signatures: dict[str, tuple[list[str], dict[str, str]]] = {}
        self.force_extern_c: bool = False  # force extern "C" on all functions (multi-backend)
        self.export_names: set[str] = set()  # Rust fns called from C++ — export them
        self.class_names: set[str] = set()  # known class names for constructor calls
        self.class_fields: dict[str, list[tuple[str, str]]] = {}  # class -> [(field, type)]
        self.func_mutated_params: dict[str, set[int]] = {}  # func name -> mutated param indices
        self.class_bases: dict[str, list[str]] = {}  # class -> [parent class names]
        self.class_properties: dict[str, list[str]] = {}  # class -> [property names]
        self.class_static_methods: dict[str, list[str]] = {}  # class -> [static method names]
        self.current_class: str = ""  # current class being emitted (for super())
        # Production: track unsupported emissions to prevent silent failures
        self.unsupported_emissions: list[str] = []  # list of unsupported features encountered
        self.current_func: str = ""  # current function being emitted
        # function return type lookup: "func_name" -> "int" or "Class.method" -> "int"
        self.func_return_types: dict[str, str] = {}
        # container element types: param name -> element type (e.g. "str" for list[str])
        self.param_elem_types: dict[str, str] = {}
        # dict key/value types: param name -> (key_type, value_type)
        # module-level constants: name -> value (for inlining into native code)
        self.constants: dict[str, object] = {}
        self.param_dict_types: dict[str, tuple[str, str]] = {}

    def emit(self, unit: FuncUnit, sig_override: str | None = None,
             body_suffix: str = "") -> str:
        self.lines = []
        self.indent_lvl = 1
        self.var_types = {}
        self.declared = set()
        self.params = set()
        self.mutated_params: set[str] = set()  # params that are reassigned (need `mut` in Rust)
        # track current class for super() calls
        self.current_class = unit.class_name if unit.is_method else ""
        # reset unsupported tracking for this function
        self.unsupported_emissions = []
        self.current_func = unit.name
        # load container element types for this function's params
        self.param_elem_types = getattr(unit, 'param_elem_types', {})
        self.param_dict_types = getattr(unit, 'param_dict_types', {})
        # check if this is a generator function (contains yield)
        is_generator = self._is_generator(unit.body)
        if is_generator:
            # transform yield statements into list appends
            unit = self._transform_generator(unit)
        # seed params (already declared by the signature)
        for pname, ptype in unit.params:
            self.var_types[pname] = ptype
            self.declared.add(pname)
            self.params.add(pname)
        # scan for parameter reassignments (Assign/AugAssign targeting a param)
        for node in ast.walk(unit.body):  # type: ignore[attr-defined]
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in self.params:
                        self.mutated_params.add(target.id)
                    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id in self.params:
                        # dict/list element assignment mutates the container
                        self.mutated_params.add(target.value.id)
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id in self.params:
                    self.mutated_params.add(node.target.id)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                # detect append() calls on list parameters
                if node.func.attr == "append" and isinstance(node.func.value, ast.Name):
                    if node.func.value.id in self.params:
                        self.mutated_params.add(node.func.value.id)
        # record which param indices are mutated (for call site borrow/deref)
        mutated_indices = set()
        for i, (pname, ptype) in enumerate(unit.params):
            if pname in self.mutated_params:
                mutated_indices.add(i)
        if mutated_indices:
            self.func_mutated_params[unit.name] = mutated_indices
        for stmt in unit.body.body:  # type: ignore[attr-defined]
            self.stmt(stmt)
        if body_suffix:
            self.lines.append(self.spec.indent * self.indent_lvl + body_suffix)
        body = "\n".join(self.lines)
        sig = sig_override if sig_override else self.signature(unit)
        return self.spec.fn_template.format(sig=sig, body=body, name=unit.name)

    # ---- signatures ----
    def py_to_native(self, t: str) -> str:
        if t in self.spec.types:
            return self.spec.types[t]
        if t == "list":
            return self.spec.list_type.format(T=self.spec.list_elem_type)
        if t == "dict":
            return self.spec.dict_type.format(V=self.spec.list_elem_type)
        if t == "tuple":
            return self.spec.tuple_type.format(T=self.spec.list_elem_type)
        if t == "set":
            if self.spec.set_type:
                return self.spec.set_type
            return self.spec.list_type.format(T=self.spec.list_elem_type)
        # class type — use the class name directly
        if t in self.class_names:
            return t
        # unknown type — default to float
        return self.spec.types["float"]

    def _native_elem_type(self, py_type: str) -> str:
        """Get the native element type for a Python type."""
        return self.spec.types.get(py_type, self.spec.list_elem_type)

    def param_native_type(self, t: str, pname: str = "") -> str:
        """Native type for a function parameter (lists borrowed)."""
        if t == "list":
            if pname and pname in self.param_elem_types:
                # heterogeneous list: use the element type from annotations
                elem_t = self._native_elem_type(self.param_elem_types[pname])
                if self.spec.name == "rust":
                    return f"&[{elem_t}]"
                return self.spec.list_type.format(T=elem_t)
            return self.spec.list_param_type
        if t == "dict":
            if pname and pname in self.param_dict_types:
                key_t, val_t = self.param_dict_types[pname]
                native_key = self._native_elem_type(key_t)
                native_val = self._native_elem_type(val_t)
                # Use backend-specific dict type with heterogeneous key/value types
                if self.spec.name == "rust":
                    return f"&std::collections::HashMap<{native_key}, {native_val}>"
                if self.spec.name == "cpp":
                    return f"const std::map<{native_key}, {native_val}>&"
                if self.spec.name == "csharp":
                    return f"Dictionary<{native_key}, {native_val}>"
                if self.spec.name == "go":
                    return f"map[{native_key}]{native_val}"
                if self.spec.name == "kotlin":
                    return f"Map<{native_key}, {native_val}>"
                if self.spec.name == "zig":
                    return f"*const std.AutoHashMap({native_key}, {native_val})"
            return self.spec.dict_type.format(V=self.spec.list_elem_type)
        if t == "tuple":
            return self.spec.tuple_type.format(T=self.spec.list_elem_type)
        if t == "set":
            if self.spec.set_type:
                if self.spec.name == "cpp":
                    return f"const {self.spec.set_type}&"
                return self.spec.set_type
            return self.spec.list_param_type
        # class type — pass by value (or const ref in C++)
        if t in self.class_names:
            if self.spec.name == "cpp":
                return f"const {t}&"
            return t
        return self.py_to_native(t)

    def signature(self, unit: FuncUnit) -> str:
        # method names use underscore: ClassName.method -> ClassName_method
        emit_name = unit.name.replace(".", "_")
        params = []
        for pname, ptype in unit.params:
            nt = self.param_native_type(ptype, pname)
            ident = self._ident(pname)
            if self.spec.name == "rust":
                # add `mut` for params that are reassigned in the body
                if ptype == "list" and pname in self.mutated_params:
                    # mutated list params need &mut Vec<T> instead of &[T]
                    elem_t = self._native_elem_type(self.param_elem_types.get(pname, "int"))
                    nt = f"&mut {self.spec.list_type.format(T=elem_t)}"
                    params.append(f"{ident}: {nt}")
                else:
                    mut_prefix = "mut " if pname in self.mutated_params else ""
                    params.append(f"{mut_prefix}{ident}: {nt}")
            else:
                params.append(f"{nt} {ident}")
        params_s = ", ".join(params)
        if unit.ret_type == "None":
            base_sig = (f"fn {emit_name}({params_s})" if self.spec.name == "rust"
                        else f"void {emit_name}({params_s})")
        else:
            ret = self.py_to_native(unit.ret_type)
            base_sig = (f"fn {emit_name}({params_s}) -> {ret}" if self.spec.name == "rust"
                        else f"{ret} {emit_name}({params_s})")
        if self.library_mode and getattr(unit, "ffi_export", False) and self.spec.ffi_prefix:
            return self.spec.ffi_prefix + base_sig
        if self.force_extern_c and self.spec.ffi_prefix:
            return self.spec.ffi_prefix + base_sig
        # export Rust functions that are called from C++ (cross-backend)
        if unit.name in self.export_names and self.spec.ffi_prefix:
            return self.spec.ffi_prefix + base_sig
        return base_sig

    # ---- statements ----
    def stmt(self, node: ast.AST) -> None:
        ind = self.spec.indent * self.indent_lvl
        if isinstance(node, ast.Return):
            if node.value is None:
                self.lines.append(f"{ind}return;")
            else:
                # in Rust, returning a mutated list param (&mut Vec) from a
                # function that returns Vec requires cloning
                if (self.spec.name == "rust" and isinstance(node.value, ast.Name)
                        and node.value.id in self.mutated_params
                        and self.var_types.get(node.value.id) == "list"):
                    self.lines.append(f"{ind}return (*{node.value.id}).clone();")
                else:
                    self.lines.append(f"{ind}return {self.expr(node.value)};")
        elif isinstance(node, ast.Assign):
            target = node.targets[0]
            val = self.expr(node.value)
            if isinstance(target, ast.Tuple):
                # tuple unpacking: a, b = expr
                self._tuple_unpack(target, node.value, ind)
            elif isinstance(target, ast.Name):
                t = self.infer_type(node.value)
                self.var_types[target.id] = t
                nt = self.py_to_native(t)
                if target.id in self.declared:
                    # in Rust, assigning to a mutated list param (&mut Vec)
                    # requires dereferencing: *graph = value
                    if (self.spec.name == "rust" and target.id in self.mutated_params
                            and self.var_types.get(target.id) == "list"):
                        self.lines.append(f"{ind}*{self._ident(target.id)} = {val};")
                    else:
                        self.lines.append(f"{ind}{self._ident(target.id)} = {val};")
                else:
                    self.declared.add(target.id)
                    if self.spec.name == "rust":
                        self.lines.append(f"{ind}let mut {self._ident(target.id)}: {nt} = {val};")
                    else:
                        decl = self.spec.var_decl_template.format(
                            nt=nt, target=self._ident(target.id), val=val)
                        self.lines.append(f"{ind}{decl}")
            elif isinstance(target, ast.Subscript):
                target_type = self.infer_type(target.value)
                if target_type == "dict":
                    key = self.expr(target.slice)
                    d = self.expr(target.value)
                    self.lines.append(f"{ind}{self.spec.dict_set.format(d=d, k=key, v=val)};")
                else:
                    self.lines.append(f"{ind}{self.expr(target)} = {val};")
            elif isinstance(target, ast.Attribute):
                # self.field = value -> self.field = value (struct field assignment)
                self.lines.append(f"{ind}{self.expr(target)} = {val};")
            else:
                self.lines.append(f"{ind}// unsupported assign target")
        elif isinstance(node, ast.AugAssign):
            target = self.expr(node.target)
            op = self.binop_symbol(node.op)
            self.lines.append(f"{ind}{target} {op}= {self.expr(node.value)};")
        elif isinstance(node, ast.AnnAssign):
            if node.value is None:
                if isinstance(node.target, ast.Name):
                    t = self._ann_type(node.annotation)
                    self.var_types[node.target.id] = t
                    self.declared.add(node.target.id)
                return
            target = node.target.id if isinstance(node.target, ast.Name) else self.expr(node.target)
            t = self._ann_type(node.annotation) if isinstance(node.target, ast.Name) else self.infer_type(node.value)
            if isinstance(node.target, ast.Name):
                self.var_types[target] = t
                self.declared.add(target)
            nt = self.py_to_native(t)
            if t == "list":
                # a bare `list` annotation carries no element type; take it
                # from the value so `xs = "a,b".split(",")` is a string list
                elem = self._list_elem_of_value(node.value)
                if elem and elem != self.spec.list_elem_type:
                    nt = self.spec.list_type.format(T=elem)
            if self.spec.name == "rust":
                self.lines.append(f"{ind}let mut {target}: {nt} = {self.expr(node.value)};")
            else:
                decl = self.spec.var_decl_template.format(
                    nt=nt, target=target, val=self.expr(node.value))
                self.lines.append(f"{ind}{decl}")
        elif isinstance(node, ast.If):
            # Type narrowing: if test is isinstance(x, T), narrow x to T in the if branch
            narrowed_var, narrowed_type = self._extract_isinstance_narrowing(node.test)
            saved_type = None
            if narrowed_var and narrowed_type:
                saved_type = self.var_types.get(narrowed_var)
                self.var_types[narrowed_var] = narrowed_type
            self.lines.append(f"{ind}if {self._condition(node.test)} {{")
            self.indent_lvl += 1
            for s in node.body:
                self.stmt(s)
            self.indent_lvl -= 1
            # Restore type after the if branch (else branch should not have narrowed type)
            if narrowed_var and narrowed_type and saved_type is not None:
                self.var_types[narrowed_var] = saved_type
            elif narrowed_var and narrowed_type:
                self.var_types.pop(narrowed_var, None)
            if node.orelse:
                # elif chains: ast nests elif as If inside orelse
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
            self.lines.append(f"{ind}while {self._condition(node.test)} {{")
            self.indent_lvl += 1
            for s in node.body:
                self.stmt(s)
            self.indent_lvl -= 1
            self.lines.append(f"{ind}}}")
        elif isinstance(node, ast.With):
            self._with_stmt(node, ind)
        elif isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Call):
                self.lines.append(f"{ind}{self.expr(node.value)};")
            # else: bare expression -> ignore (docstrings etc.)
        elif isinstance(node, ast.Pass):
            pass
        elif isinstance(node, ast.Break):
            self.lines.append(f"{ind}break;")
        elif isinstance(node, ast.Continue):
            self.lines.append(f"{ind}continue;")
        elif isinstance(node, ast.Try):
            self._try_stmt(node, ind)
        elif isinstance(node, ast.Delete):
            self._delete_stmt(node, ind)
        elif isinstance(node, ast.Raise):
            self._raise_stmt(node, ind)
        elif isinstance(node, ast.Assert):
            self._assert_stmt(node, ind)
        elif isinstance(node, ast.Match):
            self._match_stmt(node, ind)
        elif isinstance(node, ast.ClassDef):
            # struct/class definitions are handled at program level, not in function bodies
            pass
        else:
            self._mark_unsupported(f"statement {type(node).__name__}")
            self.lines.append(f"{ind}// unsupported stmt: {type(node).__name__}")

    def _delete_stmt(self, node: ast.Delete, ind: str) -> None:
        """Emit del statement — for list/dict element removal."""
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                base = self.expr(target.value)
                idx = self.expr(target.slice)
                if self.spec.name == "rust":
                    self.lines.append(f"{ind}{base}.remove({idx} as usize);")
                elif self.spec.name == "cpp":
                    self.lines.append(f"{ind}{base}.erase({base}.begin() + {idx});")
                elif self.spec.name == "csharp":
                    self.lines.append(f"{ind}{base}.RemoveAt((int)({idx}));")
                elif self.spec.name == "go":
                    self.lines.append(f"{ind}{base} = append({base}[:{idx}], {base}[{idx}+1:]...)")
                elif self.spec.name == "kotlin":
                    self.lines.append(f"{ind}{base}.removeAt({idx}.toInt())")
                else:
                    self.lines.append(f"{ind}// del {base}[{idx}]")
            elif isinstance(target, ast.Name):
                # del var — just mark as removed (in native, can't truly delete)
                self.lines.append(f"{ind}// del {target.id}")
            elif isinstance(target, ast.Attribute):
                base = self.expr(target.value)
                self.lines.append(f"{ind}// del {base}.{target.attr}")

    def _raise_stmt(self, node: ast.Raise, ind: str) -> None:
        """Emit raise statement as a panic/throw."""
        exc_name = ""
        if node.exc:
            if isinstance(node.exc, ast.Name):
                exc_name = node.exc.id
            elif isinstance(node.exc, ast.Call):
                exc_name = getattr(node.exc.func, "id", "Exception")
            else:
                exc_name = "Exception"
        msg = '"GE runtime error"'
        if node.exc and isinstance(node.exc, ast.Call) and node.exc.args:
            msg = self.expr(node.exc.args[0])
        if self.spec.name == "rust":
            self.lines.append(f'{ind}panic!("{exc_name}: {{}}", {msg});')
        elif self.spec.name == "cpp":
            self.lines.append(f'{ind}throw std::runtime_error("{exc_name}");')
        elif self.spec.name == "csharp":
            self.lines.append(f'{ind}throw new System.Exception("{exc_name}");')
        elif self.spec.name == "go":
            self.lines.append(f'{ind}panic("{exc_name}")')
        elif self.spec.name == "kotlin":
            self.lines.append(f'{ind}throw RuntimeException("{exc_name}")')
        elif self.spec.name == "zig":
            self.lines.append(f'{ind}std.debug.panic("{exc_name}", .{{}});')
        else:
            self.lines.append(f'{ind}// raise {exc_name}')

    def _assert_stmt(self, node: ast.Assert, ind: str) -> None:
        """Emit assert statement."""
        cond = self._condition(node.test)
        msg = ""
        if node.msg:
            msg = self.expr(node.msg)
        if self.spec.name == "rust":
            if msg:
                self.lines.append(f'{ind}assert!({cond}, "{msg}");')
            else:
                self.lines.append(f"{ind}assert!({cond});")
        elif self.spec.name == "cpp":
            self.lines.append(f"{ind}assert({cond});")
        elif self.spec.name == "csharp":
            self.lines.append(f"{ind}System.Diagnostics.Debug.Assert({cond});")
        elif self.spec.name == "go":
            self.lines.append(f"{ind}if !({cond}) {{ panic(\"assertion failed\") }}")
        elif self.spec.name == "kotlin":
            self.lines.append(f"{ind}assert({cond})")
        elif self.spec.name == "zig":
            self.lines.append(f"{ind}std.debug.assert({cond});")
        else:
            self.lines.append(f"{ind}// assert {cond}")

    def _match_stmt(self, node: ast.Match, ind: str) -> None:
        """Lower Python 3.10+ match statement to if-else chains."""
        subject = self.expr(node.subject)
        # Use a temp variable for the subject
        subj_var = "__match_subj"
        if self.spec.name == "rust":
            self.lines.append(f"{ind}let {subj_var} = {subject};")
        elif self.spec.name in ("cpp", "csharp", "kotlin"):
            self.lines.append(f"{ind}auto {subj_var} = {subject};")
        elif self.spec.name == "go":
            self.lines.append(f"{ind}{subj_var} := {subject}")
        elif self.spec.name == "zig":
            self.lines.append(f"{ind}const {subj_var} = {subject};")
        else:
            self.lines.append(f"{ind}var {subj_var} = {subject};")
        first = True
        for case in node.cases:
            pattern = case.pattern
            guard = case.guard
            body = case.body
            # Build condition from pattern
            cond = self._match_pattern(pattern, subj_var)
            if guard:
                cond = f"({cond} && {self._condition(guard)})"
            if first:
                self.lines.append(f"{ind}if {cond} {{")
                first = False
            else:
                self.lines.append(f"{ind}}} else if {cond} {{")
            self.indent_lvl += 1
            for s in body:
                self.stmt(s)
            self.indent_lvl -= 1
        # wildcard case (case _:) becomes else
        has_wildcard = any(
            isinstance(c.pattern, ast.MatchAs) and c.pattern.pattern is None
            for c in node.cases
        )
        if has_wildcard:
            self.lines.append(f"{ind}}} else {{")
            self.indent_lvl += 1
            for case in node.cases:
                if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None:
                    for s in case.body:
                        self.stmt(s)
                    break
            self.indent_lvl -= 1
        self.lines.append(f"{ind}}}")

    def _match_pattern(self, pattern: ast.AST, subj: str) -> str:
        """Convert a match pattern to a boolean condition."""
        if isinstance(pattern, ast.MatchValue):
            return f"({subj} == {self.expr(pattern.value)})"
        if isinstance(pattern, ast.MatchAs):
            if pattern.pattern is None:
                return "true"  # wildcard
            return self._match_pattern(pattern.pattern, subj)
        if isinstance(pattern, ast.MatchOr):
            parts = [self._match_pattern(p, subj) for p in pattern.patterns]
            return "(" + " || ".join(parts) + ")"
        if isinstance(pattern, ast.MatchSequence):
            # match [a, b]: check length and bind elements
            return f"true"  # simplified
        if isinstance(pattern, ast.MatchClass):
            cls = getattr(pattern.cls, "id", "Unknown")
            return f"/*isinstance({subj}, {cls})*/"
        return "true"

    def _try_stmt(self, node: ast.Try, ind: str) -> None:
        """Emit try/except/finally with backend-appropriate semantics.

        Based on research:
        - C++/C#/Kotlin: use try/catch/finally (native exception support)
        - Rust: use std::panic::catch_unwind with Result type
        - Go/Zig: mark as unsupported (no exception mechanism)
        """
        if self.spec.name == "rust":
            self._try_stmt_rust(node, ind)
        elif self.spec.name in ("cpp", "csharp", "kotlin"):
            self._try_stmt_native(node, ind)
        else:
            # Go and Zig don't have exceptions — mark as unsupported
            self._mark_unsupported("try/except (no exceptions in target language)")
            self.lines.append(f"{ind}// unsupported: try/except not available in {self.spec.name}")

    def _try_stmt_native(self, node: ast.Try, ind: str) -> None:
        """Emit try/catch/finally for C++/C#/Kotlin (native exception support)."""
        self.lines.append(f"{ind}try {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        if node.handlers:
            # C++/C# use catch, Kotlin uses catch
            catch_kw = "catch" if self.spec.name != "kotlin" else "catch"
            for handler in node.handlers:
                exc_name = ""
                if handler.type and isinstance(handler.type, ast.Name):
                    exc_name = handler.type.id
                if self.spec.name == "kotlin":
                    self.lines.append(f"{ind}}} {catch_kw} (e: Exception) {{")
                elif self.spec.name == "csharp":
                    self.lines.append(f"{ind}}} {catch_kw} (Exception e) {{")
                else:
                    self.lines.append(f"{ind}}} {catch_kw} (...) {{")
                self.indent_lvl += 1
                if handler.name:
                    # bind the exception variable
                    if self.spec.name == "kotlin":
                        self.lines.append(f"{ind}val {handler.name} = e")
                    elif self.spec.name == "csharp":
                        self.lines.append(f"{ind}var {handler.name} = e")
                for s in handler.body:
                    self.stmt(s)
                self.indent_lvl -= 1
        else:
            self.lines.append(f"{ind}}} catch (...) {{")
            self.indent_lvl += 1
            self.lines.append(f"{ind}// catch-all")
            self.indent_lvl -= 1
        self.lines.append(f"{ind}}}")
        # finally block
        if node.finalbody:
            if self.spec.name == "kotlin":
                self.lines.append(f"{ind}finally {{")
            else:
                self.lines.append(f"{ind}// finally:")
            self.indent_lvl += 1
            for s in node.finalbody:
                self.stmt(s)
            self.indent_lvl -= 1
            if self.spec.name == "kotlin":
                self.lines.append(f"{ind}}}")

    def _try_stmt_rust(self, node: ast.Try, ind: str) -> None:
        """Emit try/except for Rust using std::panic::catch_unwind.

        Based on py2many and Rust best practices:
        - try body wrapped in catch_unwind closure
        - except handlers check the Result
        - finally runs after the match
        """
        self.lines.append(f"{ind}let __result = std::panic::catch_unwind(|| {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        self.lines.append(f"{ind}}});")
        if node.handlers:
            self.lines.append(f"{ind}if let Err(__e) = __result {{")
            self.indent_lvl += 1
            for s in node.handlers[0].body:
                self.stmt(s)
            self.indent_lvl -= 1
            self.lines.append(f"{ind}}}")
        if node.finalbody:
            for s in node.finalbody:
                self.stmt(s)

    def _extract_isinstance_narrowing(self, test: ast.AST) -> tuple[str, str]:
        """Extract type narrowing from isinstance checks.

        Based on mypy's type narrowing: isinstance(x, int) in an if branch
        narrows x to int within that branch.

        Returns (var_name, narrowed_type) or ("", "") if no narrowing applies.
        """
        # isinstance(x, T) -> narrow x to T
        if (isinstance(test, ast.Call) and
            isinstance(test.func, ast.Name) and
            test.func.id == "isinstance" and
            len(test.args) == 2 and
            isinstance(test.args[0], ast.Name) and
            isinstance(test.args[1], ast.Name)):
            var_name = test.args[0].id
            type_name = test.args[1].id
            if type_name in ("int", "float", "bool", "str", "list", "dict", "tuple", "set"):
                return (var_name, type_name)
            if type_name in self.class_names:
                return (var_name, type_name)
        # x is not None -> narrow x to its non-optional form
        if (isinstance(test, ast.Compare) and
            len(test.ops) == 1 and
            isinstance(test.ops[0], ast.IsNot) and
            isinstance(test.left, ast.Name) and
            len(test.comparators) == 1 and
            isinstance(test.comparators[0], ast.Constant) and
            test.comparators[0].value is None):
            var_name = test.left.id
            current_type = self.var_types.get(var_name, "")
            # If current type is Optional-like, narrow to the base type
            if current_type.startswith("Optional["):
                return (var_name, current_type[9:-1])
            return ("", "")
        return ("", "")

    def _tuple_unpack(self, target: ast.Tuple, value: ast.AST, ind: str) -> None:
        """Handle tuple unpacking: a, b = expr"""
        n = len(target.elts)
        if isinstance(value, ast.Tuple) and len(value.elts) == n:
            # a, b = 1, 2 — direct assignment
            for t, v in zip(target.elts, value.elts):
                v_str = self.expr(v)
                t_type = self.infer_type(v)
                self.var_types[t.id] = t_type
                nt = self.py_to_native(t_type)
                if t.id in self.declared:
                    self.lines.append(f"{ind}{t.id} = {v_str};")
                else:
                    self.declared.add(t.id)
                    if self.spec.name == "rust":
                        self.lines.append(f"{ind}let mut {t.id}: {nt} = {v_str};")
                    else:
                        decl = self.spec.var_decl_template.format(nt=nt, target=t.id, val=v_str)
                        self.lines.append(f"{ind}{decl}")
        else:
            # a, b = func() — use tuple element access
            val_str = self.expr(value)
            # declare a temp tuple variable
            tmp = "__tup"
            if self.spec.name == "rust":
                self.lines.append(f"{ind}let {tmp} = {val_str};")
            elif self.spec.name in ("cpp", "csharp", "kotlin"):
                self.lines.append(f"{ind}auto {tmp} = {val_str};")
            elif self.spec.name == "go":
                self.lines.append(f"{ind}{tmp} := {val_str}")
            elif self.spec.name == "zig":
                self.lines.append(f"{ind}const {tmp} = {val_str};")
            else:
                self.lines.append(f"{ind}var {tmp} = {val_str};")
            for i, t in enumerate(target.elts):
                if self.spec.name == "rust":
                    access = f"{tmp}.{i}"
                elif self.spec.name == "cpp":
                    access = f"std::get<{i}>({tmp})"
                elif self.spec.name == "csharp":
                    access = f"{tmp}.Item{i+1}"
                elif self.spec.name == "go":
                    field = chr(97 + i)
                    access = f"{tmp}.{field}"
                elif self.spec.name == "kotlin":
                    field = "first" if i == 0 else "second" if i == 1 else f"component{i+1}"
                    access = f"{tmp}.{field}"
                else:
                    access = f"{tmp}[{i}]"
                self.var_types[t.id] = "int"
                self.declared.add(t.id)
                nt = self.py_to_native("int")
                if self.spec.name == "rust":
                    self.lines.append(f"{ind}let mut {t.id}: {nt} = {access};")
                else:
                    decl = self.spec.var_decl_template.format(nt=nt, target=t.id, val=access)
                    self.lines.append(f"{ind}{decl}")

    def _find_parent_class(self) -> str:
        """Find the first parent class of the current class for super() calls."""
        bases = self.class_bases.get(self.current_class, [])
        return bases[0] if bases else ""

    def _mark_unsupported(self, feature: str) -> str:
        """Track an unsupported feature emission. Returns a comment string.

        Production: instead of silently emitting wrong code, we track every
        unsupported feature so the pipeline can mark the function as
        unsupported and fall back to CPython.
        """
        msg = f"{self.current_func}: {feature}"
        if msg not in self.unsupported_emissions:
            self.unsupported_emissions.append(msg)
        # Use the backend's own comment syntax: a C-style comment is not
        # valid in Zig, and the placeholder still has to parse.
        marker = getattr(self.spec, "comment", "//") or "//"
        if marker.startswith("/*"):
            return f"/*unsupported: {feature}*/"
        return f"{marker} unsupported: {feature}"

    def _ident(self, name: str) -> str:
        """Escape a local/parameter name that collides with a target keyword.

        Function names are handled earlier, in the shared IR, because they can
        cross the C ABI; locals never do, so each backend uses its own idiom
        (`@base` in C#, `r#match` in Rust, `base_` in C++).
        """
        from ..idents import escape_local
        return escape_local(name, self.spec.name)

    def _condition(self, node: ast.AST) -> str:
        """Convert a Python truthy condition to a native boolean expression.
        
        Python allows 'if flag:' where flag is an int, but most compiled
        languages require an explicit comparison. This converts bare int
        expressions to 'expr != 0'.
        """
        # Already a comparison or bool op — leave as-is
        if isinstance(node, (ast.Compare, ast.BoolOp)):
            cond = self.expr(node)
        # Unary not — leave as-is
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            cond = self.expr(node)
        else:
            # Bare expression — check if it's an int
            t = self.infer_type(node)
            if t == "int":
                zero = self._zero_literal()
                cond = f"({self.expr(node)} != {zero})"
            elif t == "bool":
                cond = self.expr(node)
            else:
                # Default: wrap in comparison for safety
                zero = self._zero_literal()
                cond = f"({self.expr(node)} != {zero})"
        # C-like backends (C++/C#/Zig/Kotlin) need parentheses around the condition
        if getattr(self.spec, "condition_parens", True):
            return f"({cond})"
        return cond

    def _zero_literal(self) -> str:
        """Return the zero literal for this backend's int type."""
        if self.spec.name == "kotlin":
            return "0L"
        return "0"

    def _elif(self, node: ast.If) -> str:
        head = f"if {self._condition(node.test)} {{"
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
                tail = " } else {\n" + "\n".join(self.lines) + "\n" + self.spec.indent * self.indent_lvl + "}"
                self.lines = save2
        else:
            tail = "\n" + self.spec.indent * self.indent_lvl + "}"
        return head + "\n" + body + tail

    def for_loop(self, node: ast.For, ind: str) -> None:
        var = node.target.id if isinstance(node.target, ast.Name) else "_"
        is_tuple_target = isinstance(node.target, ast.Tuple)
        it = node.iter
        if isinstance(it, ast.Call) and getattr(it.func, "id", None) == "range":
            args = it.args
            if len(args) == 1:
                hi = self.expr(args[0])
                head = self.spec.range_call.format(lo="0", hi=hi, step="1")
            elif len(args) == 2:
                lo = self.expr(args[0])
                hi = self.expr(args[1])
                head = self.spec.range_call.format(lo=lo, hi=hi, step="1")
            else:
                lo = self.expr(args[0])
                hi = self.expr(args[1])
                step = self.expr(args[2])
                head = self.spec.range_step_call.format(lo=lo, hi=hi, step=step)
            self.var_types[var] = "int"
            self.lines.append(f"{ind}for {var} in {head} {{")
        elif isinstance(it, ast.Call) and getattr(it.func, "id", None) == "enumerate" and is_tuple_target:
            # for i, x in enumerate(items):
            self._for_enumerate(node, ind)
            return
        elif isinstance(it, ast.Call) and getattr(it.func, "id", None) == "zip" and is_tuple_target:
            # for a, b in zip(x, y):
            self._for_zip(node, ind)
            return
        else:
            # iterate a container
            iter_s = self.expr(it)
            if self.infer_type(it) == "dict" and self.spec.dict_keys:
                # Python iterates dict keys, not (key, value) pairs
                iter_s = self.spec.dict_keys.format(x=iter_s)
                tmpl = (self.spec.foreach_dict_template
                        or self.spec.foreach_template)
                self.var_types[var] = "str"
                head = tmpl.format(var=var, iter=iter_s,
                                   etype=self.spec.list_elem_type)
            else:
                elem_type = self._iter_elem_type(it)
                self.var_types[var] = elem_type
                head = self.spec.foreach_template.format(
                    var=var, iter=iter_s, etype=self.spec.list_elem_type)
            self.lines.append(f"{ind}{head} {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        self.lines.append(f"{ind}}}")

    def _for_enumerate(self, node: ast.For, ind: str) -> None:
        """Handle: for i, x in enumerate(items):"""
        target = node.target  # ast.Tuple
        idx_var = target.elts[0].id
        val_var = target.elts[1].id
        it = self.expr(node.iter.args[0])
        self.var_types[idx_var] = "int"
        self.var_types[val_var] = "int"
        if self.spec.name == "rust":
            self.lines.append(f"{ind}for ({idx_var}, {val_var}) in {it}.iter().enumerate() {{")
        elif self.spec.name == "cpp":
            self.lines.append(f"{ind}for (int64_t {idx_var} = 0; auto& {val_var} : {it}) {{")
        elif self.spec.name == "csharp":
            self.lines.append(f"{ind}foreach (var __pair in {it}.Select((x, i) => (i, x))) {{")
            self.lines.append(f"{ind}    var {idx_var} = __pair.Item1; var {val_var} = __pair.Item2;")
        elif self.spec.name == "go":
            self.lines.append(f"{ind}for {idx_var}, {val_var} := range {it} {{")
        elif self.spec.name == "kotlin":
            self.lines.append(f"{ind}for ((__i, {val_var}) in {it}.withIndex()) {{")
            self.lines.append(f"{ind}    var {idx_var} = __i.toLong()")
        elif self.spec.name == "zig":
            self.lines.append(f"{ind}for ({it}, 0..) |{val_var}, {idx_var}| {{")
        else:
            self.lines.append(f"{ind}// unsupported enumerate for-loop")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        self.lines.append(f"{ind}}}")

    def _for_zip(self, node: ast.For, ind: str) -> None:
        """Handle: for a, b in zip(x, y):"""
        target = node.target  # ast.Tuple
        var_a = target.elts[0].id
        var_b = target.elts[1].id
        it_a = self.expr(node.iter.args[0])
        it_b = self.expr(node.iter.args[1])
        self.var_types[var_a] = "int"
        self.var_types[var_b] = "int"
        if self.spec.name == "rust":
            self.lines.append(f"{ind}for ({var_a}, {var_b}) in {it_a}.iter().zip({it_b}.iter()) {{")
        elif self.spec.name == "cpp":
            self.lines.append(f"{ind}for (int64_t __i = 0; __i < (int64_t)std::min({it_a}.size(), {it_b}.size()); __i++) {{")
            self.lines.append(f"{ind}    int64_t {var_a} = {it_a}[__i]; int64_t {var_b} = {it_b}[__i];")
        elif self.spec.name == "csharp":
            self.lines.append(f"{ind}foreach (var __pair in {it_a}.Zip({it_b}, (a, b) => (a, b))) {{")
            self.lines.append(f"{ind}    var {var_a} = __pair.Item1; var {var_b} = __pair.Item2;")
        elif self.spec.name == "go":
            self.lines.append(f"{ind}for __i := int64(0); __i < int64(len({it_a})) && __i < int64(len({it_b})); __i++ {{")
            self.lines.append(f"{ind}    {var_a} := {it_a}[__i]; {var_b} := {it_b}[__i]")
        elif self.spec.name == "kotlin":
            self.lines.append(f"{ind}for (__pair in {it_a}.zip({it_b})) {{")
            self.lines.append(f"{ind}    var {var_a} = __pair.first; var {var_b} = __pair.second")
        elif self.spec.name == "zig":
            self.lines.append(f"{ind}var __i: usize = 0;")
            self.lines.append(f"{ind}while (__i < {it_a}.len and __i < {it_b}.len) : (__i += 1) {{")
            self.lines.append(f"{ind}    const {var_a} = {it_a}[__i]; const {var_b} = {it_b}[__i];")
        else:
            self.lines.append(f"{ind}// unsupported zip for-loop")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        self.lines.append(f"{ind}}}")

    def _iter_elem_type(self, it: ast.AST) -> str:
        """Infer element type of an iterable."""
        t = self.infer_type(it)
        if t == "list":
            return "int"
        if t == "str":
            return "str"
        return "int"

    # ---- expressions ----
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
                if self.spec.name == "rust":
                    return f'String::from("{v.replace(chr(34), chr(92)+chr(34))}")'
                return '"' + v.replace('"', '\\"') + '"'
            if v is None:
                return "()" if self.spec.name == "rust" else "nullptr"
        if isinstance(node, ast.JoinedStr):
            return self._fstring(node)
        if isinstance(node, ast.Lambda):
            return self._lambda(node)
        if isinstance(node, ast.Name):
            # rename self -> _self (self is reserved in Rust)
            if node.id == "self":
                return "_self"
            # inline module-level constants
            if node.id in self.constants:
                val = self.constants[node.id]
                if isinstance(val, bool):
                    return "true" if val else "false"
                if isinstance(val, int):
                    return str(val)
                if isinstance(val, float):
                    return str(val)
                if isinstance(val, str):
                    if self.spec.name == "rust":
                        return f'String::from("{val}")'
                    return f'"{val}"'
            return self._ident(node.id)
        if isinstance(node, ast.BinOp):
            left = self.expr(node.left)
            right = self.expr(node.right)
            if isinstance(node.op, ast.Div):
                return self.spec.float_div.format(l=left, r=right)
            if isinstance(node.op, ast.FloorDiv):
                return self.spec.floor_div.format(l=left, r=right)
            if isinstance(node.op, ast.Pow):
                return self._pow(left, right, node)
            if isinstance(node.op, ast.Add):
                lt = self.infer_type(node.left)
                rt = self.infer_type(node.right)
                if lt == "str" or rt == "str":
                    return self.spec.str_concat.format(l=left, r=right)
                if lt == "list" or rt == "list":
                    return self.spec.list_concat.format(l=left, r=right)
            return f"({left} {self.binop_symbol(node.op)} {right})"
        if isinstance(node, ast.UnaryOp):
            operand = self.expr(node.operand)
            if isinstance(node.op, ast.USub):
                return f"(-{operand})"
            if isinstance(node.op, ast.UAdd):
                return f"(+{operand})"
            if isinstance(node.op, ast.Not):
                return f"(!{operand})"
        if isinstance(node, ast.BoolOp):
            op = "&&" if isinstance(node.op, ast.And) else "||"
            parts = [self.expr(v) for v in node.values]
            return "(" + f" {op} ".join(parts) + ")"
        if isinstance(node, ast.Compare):
            left = self.expr(node.left)
            left_type = self.infer_type(node.left)
            parts = []
            cur = left
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)):
                    right = self.expr(comp)
                    right_type = self.infer_type(comp)
                    if right_type == "dict":
                        contains = self.spec.dict_contains.format(d=right, k=cur)
                        if isinstance(op, ast.NotIn):
                            parts.append(f"(!{contains})")
                        else:
                            parts.append(contains)
                    elif right_type == "list":
                        # list membership: use contains/find
                        if self.spec.name == "rust":
                            contains = f"{right}.iter().any(|&x| x == {cur})"
                        elif self.spec.name == "cpp":
                            contains = f"(std::find({right}.begin(), {right}.end(), {cur}) != {right}.end())"
                        elif self.spec.name == "csharp":
                            contains = f"{right}.Contains({cur})"
                        elif self.spec.name == "zig":
                            contains = f"contains(i64, {right}, {cur})"
                        elif self.spec.name == "go":
                            contains = f"contains({right}, {cur})"
                        elif self.spec.name == "kotlin":
                            contains = f"{right}.contains({cur})"
                        else:
                            contains = f"/*contains*/"
                        if isinstance(op, ast.NotIn):
                            parts.append(f"(!{contains})")
                        else:
                            parts.append(contains)
                    else:
                        # string contains
                        if self.spec.name == "rust":
                            contains = f"{right}.contains({cur})"
                        elif self.spec.name == "cpp":
                            contains = f"({right}.find({cur}) != std::string::npos)"
                        elif self.spec.name == "csharp":
                            contains = f"{right}.Contains({cur})"
                        elif self.spec.name == "go":
                            contains = f"strContains({right}, {cur})"
                        elif self.spec.name == "kotlin":
                            contains = f"{right}.contains({cur})"
                        else:
                            contains = f"/*contains*/"
                        if isinstance(op, ast.NotIn):
                            parts.append(f"(!{contains})")
                        else:
                            parts.append(contains)
                    cur = self.expr(comp)
                else:
                    sym = self.cmp_symbol(op)
                    right = self.expr(comp)
                    parts.append(f"({cur} {sym} {right})")
                    cur = right
            return "(" + " && ".join(parts) + ")"
        if isinstance(node, ast.IfExp):
            # ternary: x if cond else y
            cond = self._condition(node.test)
            body = self.expr(node.body)
            orelse = self.expr(node.orelse)
            if self.spec.name == "rust":
                return f"if {cond} {{ {body} }} else {{ {orelse} }}"
            if self.spec.name in ("cpp", "csharp"):
                return f"({cond} ? {body} : {orelse})"
            if self.spec.name == "kotlin":
                # Kotlin has no ?: operator — it uses an if expression
                return f"(if ({cond}) {body} else {orelse})"
            if self.spec.name == "go":
                return f"(func() int64 {{ if {cond} {{ return {body} }}; return {orelse} }}())"
            if self.spec.name == "zig":
                return f"if ({cond}) {body} else {orelse}"
            return f"({cond} ? {body} : {orelse})"
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.Subscript):
            base = self.expr(node.value)
            base_type = self.infer_type(node.value)
            # handle slicing (ast.Slice)
            if isinstance(node.slice, ast.Slice):
                sl = node.slice
                start = self.expr(sl.lower) if sl.lower else None
                stop = self.expr(sl.upper) if sl.upper else None
                if base_type == "str":
                    if start and stop:
                        return self.spec.str_slice.format(x=base, start=start, end=stop, len=f"({stop} - {start})")
                    if start:
                        return self.spec.str_slice_start.format(x=base, start=start)
                    if stop:
                        return self.spec.str_slice_end.format(x=base, end=stop)
                    return base  # full slice s[:] = s
                # list slicing — xs[a:b], xs[a:], xs[:b], xs[:]
                if self.spec.list_slice:
                    length = self.spec.len_call.format(x=base)
                    if not start:
                        start = self.spec.int_cast.format(x="0")
                    if not stop:
                        stop = length
                    if not sl.lower and not sl.upper:
                        if self.spec.list_copy:
                            return self.spec.list_copy.format(x=base)
                    return self.spec.list_slice.format(
                        x=base, start=start, stop=stop)
                return self._mark_unsupported(f"list slice {base}")
            idx = self.expr(node.slice)
            if base_type == "dict":
                return self.spec.dict_get.format(d=base, k=idx)
            if base_type == "tuple":
                # tuple element access: use tuple_get spec
                # idx should be a constant integer
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
                    i = node.slice.value
                    # Go uses field names a, b, c... and Kotlin uses first, second
                    if self.spec.name == "go":
                        field = chr(97 + i)  # 0->a, 1->b, etc.
                        return self.spec.tuple_get.format(t=base, field=field)
                    if self.spec.name == "kotlin":
                        field = "first" if i == 0 else "second" if i == 1 else f"component{i + 1}"
                        return self.spec.tuple_get.format(t=base, field=field)
                    if self.spec.name == "csharp":
                        return self.spec.tuple_get.format(t=base, i1=i + 1)
                    return self.spec.tuple_get.format(t=base, i=i)
                return self.spec.tuple_get.format(t=base, i=idx)
            if base_type == "str":
                return self.spec.str_index.format(x=base, i=idx)
            # Production: bounds-checked list indexing
            if self.spec.name == "rust":
                return f"{base}[{idx} as usize]"
            return self.spec.index_call.format(x=base, i=idx)
        if isinstance(node, ast.List):
            elems = ", ".join(self.expr(e) for e in node.elts)
            # a literal of strings needs a string element type, not the
            # backend's default integer element
            elem = self._list_elem_of_value(node) or self.spec.list_elem_type
            if self.spec.name == "rust":
                return f"vec![{elems}]"
            if self.spec.name == "go":
                return f"[]{elem}{{{elems}}}"
            if self.spec.name == "kotlin":
                return f"mutableListOf({elems})"
            if self.spec.name == "zig":
                return f"&[_]i64{{ {elems} }}"
            if self.spec.name == "csharp":
                lt = self.spec.list_type.format(T=elem)
                return f"new {lt}{{{elems}}}"
            lt = self.spec.list_type.format(T=elem)
            return f"{lt}{{{elems}}}"
        if isinstance(node, ast.ListComp):
            return self._list_comp(node)
        if isinstance(node, ast.Dict):
            # emit as a map literal — backend-specific
            if self.spec.name == "rust":
                pairs = ", ".join(f"({self.expr(k)}, {self.expr(v)})"
                                  for k, v in zip(node.keys, node.values))
                return f"std::collections::HashMap::from([{pairs}])"
            if self.spec.name == "cpp":
                pairs = ", ".join(f"{{ {self.expr(k)}, {self.expr(v)} }}"
                                  for k, v in zip(node.keys, node.values))
                return f"{{{{{pairs}}}}}"
            if self.spec.name == "csharp":
                pairs = ", ".join(f"{{ {self.expr(k)}, {self.expr(v)} }}"
                                  for k, v in zip(node.keys, node.values))
                return f"new Dictionary<string, {self.spec.list_elem_type}>() {{{pairs}}}"
            if self.spec.name == "go":
                pairs = ", ".join(f"{self.expr(k)}: {self.expr(v)}"
                                 for k, v in zip(node.keys, node.values))
                return f"map[string]{self.spec.list_elem_type}{{{pairs}}}"
            if self.spec.name == "kotlin":
                pairs = ", ".join(f"{self.expr(k)} to {self.expr(v)}"
                                 for k, v in zip(node.keys, node.values))
                return f"hashMapOf({pairs})"
            if self.spec.name == "zig":
                # Zig doesn't have map literals — emit a block expression
                # that creates and populates the map
                puts = "\n".join(f"        m.put({self.expr(k)}, {self.expr(v)}) catch unreachable;"
                                for k, v in zip(node.keys, node.values))
                return f"blk: {{\n        var m = std.StringHashMap({self.spec.list_elem_type}).init(std.heap.page_allocator);\n{puts}\n        break :blk m;\n    }}"
            return f"{{{pairs}}}"
        if isinstance(node, ast.Set):
            elems = ", ".join(self.expr(e) for e in node.elts)
            if self.spec.name == "rust":
                return f"std::collections::HashSet::from([{elems}])"
            if self.spec.name == "cpp":
                return f"std::set<int64_t>{{{elems}}}"
            if self.spec.name == "csharp":
                return f"new HashSet<long>{{{elems}}}"
            if self.spec.name == "go":
                # Go has no set type; GE uses map[elem]bool. Go rejects
                # duplicate *constant* keys at compile time, so literals are
                # deduplicated here (a runtime set would collapse them anyway).
                seen: list[str] = []
                for e in node.elts:
                    rendered = self.expr(e)
                    if rendered not in seen:
                        seen.append(rendered)
                if not seen:
                    return "map[int64]bool{}"
                pairs = ", ".join(f"{v}: true" for v in seen)
                return f"map[int64]bool{{{pairs}}}"
            if self.spec.name == "kotlin":
                return f"hashSetOf({elems})"
            if self.spec.name == "zig":
                # no allocator-backed set in the Zig runtime
                return self._mark_unsupported("set literal (Zig)")
            return f"std::set<int64_t>{{{elems}}}"
        if isinstance(node, ast.SetComp):
            return self._set_comp(node)
        if isinstance(node, ast.DictComp):
            return self._dict_comp(node)
        if isinstance(node, ast.Tuple):
            # GE models tuples as fixed-width pairs. Anything else would need
            # a per-arity native type (Go structs, Kotlin Triple, ...), so it
            # is rejected loudly rather than emitted as broken code.
            if len(node.elts) != 2:
                return self._mark_unsupported(
                    f"tuple of {len(node.elts)} elements "
                    f"(only 2-element tuples are supported)")
            elems = ", ".join(self.expr(e) for e in node.elts)
            if self.spec.name == "rust":
                return f"({elems})"
            if self.spec.name == "cpp":
                return f"std::make_tuple({elems})"
            if self.spec.name == "csharp":
                return f"({elems})"
            if self.spec.name == "kotlin":
                return f"Pair({elems})"
            if self.spec.name == "zig":
                return f"[_]{self.spec.list_elem_type}{{ {elems} }}"
            if self.spec.name == "go":
                # Go uses struct literal with field names a, b, c...
                fields = ", ".join(f"{chr(97 + i)}: {self.expr(e)}"
                                   for i, e in enumerate(node.elts))
                # build struct type with field names
                field_types = "; ".join(f"{chr(97 + i)} {self.spec.list_elem_type}"
                                        for i in range(len(node.elts)))
                return f"struct {{ {field_types} }}{{ {fields} }}"
            return f"({elems})"
        if isinstance(node, ast.Attribute):
            base = self.expr(node.value)
            # check if this is a property access (obj.prop -> ClassName_prop(obj))
            base_type = self.infer_type(node.value)
            if base_type in self.class_names:
                props = self.class_properties.get(base_type, [])
                if node.attr in props:
                    return f"{base_type}_{node.attr}({base})"
            return f"{base}.{node.attr}"
        return self._mark_unsupported('{type(node).__name__}')

    def call(self, node: ast.Call) -> str:
        fname = getattr(node.func, "id", None)
        # inline target-language escape hatch: ge_inline("backend", "raw code")
        # Security: validate backend name and log usage
        if fname == "ge_inline":
            if len(node.args) >= 2:
                target_backend = ""
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    target_backend = node.args[0].value
                # validate backend name against known backends
                valid_backends = {"rust", "cpp", "csharp", "zig", "go", "kotlin", "dart"}
                if target_backend not in valid_backends:
                    self._mark_unsupported(f"ge_inline: invalid backend '{target_backend}'")
                    return f"/*ge_inline: invalid backend '{target_backend}'*/"
                if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    raw_code = node.args[1].value
                    if target_backend == self.spec.name:
                        return raw_code
                    return f"/*ge_inline: skipped for {self.spec.name}*/"
            return f"/*ge_inline: invalid usage*/"
        if fname == "ge_raw":
            # emit raw code regardless of backend
            # Security: this is an arbitrary code injection point
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return node.args[0].value
            return f"/*ge_raw: invalid usage*/"
        if fname == "ge_preamble":
            # module-level file-scope injection, collected by the analyzer.
            # A call inside a function body has nothing left to do.
            return f"/*ge_preamble: hoisted to file scope*/"
        if fname == "print":
            return self.print_call(node.args)
        if fname == "len":
            arg = node.args[0]
            t = self.infer_type(arg)
            if t == "str":
                return self.spec.str_len.format(x=self.expr(arg))
            if t == "list":
                return self.spec.list_len.format(x=self.expr(arg))
            return self.spec.len_call.format(x=self.expr(arg))
        if fname == "abs":
            t = self.infer_type(node.args[0])
            tmpl = self.spec.abs_int if t == "int" else self.spec.abs_float
            return tmpl.format(x=self.expr(node.args[0]))
        if fname == "sum":
            return self.spec.sum_call.format(it=self.expr(node.args[0]))
        if fname in ("min", "max"):
            is_min = fname == "min"
            tmpl = self.spec.min_call if is_min else self.spec.max_call
            raw = [self.expr(a) for a in node.args]
            if len(raw) == 1:
                return tmpl.format(it=raw[0])
            if len(raw) == 2:
                pair = (self.spec.min2_call if is_min
                        else self.spec.max2_call)
                if pair:
                    return pair.format(a=raw[0], b=raw[1])
            return f"{fname}({', '.join(raw)})"
        if fname == "pow":
            return self.spec.pow_call.format(l=self.expr(node.args[0]), r=self.expr(node.args[1]))
        if fname == "int":
            return f"({self.spec.int_cast.format(x=self.expr(node.args[0]))})"
        if fname == "float":
            return f"({self.spec.float_cast.format(x=self.expr(node.args[0]))})"
        if fname == "str":
            return self._str_call(node.args[0])
        if fname == "bool":
            return f"({self.expr(node.args[0])} != 0)"
        if fname == "sorted":
            # sorted(list) -> copy and sort (simplified)
            if self.spec.name == "rust":
                return f"{{ let mut v = {self.expr(node.args[0])}.clone(); v.sort(); v }}"
            if self.spec.name == "cpp":
                return f"([&]() {{ auto v = {self.expr(node.args[0])}; std::sort(v.begin(), v.end()); return v; }}())"
            if self.spec.name == "csharp":
                return f"{self.expr(node.args[0])}.OrderBy(x => x).ToList()"
            if self.spec.name == "go":
                return f"func() []int64 {{ var v = make([]int64, len({self.expr(node.args[0])})); copy(v, {self.expr(node.args[0])}); sort.Slice(v, func(i, j int) bool {{ return v[i] < v[j] }}); return v; }}()"
            if self.spec.name == "kotlin":
                return f"{self.expr(node.args[0])}.sorted().toMutableList()"
            return self._mark_unsupported('sorted()')
        if fname == "reversed":
            if self.spec.name == "rust":
                return f"{{ let v = {self.expr(node.args[0])}; v.iter().rev().cloned().collect::<Vec<_>>() }}"
            if self.spec.name == "cpp":
                return f"([&]() {{ auto v = {self.expr(node.args[0])}; std::reverse(v.begin(), v.end()); return v; }}())"
            if self.spec.name == "csharp":
                return f"{self.expr(node.args[0])}.ToArray().Reverse().ToList()"
            if self.spec.name == "go":
                return f"func() []int64 {{ var src = {self.expr(node.args[0])}; var v = make([]int64, len(src)); for i := range src {{ v[i] = src[len(src)-1-i] }}; return v; }}()"
            if self.spec.name == "kotlin":
                return f"{self.expr(node.args[0])}.reversed()"
            return self._mark_unsupported('reversed()')
        if fname == "any":
            it = self.expr(node.args[0])
            if self.spec.name == "rust":
                return f"{it}.iter().any(|&x| x != 0)"
            if self.spec.name == "cpp":
                return f"std::any_of({it}.begin(), {it}.end(), [](int64_t x) {{ return x != 0; }})"
            if self.spec.name == "csharp":
                return f"{it}.Any(x => x != 0)"
            if self.spec.name == "go":
                return f"func() bool {{ for _, v := range {it} {{ if v != 0 {{ return true }} }}; return false }}()"
            if self.spec.name == "kotlin":
                return f"{it}.any {{ it != 0L }}"
            return self._mark_unsupported('any()')
        if fname == "all":
            it = self.expr(node.args[0])
            if self.spec.name == "rust":
                return f"{it}.iter().all(|&x| x != 0)"
            if self.spec.name == "cpp":
                return f"std::all_of({it}.begin(), {it}.end(), [](int64_t x) {{ return x != 0; }})"
            if self.spec.name == "csharp":
                return f"{it}.All(x => x != 0)"
            if self.spec.name == "go":
                return f"func() bool {{ for _, v := range {it} {{ if v == 0 {{ return false }} }}; return true }}()"
            if self.spec.name == "kotlin":
                return f"{it}.all {{ it != 0L }}"
            return self._mark_unsupported('all()')
        if fname == "divmod":
            a = self.expr(node.args[0])
            b = self.expr(node.args[1])
            if self.spec.name == "rust":
                return f"({a} / {b}, {a} % {b})"
            if self.spec.name == "cpp":
                return f"std::make_tuple({a} / {b}, {a} % {b})"
            if self.spec.name == "csharp":
                return f"({a} / {b}, {a} % {b})"
            if self.spec.name == "go":
                return f"struct {{ a int64; b int64 }}{{ {a} / {b}, {a} % {b} }}"
            if self.spec.name == "kotlin":
                return f"Pair({a} / {b}, {a} % {b})"
            return f"({a} / {b}, {a} % {b})"
        if fname == "bin":
            v = self.expr(node.args[0])
            if self.spec.name == "rust":
                return f'format!("{{:b}}", {v})'
            if self.spec.name == "cpp":
                return f"std::bitset<64>({v}).to_string()"
            if self.spec.name == "csharp":
                return f"Convert.ToString({v}, 2)"
            if self.spec.name == "go":
                return f'strconv.FormatInt({v}, 2)'
            if self.spec.name == "kotlin":
                return f"{v}.toString(2)"
            return self._mark_unsupported('bin()')
        if fname == "hex":
            v = self.expr(node.args[0])
            if self.spec.name == "rust":
                return f'format!("{{:x}}", {v})'
            if self.spec.name == "cpp":
                return f'ge_int_to_hex({v})'
            if self.spec.name == "csharp":
                return f"{v}.ToString(\"x\")"
            if self.spec.name == "go":
                return f'strconv.FormatInt({v}, 16)'
            if self.spec.name == "kotlin":
                return f"{v}.toString(16)"
            return self._mark_unsupported('hex()')
        if fname == "oct":
            v = self.expr(node.args[0])
            if self.spec.name == "rust":
                return f'format!("{{:o}}", {v})'
            if self.spec.name == "cpp":
                return f'ge_int_to_oct({v})'
            if self.spec.name == "csharp":
                return f"Convert.ToString({v}, 8)"
            if self.spec.name == "go":
                return f'strconv.FormatInt({v}, 8)'
            if self.spec.name == "kotlin":
                return f"{v}.toString(8)"
            return self._mark_unsupported('oct()')
        if fname == "chr":
            v = self.expr(node.args[0])
            if self.spec.name == "rust":
                return f"char::from_u32({v} as u32).unwrap_or('?').to_string()"
            if self.spec.name == "cpp":
                return f"std::string(1, (char)({v}))"
            if self.spec.name == "csharp":
                return f"((char)({v})).ToString()"
            if self.spec.name == "go":
                return f"string(rune({v}))"
            if self.spec.name == "kotlin":
                return f"{v}.toChar().toString()"
            return self._mark_unsupported('chr()')
        if fname == "ord":
            v = self.expr(node.args[0])
            if self.spec.name == "rust":
                return f"{v}.as_bytes()[0] as i64"
            if self.spec.name == "cpp":
                return f"(int64_t)({v})[0]"
            if self.spec.name == "csharp":
                return f"(long)({v})[0]"
            if self.spec.name == "go":
                return f"int64({v}[0])"
            if self.spec.name == "kotlin":
                return f"{v}[0].toLong()"
            return self._mark_unsupported('ord()')
        if fname == "isinstance":
            # Static type check — resolved at compile time
            val_type = self.infer_type(node.args[0])
            if isinstance(node.args[1], ast.Name):
                check_type = node.args[1].id
                return "true" if val_type == check_type else "false"
            return "false"
        if fname == "repr":
            v = self.expr(node.args[0])
            t = self.infer_type(node.args[0])
            if t == "str":
                if self.spec.name == "rust":
                    return f'format!("{{:?}}", {v})'
                if self.spec.name == "cpp":
                    return f'"\\""' + f" + {v} + " + f'"\\""'
                if self.spec.name == "csharp":
                    return f'"\\\""' + f" + {v} + " + f'"\\\""'
                if self.spec.name == "go":
                    return f'fmt.Sprintf("%q", {v})'
                if self.spec.name == "kotlin":
                    return f'"\\""' + f" + {v} + " + f'"\\""'
            return self._str_call(node.args[0])
        if fname == "hash":
            v = self.expr(node.args[0])
            if self.spec.name == "rust":
                return f"std::collections::hash_map::DefaultHasher::hash(&mut std::collections::hash_map::DefaultHasher::new(), &{v}) as i64"
            if self.spec.name == "cpp":
                return f"(int64_t)std::hash<int64_t>()({v})"
            if self.spec.name == "csharp":
                return f"{v}.GetHashCode()"
            if self.spec.name == "go":
                return f"int64(uintptr(unsafe.Pointer(&{v})))"
            if self.spec.name == "kotlin":
                return f"{v}.hashCode().toLong()"
            return self._mark_unsupported('hash()')
        if fname == "input":
            if self.spec.name == "rust":
                return '{ let mut s = String::new(); std::io::stdin().read_line(&mut s).ok(); s.trim_end().to_string() }'
            if self.spec.name == "cpp":
                return '([]() { std::string s; std::getline(std::cin, s); return s; }())'
            if self.spec.name == "csharp":
                return 'Console.ReadLine() ?? ""'
            if self.spec.name == "go":
                return 'func() string { var s string; fmt.Scanln(&s); return s }()'
            if self.spec.name == "kotlin":
                return 'readLine() ?: ""'
            return self._mark_unsupported('input()')
        if fname == "map":
            fn_arg = node.args[0]
            it = self.expr(node.args[1])
            fn_name = getattr(fn_arg, "id", None) or getattr(getattr(fn_arg, "func", None), "id", None)
            if fn_name and self.spec.name == "rust":
                return f"{it}.iter().map(|&x| {fn_name}(x)).collect::<Vec<i64>>()"
            if fn_name and self.spec.name == "cpp":
                return f"([&]() {{ std::vector<int64_t> r; for (auto x : {it}) r.push_back({fn_name}(x)); return r; }}())"
            if fn_name and self.spec.name == "csharp":
                return f"{it}.Select(x => {fn_name}(x)).ToList()"
            if fn_name and self.spec.name == "go":
                return f"func() []int64 {{ var r []int64; for _, x := range {it} {{ r = append(r, {fn_name}(x)) }}; return r; }}()"
            if fn_name and self.spec.name == "kotlin":
                return f"{it}.map {{ {fn_name}(it) }}.toMutableList()"
            if fn_name:
                return self._mark_unsupported('map()')
            # lambda arg
            if isinstance(fn_arg, ast.Lambda):
                lam = self._lambda(fn_arg)
                if self.spec.name == "rust":
                    return f"{it}.iter().map({lam}).collect::<Vec<i64>>()"
                if self.spec.name == "cpp":
                    return f"([&]() {{ std::vector<int64_t> r; for (auto x : {it}) r.push_back(({lam})(x)); return r; }}())"
                if self.spec.name == "csharp":
                    return f"{it}.Select({lam}).ToList()"
                if self.spec.name == "kotlin":
                    return f"{it}.map {{ {lam}(it) }}.toMutableList()"
            return self._mark_unsupported('map()')
        if fname == "filter":
            fn_arg = node.args[0]
            it = self.expr(node.args[1])
            fn_name = getattr(fn_arg, "id", None) or getattr(getattr(fn_arg, "func", None), "id", None)
            if fn_name and self.spec.name == "rust":
                return f"{it}.iter().filter(|&x| {fn_name}(x) != 0).cloned().collect::<Vec<i64>>()"
            if fn_name and self.spec.name == "cpp":
                return f"([&]() {{ std::vector<int64_t> r; for (auto x : {it}) if ({fn_name}(x) != 0) r.push_back(x); return r; }}())"
            if fn_name and self.spec.name == "csharp":
                return f"{it}.Where(x => {fn_name}(x) != 0).ToList()"
            if fn_name and self.spec.name == "kotlin":
                return f"{it}.filter {{ {fn_name}(it) != 0L }}.toMutableList()"
            if isinstance(fn_arg, ast.Lambda):
                lam = self._lambda(fn_arg)
                if self.spec.name == "rust":
                    return f"{it}.iter().filter(|&x| ({lam})(x) != 0).cloned().collect::<Vec<i64>>()"
                if self.spec.name == "cpp":
                    return f"([&]() {{ std::vector<int64_t> r; for (auto x : {it}) if (({lam})(x) != 0) r.push_back(x); return r; }}())"
                if self.spec.name == "csharp":
                    return f"{it}.Where(x => ({lam})(x) != 0).ToList()"
                if self.spec.name == "kotlin":
                    return f"{it}.filter {{ ({lam})(it) != 0L }}.toMutableList()"
            return self._mark_unsupported('filter()')
        if fname == "enumerate":
            it = self.expr(node.args[0])
            if self.spec.name == "rust":
                return f"{it}.iter().enumerate().map(|(i, x)| (i as i64, *x)).collect::<Vec<(i64, i64)>>()"
            if self.spec.name == "cpp":
                return f"([&]() {{ std::vector<std::tuple<int64_t,int64_t>> r; for (int64_t i = 0; i < (int64_t){it}.size(); i++) r.push_back(std::make_tuple(i, {it}[i])); return r; }}())"
            if self.spec.name == "csharp":
                return f"{it}.Select((x, i) => (i, x)).ToList()"
            if self.spec.name == "kotlin":
                return f"{it}.mapIndexed {{ i, x -> Pair(i.toLong(), x) }}.toMutableList()"
            return self._mark_unsupported('enumerate()')
        if fname == "zip":
            it1 = self.expr(node.args[0])
            it2 = self.expr(node.args[1])
            if self.spec.name == "rust":
                return f"{it1}.iter().zip({it2}.iter()).map(|(a, b)| (*a, *b)).collect::<Vec<(i64, i64)>>()"
            if self.spec.name == "cpp":
                return f"([&]() {{ std::vector<std::tuple<int64_t,int64_t>> r; int64_t n = std::min({it1}.size(), {it2}.size()); for (int64_t i = 0; i < n; i++) r.push_back(std::make_tuple({it1}[i], {it2}[i])); return r; }}())"
            if self.spec.name == "csharp":
                return f"{it1}.Zip({it2}, (a, b) => (a, b)).ToList()"
            if self.spec.name == "kotlin":
                return f"{it1}.zip({it2}).toMutableList()"
            return self._mark_unsupported('zip()')
        if fname == "range":
            # range() used as a value (not in for loop) -> build a list
            args = node.args
            if len(args) == 1:
                lo, hi = "0", self.expr(args[0])
            elif len(args) == 2:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            else:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            if self.spec.name == "rust":
                return f"({lo}..{hi}).collect::<Vec<i64>>()"
            if self.spec.name == "cpp":
                return f"([&]() {{ std::vector<int64_t> r; for (int64_t i = {lo}; i < {hi}; i++) r.push_back(i); return r; }}())"
            if self.spec.name == "csharp":
                return f"Enumerable.Range((int)({lo}), (int)({hi}) - (int)({lo})).Select(x => (long)x).ToList()"
            if self.spec.name == "go":
                return f"func() []int64 {{ var r []int64; for i := {lo}; i < {hi}; i++ {{ r = append(r, i) }}; return r; }}()"
            if self.spec.name == "kotlin":
                return f"({lo} until {hi}).map {{ it.toLong() }}.toMutableList()"
            return self._mark_unsupported('range()')
        # stdlib file I/O and math functions
        if fname == "read_file":
            return self._stdlib_call("ge_read_file", node.args)
        if fname == "write_file":
            return self._stdlib_call("ge_write_file", node.args)
        if fname == "append_file":
            return self._stdlib_call("ge_append_file", node.args)
        if fname == "sqrt":
            return self._stdlib_call("ge_sqrt", node.args)
        if fname == "floor":
            return self._stdlib_call("ge_floor", node.args)
        if fname == "ceil":
            return self._stdlib_call("ge_ceil", node.args)
        if fname == "round":
            return self._stdlib_call("ge_round", node.args)
        if fname == "sin":
            return self._stdlib_call("ge_sin", node.args)
        if fname == "cos":
            return self._stdlib_call("ge_cos", node.args)
        if fname == "tan":
            return self._stdlib_call("ge_tan", node.args)
        if fname == "log":
            return self._stdlib_call("ge_log", node.args)
        if fname == "exp":
            return self._stdlib_call("ge_exp", node.args)
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "split"
                and len(node.args) == 1):
            if not self.spec.str_split:
                return self._mark_unsupported(
                    f"str.split (not available on the {self.spec.name} backend)")
            return self.spec.str_split.format(
                x=self.expr(node.func.value), sep=self.expr(node.args[0]))
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "join"
                and len(node.args) == 1):
            if not self.spec.str_join:
                return self._mark_unsupported(
                    f"str.join (not available on the {self.spec.name} backend)")
            return self.spec.str_join.format(
                x=self.expr(node.args[0]), sep=self.expr(node.func.value))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "append":
            base = self.expr(node.func.value)
            if not self.spec.append_call:
                return self._mark_unsupported(
                    f"list.append (the {self.spec.name} backend models lists "
                    f"as fixed slices)")
            return self.spec.append_call.format(x=base, v=self.expr(node.args[0]))
        # super().method(args) -> ParentClass_method(_self, args)
        if (isinstance(node.func, ast.Attribute) and
            isinstance(node.func.value, ast.Call) and
            getattr(node.func.value.func, "id", None) == "super"):
            method = node.func.attr
            args = [self._arg(a) for a in node.args]
            # find the parent class from the current method context
            parent = self._find_parent_class()
            if parent:
                return f"{parent}_{method}(_self, {', '.join(args)})"
            return f"/*super().{method}() — no parent class*/"
        # class constructor call: ClassName(args) -> ClassName_new(args)
        if fname and fname in self.class_names:
            args = [self._arg(a) for a in node.args]
            return f"{fname}_new({', '.join(args)})"
        # method call: obj.method(args) -> ClassName_method(obj, args)
        if isinstance(node.func, ast.Attribute) and not node.func.attr == "append":
            base = self.expr(node.func.value)
            args = [self._arg(a) for a in node.args]
            # check if base is a known class instance
            base_type = self.infer_type(node.func.value)
            if base_type in self.class_names:
                return f"{base_type}_{node.func.attr}({base}, {', '.join(args)})"
            # check if base name is a class name (static method call)
            if isinstance(node.func.value, ast.Name) and node.func.value.id in self.class_names:
                return f"{node.func.value.id}_{node.func.attr}({', '.join(args)})"
            # string methods
            if base_type == "str" or (isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str)):
                method = node.func.attr
                if method == "upper":
                    if self.spec.name == "rust":
                        return f"{base}.to_uppercase()"
                    if self.spec.name == "cpp":
                        return f"geStrUpper({base})"
                    if self.spec.name == "csharp":
                        return f"{base}.ToUpper()"
                    if self.spec.name == "go":
                        return f"strings.ToUpper({base})"
                    if self.spec.name == "kotlin":
                        return f"{base}.uppercase()"
                    return f"{base}.upper()"
                if method == "lower":
                    if self.spec.name == "rust":
                        return f"{base}.to_lowercase()"
                    if self.spec.name == "cpp":
                        return f"geStrLower({base})"
                    if self.spec.name == "csharp":
                        return f"{base}.ToLower()"
                    if self.spec.name == "go":
                        return f"strings.ToLower({base})"
                    if self.spec.name == "kotlin":
                        return f"{base}.lowercase()"
                    return f"{base}.lower()"
                if method == "replace" and len(node.args) == 2:
                    a = self.expr(node.args[0])
                    b = self.expr(node.args[1])
                    if self.spec.name == "rust":
                        return f"{base}.replace({a}.as_str(), {b}.as_str())"
                    if self.spec.name == "cpp":
                        return f"geStrReplace({base}, {a}, {b})"
                    if self.spec.name == "csharp":
                        return f"{base}.Replace({a}, {b})"
                    if self.spec.name == "go":
                        return f"strings.ReplaceAll({base}, {a}, {b})"
                    if self.spec.name == "kotlin":
                        return f"{base}.replace({a}, {b})"
                if method == "strip":
                    if self.spec.name == "rust":
                        return f"{base}.trim().to_string()"
                    if self.spec.name == "csharp":
                        return f"{base}.Trim()"
                    if self.spec.name == "go":
                        return f"strings.TrimSpace({base})"
                    if self.spec.name == "kotlin":
                        return f"{base}.trim()"
                    return f"{base}.strip()"
            # generic method call
            return f"{base}.{node.func.attr}({', '.join(args)})"
        # generic (user) function call: borrow list args where appropriate
        # for Rust, check if the called function has mutated list params
        mutated_indices = self.func_mutated_params.get(fname, set())
        args = []
        for i, a in enumerate(node.args):
            if self.spec.name == "rust" and i in mutated_indices:
                # this arg position is a mutated list param — pass &mut
                t = self.infer_type(a)
                if t == "list" and isinstance(a, ast.Name):
                    # if the arg is already a mutated param of the current function,
                    # it's already a &mut Vec<i64> reference — pass it directly
                    if a.id in self.mutated_params:
                        args.append(self.expr(a))
                    else:
                        args.append(f"&mut {self.expr(a)}")
                    continue
            args.append(self._arg(a))
        # handle keyword arguments: map to positional by reordering
        # (native languages don't support keyword args, so we just append them)
        for kw in node.keywords:
            if kw.arg is None:
                # **kwargs — not supported, skip
                continue
            args.append(self.expr(kw.value))
        args = self._fill_defaults(fname, args, node)
        call_str = f"{fname}({', '.join(args)})"
        # wrap extern "C" calls in unsafe block (Rust requires this)
        if fname in self.extern_names and self.spec.name == "rust":
            return f"unsafe {{ {call_str} }}"
        return call_str

    def _fill_defaults(self, fname: str, args: list[str],
                       node: ast.Call) -> list[str]:
        """Append default arguments a call site omitted.

        `def f(a, b=10)` called as `f(5)` must emit `f(5, 10)` in the target
        language, which has no notion of Python default parameters.
        """
        if node.keywords:
            return args
        sig = self.func_signatures.get(fname)
        if not sig:
            return args
        names, defaults = sig
        if len(args) >= len(names):
            return args
        filled = list(args)
        for name in names[len(filled):]:
            d = defaults.get(name)
            if d is None or d == "":
                break
            filled.append(d)
        return filled

    def _str_call(self, arg: ast.AST) -> str:
        """Convert a value to string."""
        t = self.infer_type(arg)
        v = self.expr(arg)
        if self.spec.name == "rust":
            return f"{v}.to_string()"
        if self.spec.name == "cpp":
            return f"std::to_string({v})"
        if self.spec.name == "csharp":
            return f"{v}.ToString()"
        if self.spec.name == "zig":
            return f"std.fmt.allocPrint(std.heap.page_allocator, \"{{d}}\", .{{{v}}}) catch unreachable"
        if self.spec.name == "go":
            return f"strconv.FormatInt({v}, 10)"
        if self.spec.name == "kotlin":
            return f"{v}.toString()"
        return f"std::to_string({v})"

    def _arg(self, node: ast.AST) -> str:
        """Render a user-call argument, borrowing owned list values when needed."""
        s = self.expr(node)
        if not self.spec.borrow_list_arg:
            return s
        if isinstance(node, ast.Name) and node.id in self.params:
            # already a borrowed slice param -> pass as-is
            # but if it's a mutated list param (&mut Vec), reborrow as &[i64]
            if self.spec.name == "rust" and node.id in self.mutated_params:
                return f"&*{s}"
            return s
        t = self.infer_type(node)
        if t == "list":
            return "&" + s
        return s

    def _stdlib_call(self, ge_name: str, args: list[ast.AST]) -> str:
        """Emit a call to a GE stdlib runtime function, adapting the name per backend."""
        # C# uses PascalCase
        if self.spec.name == "csharp":
            parts = ge_name.split("_")
            cs_name = "".join(p.capitalize() for p in parts)
            cs_name = "Ge" + cs_name[2:] if cs_name.startswith("Ge") else cs_name
            arg_strs = ", ".join(self.expr(a) for a in args)
            return f"{cs_name}({arg_strs})"
        # Go uses camelCase
        if self.spec.name == "go":
            parts = ge_name.split("_")
            go_name = parts[0] + "".join(p.capitalize() for p in parts[1:])
            arg_strs = ", ".join(self.expr(a) for a in args)
            return f"{go_name}({arg_strs})"
        arg_strs = ", ".join(self.expr(a) for a in args)
        return f"{ge_name}({arg_strs})"

    def _lambda(self, node: ast.Lambda) -> str:
        """Lower a lambda expression to backend-specific closure syntax."""
        params = node.args.args
        body_expr = self.expr(node.body)

        if self.spec.name == "rust":
            args = ", ".join(f"{a.arg}: i64" for a in params)
            return f"|{args}| {{ {body_expr} }}"
        if self.spec.name == "cpp":
            args = ", ".join(f"int64_t {a.arg}" for a in params)
            return f"[]({args}) -> int64_t {{ return {body_expr}; }}"
        if self.spec.name == "csharp":
            args = ", ".join(f"long {a.arg}" for a in params)
            if len(params) == 1:
                return f"({args}) => {body_expr}"
            return f"({args}) => {body_expr}"
        if self.spec.name == "go":
            args = ", ".join(f"{a.arg} int64" for a in params)
            return f"func({args}) int64 {{ return {body_expr} }}"
        if self.spec.name == "kotlin":
            args = ", ".join(f"{a.arg}: Long" for a in params)
            return f"{{ {args} -> {body_expr} }}"
        if self.spec.name == "zig":
            # Zig doesn't have lambdas — emit as an anonymous struct with a call method
            # This is a simplification; real Zig would need a comptime generic
            return self._mark_unsupported('lambda in Zig')
        return self._mark_unsupported('lambda')

    def _is_generator(self, body: ast.AST) -> bool:
        """Check if a function body contains yield statements."""
        for node in ast.walk(body):
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                return True
        return False

    def _transform_generator(self, unit: FuncUnit) -> FuncUnit:
        """Transform a generator function into a list-building function.

        Replaces `yield value` with `__gen_result.append(value)`,
        adds a list variable at the start, and a return at the end.
        Changes the return type to 'list'.
        """
        import copy
        # deep copy the body to avoid modifying the original
        body = copy.deepcopy(unit.body)
        # transform yield statements
        self._transform_yield(body)
        # prepend a list declaration and append a return statement
        list_decl = ast.AnnAssign(
            target=ast.Name(id="__gen_result", ctx=ast.Store()),
            annotation=ast.Name(id="list", ctx=ast.Load()),
            value=ast.List(elts=[], ctx=ast.Load()),
            simple=1,
        )
        list_decl.lineno = body.lineno
        ret = ast.Return(value=ast.Name(id="__gen_result", ctx=ast.Load()))
        ret.lineno = body.end_lineno or body.lineno
        body.body = [list_decl] + body.body + [ret]
        # change return type to list
        unit = FuncUnit(
            name=unit.name,
            lineno=unit.lineno,
            params=unit.params,
            ret_type="list",
            body=body,
            source=unit.source,
            forced_backend=unit.forced_backend,
            supported=unit.supported,
            unsupported_reasons=unit.unsupported_reasons,
            features=unit.features,
            backend=unit.backend,
        )
        return unit

    def _transform_yield(self, node: ast.AST) -> None:
        """Recursively transform yield statements into list.append() calls."""
        for field in ast.iter_fields(node):
            if isinstance(field[1], list):
                new_list = []
                for child in field[1]:
                    if isinstance(child, ast.Expr) and isinstance(child.value, ast.Yield):
                        # yield value -> __gen_result.append(value)
                        val = child.value.value
                        if val is None:
                            val = ast.Constant(value=None)
                        append_call = ast.Expr(
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(id="__gen_result", ctx=ast.Load()),
                                    attr="append",
                                    ctx=ast.Load(),
                                ),
                                args=[val],
                                keywords=[],
                            )
                        )
                        append_call.lineno = child.lineno
                        new_list.append(append_call)
                    elif isinstance(child, ast.Yield):
                        # bare yield (not in Expr) -> wrap in append
                        val = child.value if child.value else ast.Constant(value=None)
                        append_call = ast.Expr(
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(id="__gen_result", ctx=ast.Load()),
                                    attr="append",
                                    ctx=ast.Load(),
                                ),
                                args=[val],
                                keywords=[],
                            )
                        )
                        append_call.lineno = child.lineno
                        new_list.append(append_call)
                    else:
                        self._transform_yield(child)
                        new_list.append(child)
                setattr(node, field[0], new_list)
            elif isinstance(field[1], ast.AST):
                self._transform_yield(field[1])

    def _with_stmt(self, node: ast.With, ind: str) -> None:
        """Lower a with statement to backend-specific resource management."""
        # Only support single-item with statements for now
        if len(node.items) != 1:
            self.lines.append(f"{ind}// unsupported multi-item with statement")
            return
        item = node.items[0]
        ctx = item.context_expr
        var_name = item.optional_vars.id if item.optional_vars else None

        # Check if it's an open() call
        is_open = isinstance(ctx, ast.Call) and getattr(ctx.func, "id", None) == "open"
        if is_open:
            args = ctx.args
            path = self.expr(args[0]) if args else '""'
            mode = self.expr(args[1]) if len(args) > 1 else '"r"'

            if self.spec.name == "cpp":
                if var_name:
                    self.lines.append(f'{ind}std::ifstream {var_name}({path});')
                self.indent_lvl += 1
                for s in node.body:
                    self.stmt(s)
                self.indent_lvl -= 1
            elif self.spec.name == "rust":
                if var_name:
                    self.lines.append(f'{ind}let mut {var_name} = std::fs::File::open({path}).unwrap();')
                self.indent_lvl += 1
                for s in node.body:
                    self.stmt(s)
                self.indent_lvl -= 1
            elif self.spec.name == "csharp":
                if var_name:
                    self.lines.append(f'{ind}using (var {var_name} = System.IO.File.OpenText({path})) {{')
                else:
                    self.lines.append(f'{ind}using (var __f = System.IO.File.OpenText({path})) {{')
                self.indent_lvl += 1
                for s in node.body:
                    self.stmt(s)
                self.indent_lvl -= 1
                self.lines.append(f"{ind}}}")
            elif self.spec.name == "go":
                if var_name:
                    self.lines.append(f'{ind}{var_name}, _ := os.Open({path})')
                    self.lines.append(f'{ind}defer {var_name}.Close()')
                else:
                    self.lines.append(f'{ind}__f, _ := os.Open({path})')
                    self.lines.append(f'{ind}defer __f.Close()')
                self.indent_lvl += 1
                for s in node.body:
                    self.stmt(s)
                self.indent_lvl -= 1
            elif self.spec.name == "kotlin":
                if var_name:
                    self.lines.append(f'{ind}java.io.File({path}).bufferedReader().use {{ {var_name} ->')
                else:
                    self.lines.append(f'{ind}java.io.File({path}).bufferedReader().use {{ __f ->')
                self.indent_lvl += 1
                for s in node.body:
                    self.stmt(s)
                self.indent_lvl -= 1
                self.lines.append(f"{ind}}}")
            elif self.spec.name == "zig":
                if var_name:
                    self.lines.append(f'{ind}var {var_name} = try std.fs.cwd().openFile({path}, .{{}});')
                    self.lines.append(f'{ind}defer {var_name}.close();')
                self.indent_lvl += 1
                for s in node.body:
                    self.stmt(s)
                self.indent_lvl -= 1
            else:
                self.lines.append(f"{ind}// unsupported with statement")
                self.indent_lvl += 1
                for s in node.body:
                    self.stmt(s)
                self.indent_lvl -= 1
        else:
            # non-open with statements: emit as a comment + body
            self.lines.append(f"{ind}// with statement (non-file context)")
            self.indent_lvl += 1
            for s in node.body:
                self.stmt(s)
            self.indent_lvl -= 1

    def _list_comp(self, node: ast.ListComp) -> str:
        """Lower a list comprehension to a block expression that builds a list."""
        # only support single-generator comprehensions for now
        if len(node.generators) != 1:
            return self._mark_unsupported('multi-gen comprehension')
        gen = node.generators[0]
        var = gen.target.id if isinstance(gen.target, ast.Name) else "_"
        # build the loop source
        it = gen.iter
        if isinstance(it, ast.Call) and getattr(it.func, "id", None) == "range":
            args = it.args
            if len(args) == 1:
                lo, hi = "0", self.expr(args[0])
            elif len(args) == 2:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            else:
                lo, hi = self.expr(args[0]), self.expr(args[1])
        else:
            # for-in over a container
            lo, hi = None, None
            iter_src = self.expr(it)

        elem = self.expr(node.elt)
        lt = self.spec.list_type.format(T=self.spec.list_elem_type)

        if self.spec.name == "rust":
            if lo is not None:
                return (f"{{ let mut __v: {lt} = Vec::new(); "
                        f"for {var} in {lo}..{hi} {{ __v.push({elem}); }} __v }}")
            return (f"{{ let mut __v: {lt} = Vec::new(); "
                    f"for {var} in {iter_src} {{ __v.push({elem}); }} __v }}")
        if self.spec.name == "cpp":
            if lo is not None:
                return (f"([&]() {{ auto __v = std::vector<{self.spec.list_elem_type}>{{}}; "
                        f"for (int64_t {var} = {lo}; {var} < {hi}; {var}++) {{ __v.push_back({elem}); }} "
                        f"return __v; }}())")
            return (f"([&]() {{ auto __v = std::vector<{self.spec.list_elem_type}>{{}}; "
                    f"for (auto {var} : {iter_src}) {{ __v.push_back({elem}); }} "
                    f"return __v; }}())")
        if self.spec.name == "csharp":
            if lo is not None:
                # use LINQ: Enumerable.Range(start, count).Select(x => (long)elem).ToList()
                count = f"({hi} - {lo})"
                return f"Enumerable.Range((int)({lo}), (int)({count})).Select({var} => (long)({elem})).ToList()"
            return (f"{{ var __v = new {lt}(); "
                    f"foreach (var {var} in {iter_src}) {{ __v.Add({elem}); }} "
                    f"__v; }}")
        if self.spec.name == "go":
            if lo is not None:
                return (f"func() []int64 {{ var __v []int64; "
                        f"for {var} := {lo}; {var} < {hi}; {var}++ {{ __v = append(__v, int64({elem})) }}; "
                        f"return __v; }}()")
            return (f"func() []int64 {{ var __v []int64; "
                    f"for _, {var} := range {iter_src} {{ __v = append(__v, int64({elem})) }}; "
                    f"return __v; }}()")
        if self.spec.name == "zig":
            if lo is not None:
                return (f"blk: {{ var __v = std.ArrayList({self.spec.list_elem_type}).init(std.heap.page_allocator); "
                        f"var {var}: i64 = {lo}; while ({var} < {hi}) : ({var} += 1) {{ __v.append({elem}) catch unreachable; }} "
                        f"break :blk __v.toOwnedSlice() catch unreachable; }}")
            return self._mark_unsupported('for-in comprehension in Zig')
        if self.spec.name == "kotlin":
            if lo is not None:
                return (f"run {{ val __v = mutableListOf<Long>(); "
                        f"for ({var} in {lo}..{hi}-1) {{ __v.add({elem}); }}; __v }}")
            return (f"run {{ val __v = mutableListOf<Long>(); "
                    f"for ({var} in {iter_src}) {{ __v.add({elem}); }}; __v }}")
        return self._mark_unsupported('list comprehension')

    def _set_comp(self, node: ast.SetComp) -> str:
        """Lower a set comprehension to a block expression that builds a set."""
        if len(node.generators) != 1:
            return self._mark_unsupported('multi-gen set comprehension')
        gen = node.generators[0]
        var = gen.target.id if isinstance(gen.target, ast.Name) else "_"
        it = gen.iter
        elem = self.expr(node.elt)
        if isinstance(it, ast.Call) and getattr(it.func, "id", None) == "range":
            args = it.args
            if len(args) == 1:
                lo, hi = "0", self.expr(args[0])
            elif len(args) == 2:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            else:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            iter_src = None
        else:
            lo, hi = None, None
            iter_src = self.expr(it)
        if self.spec.name == "rust":
            if lo is not None:
                return (f"{{ let mut __s: std::collections::HashSet<i64> = std::collections::HashSet::new(); "
                        f"for {var} in {lo}..{hi} {{ __s.insert({elem}); }} __s }}")
            return (f"{{ let mut __s: std::collections::HashSet<i64> = std::collections::HashSet::new(); "
                    f"for {var} in {iter_src} {{ __s.insert({elem}); }} __s }}")
        if self.spec.name == "cpp":
            if lo is not None:
                return (f"([&]() {{ std::set<int64_t> __s; "
                        f"for (int64_t {var} = {lo}; {var} < {hi}; {var}++) {{ __s.insert({elem}); }} "
                        f"return __s; }}())")
            return (f"([&]() {{ std::set<int64_t> __s; "
                    f"for (auto {var} : {iter_src}) {{ __s.insert({elem}); }} "
                    f"return __s; }}())")
        if self.spec.name == "csharp":
            if lo is not None:
                count = f"({hi} - {lo})"
                return f"Enumerable.Range((int)({lo}), (int)({count})).Select({var} => {elem}).ToHashSet()"
            return f"{iter_src}.Select({var} => {elem}).ToHashSet()"
        if self.spec.name == "kotlin":
            if lo is not None:
                return (f"run {{ val __s = hashSetOf<Long>(); "
                        f"for ({var} in {lo}..{hi}-1) {{ __s.add({elem}) }}; __s }}")
            return (f"run {{ val __s = hashSetOf<Long>(); "
                    f"for ({var} in {iter_src}) {{ __s.add({elem}) }}; __s }}")
        return self._mark_unsupported('set comprehension')

    def _dict_comp(self, node: ast.DictComp) -> str:
        """Lower a dict comprehension to a block expression that builds a dict."""
        if len(node.generators) != 1:
            return self._mark_unsupported('multi-gen dict comprehension')
        gen = node.generators[0]
        var = gen.target.id if isinstance(gen.target, ast.Name) else "_"
        it = gen.iter
        key = self.expr(node.key)
        val = self.expr(node.value)
        if isinstance(it, ast.Call) and getattr(it.func, "id", None) == "range":
            args = it.args
            if len(args) == 1:
                lo, hi = "0", self.expr(args[0])
            elif len(args) == 2:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            else:
                lo, hi = self.expr(args[0]), self.expr(args[1])
            iter_src = None
        else:
            lo, hi = None, None
            iter_src = self.expr(it)
        if self.spec.name == "rust":
            if lo is not None:
                return (f"{{ let mut __m: std::collections::HashMap<i64, i64> = std::collections::HashMap::new(); "
                        f"for {var} in {lo}..{hi} {{ __m.insert({key}, {val}); }} __m }}")
            return (f"{{ let mut __m: std::collections::HashMap<i64, i64> = std::collections::HashMap::new(); "
                    f"for {var} in {iter_src} {{ __m.insert({key}, {val}); }} __m }}")
        if self.spec.name == "cpp":
            if lo is not None:
                return (f"([&]() {{ std::map<int64_t, int64_t> __m; "
                        f"for (int64_t {var} = {lo}; {var} < {hi}; {var}++) {{ __m[{key}] = {val}; }} "
                        f"return __m; }}())")
            return (f"([&]() {{ std::map<int64_t, int64_t> __m; "
                    f"for (auto {var} : {iter_src}) {{ __m[{key}] = {val}; }} "
                    f"return __m; }}())")
        if self.spec.name == "csharp":
            if lo is not None:
                count = f"({hi} - {lo})"
                return f"Enumerable.Range((int)({lo}), (int)({count})).ToDictionary({var} => {key}, {var} => {val})"
            return f"{iter_src}.ToDictionary({var} => {key}, {var} => {val})"
        if self.spec.name == "kotlin":
            if lo is not None:
                return (f"run {{ val __m = hashMapOf<Long, Long>(); "
                        f"for ({var} in {lo}..{hi}-1) {{ __m[{key}] = {val} }}; __m }}")
            return (f"run {{ val __m = hashMapOf<Long, Long>(); "
                    f"for ({var} in {iter_src}) {{ __m[{key}] = {val} }}; __m }}")
        return self._mark_unsupported('dict comprehension')

    def _fstring(self, node: ast.JoinedStr) -> str:
        """Convert an f-string (JoinedStr) to backend-specific string formatting."""
        parts = []
        for val in node.values:
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                parts.append(("text", val.value))
            elif isinstance(val, ast.FormattedValue):
                expr_str = self.expr(val.value)
                t = self.infer_type(val.value)
                parts.append(("expr", expr_str, t))
        # build the format string based on backend
        if self.spec.name == "rust":
            fmt_parts = []
            args = []
            for p in parts:
                if p[0] == "text":
                    fmt_parts.append(p[1].replace("{", "{{").replace("}", "}}"))
                else:
                    fmt_parts.append("{}")
                    args.append(p[1])
            fmt_str = "".join(fmt_parts).replace('"', '\\"')
            args_str = ", ".join(args)
            return f'format!("{fmt_str}", {args_str})'
        if self.spec.name == "csharp":
            # C# interpolated string: $"text {expr} text"
            fmt_parts = []
            for p in parts:
                if p[0] == "text":
                    fmt_parts.append(p[1].replace("{", "{{").replace("}", "}}"))
                else:
                    fmt_parts.append("{" + p[1] + "}")
            return '$"' + "".join(fmt_parts).replace('"', '\\"') + '"'
        if self.spec.name == "kotlin":
            # Kotlin string template: "text ${expr} text"
            fmt_parts = []
            for p in parts:
                if p[0] == "text":
                    fmt_parts.append(p[1].replace("$", "$$").replace('"', '\\"'))
                else:
                    fmt_parts.append("${" + p[1] + "}")
            return '"' + "".join(fmt_parts) + '"'
        if self.spec.name == "go":
            # Go: fmt.Sprintf("text %v text", args...)
            fmt_parts = []
            args = []
            for p in parts:
                if p[0] == "text":
                    fmt_parts.append(p[1].replace("%", "%%"))
                else:
                    fmt_parts.append("%v")
                    args.append(p[1])
            fmt_str = "".join(fmt_parts).replace('"', '\\"')
            args_str = ", ".join(args)
            return f'fmt.Sprintf("{fmt_str}", {args_str})'
        if self.spec.name == "zig":
            # Zig: std.fmt.allocPrint(allocator, "text {d} text", .{args...})
            fmt_parts = []
            args = []
            for p in parts:
                if p[0] == "text":
                    fmt_parts.append(p[1].replace("{", "{{").replace("}", "}}"))
                else:
                    t = p[2]
                    if t == "str":
                        fmt_parts.append("{s}")
                    else:
                        fmt_parts.append("{d}")
                    args.append(p[1])
            fmt_str = "".join(fmt_parts).replace('"', '\\"')
            args_str = ", ".join(args)
            return f'std.fmt.allocPrint(std.heap.page_allocator, "{fmt_str}", .{{{args_str}}}) catch unreachable'
        # C++ default: string concatenation with std::to_string
        concat_parts = []
        for p in parts:
            if p[0] == "text":
                if p[1]:
                    concat_parts.append('"' + p[1].replace('"', '\\"') + '"')
            else:
                t = p[2]
                if t == "str":
                    concat_parts.append(p[1])
                else:
                    concat_parts.append(f"std::to_string({p[1]})")
        if not concat_parts:
            return '""'
        return " + ".join(concat_parts)

    def print_call(self, args: list) -> str:
        if not args:
            return self.spec.print_generic.format(v='""')
        arg = args[0]
        v = self.expr(arg)
        # infer type to choose the right print format
        t = self.infer_type(arg)
        if t == "str":
            return self.spec.print_str.format(v=v)
        if t == "float":
            return self.spec.print_float.format(v=v)
        if t == "bool":
            return self.spec.print_bool.format(v=v)
        if t in ("list", "tuple", "set") and self.spec.print_list:
            return self.spec.print_list.format(v=v)
        # fallback to heuristics on the source text
        if any(c in v for c in ".") and not v.startswith('"'):
            return self.spec.print_float.format(v=v)
        if v in ("true", "false") or v.startswith("!"):
            return self.spec.print_bool.format(v=v)
        if v.startswith('"'):
            return self.spec.print_str.format(v=v)
        return self.spec.print_int.format(v=v)

    # ---- type inference (simple) ----
    def _ann_type(self, node: ast.AST) -> str:
        """Read a PEP 484 annotation node to a tracked type string."""
        if isinstance(node, ast.Name):
            t = node.id
            if t in ("int", "float", "bool", "str", "list", "dict", "tuple", "set"):
                return t
            # class type
            if t in self.class_names:
                return t
            return "int"
        if isinstance(node, ast.Subscript):
            base = _ann_base(node)
            return base if base in ("list", "dict", "tuple", "set") else "list"
        return "int"

    def _list_elem_of_value(self, node: ast.AST) -> str:
        """Native element type of a list-producing expression, or "".

        A bare `list` annotation says nothing about the element type, so it is
        taken from the value: `"a,b".split(",")` yields strings, not ints.
        """
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)):
            attr = node.func.attr
            if attr in ("split", "splitlines", "keys"):
                return self.spec.types.get("str") or self._native_elem_type("str")
            if attr == "values":
                return self.spec.list_elem_type
            if attr in ("copy", "sorted", "reverse"):
                return self._list_elem_of_value(node.func.value) or ""
            if attr == "split" or attr == "items":
                return self.spec.types.get("str", "String")
        if isinstance(node, ast.List):
            types = [self.infer_type(e) for e in node.elts]
            types = [t for t in types if t]
            if types and all(t == types[0] for t in types):
                return self._native_elem_type(types[0])
        if isinstance(node, ast.ListComp):
            return self._native_elem_type(self.infer_type(node.elt))
        if isinstance(node, ast.Subscript):
            return self._list_elem_of_value(node.value)
        return ""

    def _pow(self, left: str, right: str, node: ast.AST) -> str:
        """Render `a ** b`.

        Integer and float exponentiation need different target syntax, and a
        bare literal like `2 ** 10` is ambiguous in Rust, so the operand type
        decides which template is used.
        """
        lt = self.infer_type(node.left)
        rt = self.infer_type(node.right)
        is_float = lt == "float" or rt == "float"
        if is_float and self.spec.pow_float:
            return self.spec.pow_float.format(l=left, r=right)
        if not is_float and self.spec.pow_int:
            return self.spec.pow_int.format(l=left, r=right)
        return self.spec.pow_call.format(l=left, r=right)

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
            return self.var_types.get(node.id, "int")
        if isinstance(node, ast.BinOp):
            lt = self.infer_type(node.left)
            rt = self.infer_type(node.right)
            if isinstance(node.op, ast.Div):
                return "float"
            if isinstance(node.op, ast.Add):
                if lt == "str" or rt == "str":
                    return "str"
                if lt == "list" or rt == "list":
                    return "list"
            if "float" in (lt, rt):
                return "float"
            return "int"
        if isinstance(node, ast.List):
            return "list"
        if isinstance(node, ast.ListComp):
            return "list"
        if isinstance(node, ast.Dict):
            return "dict"
        if isinstance(node, ast.Tuple):
            return "tuple"
        if isinstance(node, ast.JoinedStr):
            return "str"
        if isinstance(node, ast.Subscript):
            base_type = self.infer_type(node.value)
            if isinstance(node.slice, ast.Slice):
                # slicing a string returns a string, slicing a list returns a list
                return base_type if base_type in ("str", "list") else "list"
            if base_type == "str":
                return "int"  # character access returns an integer (char code)
            if base_type == "dict":
                return "int"  # dict values are integers
            if base_type == "tuple":
                return "int"  # tuple elements are integers
            return "int"  # list elements are integers
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None)
            if fname == "len":
                return "int"
            if fname == "float":
                return "float"
            if fname == "int":
                return "int"
            if fname == "str":
                return "str"
            if fname == "bool":
                return "bool"
            if fname == "abs":
                return self.infer_type(node.args[0])
            if fname in ("any", "all", "isinstance"):
                return "bool"
            if fname in ("bin", "hex", "oct", "chr", "repr", "input", "format"):
                return "str"
            if fname in ("ord", "hash"):
                return "int"
            if fname == "divmod":
                return "tuple"
            if fname in ("map", "filter", "sorted", "reversed", "enumerate", "zip", "range"):
                return "list"
            if fname == "round":
                return self.infer_type(node.args[0])
            if fname == "pow":
                return self.infer_type(node.args[0])
            if fname in ("ge_inline", "ge_raw"):
                # inline code — default to int, or use third arg as type hint
                if len(node.args) >= 3 and isinstance(node.args[2], ast.Name):
                    return node.args[2].id
                return "int"
            # class constructor call
            if fname and fname in self.class_names:
                return fname
            # user-defined function call — look up return type
            if fname and fname in self.func_return_types:
                return self.func_return_types[fname]
            # method call: ClassName.method() — look up return type
            if (isinstance(node.func, ast.Attribute) and
                isinstance(node.func.value, ast.Name) and
                node.func.value.id in self.class_names):
                key = f"{node.func.value.id}.{node.func.attr}"
                if key in self.func_return_types:
                    return self.func_return_types[key]
        if isinstance(node, ast.Set):
            return "set"
        if isinstance(node, ast.SetComp):
            return "set"
        if isinstance(node, ast.DictComp):
            return "dict"
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return self.infer_type(node.operand)
            if isinstance(node.op, ast.Not):
                return "bool"
        if isinstance(node, ast.Compare):
            return "bool"
        if isinstance(node, ast.BoolOp):
            return "bool"
        if isinstance(node, ast.IfExp):
            return self.infer_type(node.body)
        if isinstance(node, ast.Attribute):
            # field access — look up class field type
            base_type = self.infer_type(node.value)
            if base_type in self.class_fields:
                for fname, ftype in self.class_fields[base_type]:
                    if fname == node.attr:
                        return ftype
        return "int"

    def binop_symbol(self, op: ast.AST) -> str:
        return {
            ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Mod: "%",
            ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^",
            ast.LShift: "<<", ast.RShift: ">>",
        }.get(type(op), "?")

    def cmp_symbol(self, op: ast.AST) -> str:
        return {
            ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
            ast.Gt: ">", ast.GtE: ">=", ast.Is: "==", ast.IsNot: "!=",
        }.get(type(op), "?")
