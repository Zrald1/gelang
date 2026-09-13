"""C++ backend spec + program assembly."""
from __future__ import annotations

import ast

from .base import Emitter, Spec
from ..analyzer import FuncUnit

SPEC = Spec(
    name="cpp",
    types={"int": "int64_t", "float": "double", "bool": "bool", "str": "std::string", "None": "void"},
    list_type="std::vector<{T}>",
    list_param_type="std::vector<int64_t>&",
    list_elem_type="int64_t",
    list_sort="std::sort({x}.begin(), {x}.end())",
    list_reverse="std::reverse({x}.begin(), {x}.end())",
    str_split="geStrSplit({x}, {sep})",
    str_upper="geStrUpper({x})",
    str_lower="geStrLower({x})",
    str_replace="geStrReplace({x}, {a}, {b})",
    str_join="geStrJoin({x}, {sep})",
    list_slice="std::vector<int64_t>({x}.begin() + ({start}), {x}.begin() + ({stop}))",
    list_copy="std::vector<int64_t>({x})",
    borrow_list_arg=False,
    range_call="for_range({lo}, {hi})",
    range_step_call="for_range({lo}, {hi}, {step})",
    len_call="static_cast<int64_t>({x}.size())",
    list_len="static_cast<int64_t>({x}.size())",
    print_int='std::cout << ({v}) << std::endl',
    print_float='std::cout << ({v}) << std::endl',
    print_str='std::cout << ({v}) << std::endl',
    print_bool='std::cout << (({v}) ? "True" : "False") << std::endl',
    print_generic='std::cout << ({v}) << std::endl',
    print_list='std::cout << geListStr({v}) << std::endl',
    int_cast="static_cast<int64_t>({x})",
    float_cast="static_cast<double>({x})",
    float_div="(static_cast<double>({l}) / static_cast<double>({r}))",
    floor_div="({l} / {r})",
    sum_call="std::accumulate({it}.begin(), {it}.end(), 0LL)",
    abs_int="std::abs({x})",
    abs_float="std::fabs({x})",
    min2_call="std::min({a}, {b})",
    max2_call="std::max({a}, {b})",
    min_call="*std::min_element({it}.begin(), {it}.end())",
    max_call="*std::max_element({it}.begin(), {it}.end())",
    pow_call="std::pow({l}, {r})",
    pow_int="static_cast<int64_t>(std::pow(static_cast<double>({l}), static_cast<double>({r})))",
    pow_float="std::pow({l}, {r})",
    append_call="{x}.push_back({v})",
    index_call="{x}[{i}]",
    comment="//",
    fn_template="{sig} {{\n{body}\n}}",
    main_template="",
    ffi_prefix='extern "C" ',
    str_concat="{l} + {r}",
    str_len="static_cast<int64_t>({x}.length())",
    str_index="std::string(1, ({x})[({i})])",
    str_slice="{x}.substr({start}, {len})",
    str_slice_start="{x}.substr({start})",
    str_slice_end="{x}.substr(0, {end})",
    list_concat="[&]() {{ auto t = {l}; auto s = {r}; t.insert(t.end(), s.begin(), s.end()); return t; }}()",
    foreach_template="for (auto {var} : {iter})",
    try_template="try {{\n{body}\n}} catch (...) {{\n{handler}\n}}",
    struct_template="struct {name} {{\n{fields}\n}};",
    struct_field_template="    {type} {name};",
    struct_new_template="{name} {name}_new({params}) {{\n{body}\n}}",
    dict_type="std::map<std::string, {V}>",
    set_type="std::set<int64_t>",
    dict_get="{d}.at({k})",
    dict_set="{d}[{k}] = {v}",
    dict_keys="geDictKeys({x})",
    dict_contains="({d}.find({k}) != {d}.end())",
    tuple_type="std::tuple<{T}, {T}>",
    tuple_get="std::get<{i}>({t})",
)


class CppEmitter(Emitter):
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
            if step == "1":
                self.lines.append(f"{ind}for (int64_t {var} = {lo}; {var} < {hi}; ++{var}) {{")
            else:
                self.lines.append(
                    f"{ind}for (int64_t {var} = {lo}; {var} < {hi}; {var} += {step}) {{"
                )
        else:
            iter_s = self.expr(it)
            if self.infer_type(it) == "dict":
                self.var_types[var] = "str"
                self.lines.append(
                    f"{ind}for (auto {var} : geDictKeys({iter_s})) {{")
            else:
                self.var_types[var] = "int"
                self.lines.append(f"{ind}for (auto& {var} : {iter_s}) {{")
        self.indent_lvl += 1
        for s in node.body:
            self.stmt(s)
        self.indent_lvl -= 1
        self.lines.append(f"{ind}}}")


def _entry_unit(units: list[FuncUnit], entry: str | None) -> FuncUnit:
    if entry:
        for u in units:
            if u.name == entry:
                return u
    for u in units:
        if u.name == "main":
            return u
    return units[0]


def _emit_structs_cpp(classes: list) -> str:
    """Emit C++ struct definitions and constructors for ClassUnits."""
    out: list[str] = []
    for cls in classes:
        fields_str = ""
        for fname, ftype in cls.fields:
            nt = SPEC.types.get(ftype, SPEC.types.get("float"))
            if ftype == "list":
                nt = "std::vector<int64_t>"
            elif ftype not in SPEC.types:
                nt = "double"
            fields_str += f"    {nt} {fname};\n"
        out.append(f"struct {cls.name} {{\n{fields_str}}};\n")
        # constructor
        if cls.constructor_params:
            params_str = ", ".join(
                f"{SPEC.types.get(ptype, 'double')} {pname}"
                for pname, ptype in cls.constructor_params
            )
            init_list = ", ".join(fname for fname, _ in cls.constructor_params)
            out.append(f"{cls.name} {cls.name}_new({params_str}) {{\n"
                        f"    return {cls.name}{{{init_list}}};\n}}\n")
        else:
            out.append(f"{cls.name} {cls.name}_new() {{\n"
                        f"    return {cls.name}{{}};\n}}\n")
    return "\n".join(out)


def emit_cpp(units: list[FuncUnit], entry: str | None,
             library_mode: bool = False,
             extern_fns: list[FuncUnit] | None = None,
             classes: list | None = None,
             constants: dict | None = None,
             preamble: dict | None = None) -> tuple[str, dict[str, str]]:
    emitter = CppEmitter(SPEC)
    emitter.func_signatures = {
        u.name: ([p for p, _t in u.params],
                 dict(getattr(u, 'param_defaults', {})))
        for u in units
    }
    emitter.library_mode = library_mode
    emitter.constants = constants or {}
    # in multi-backend mode, force extern "C" on all functions so Rust can link
    emitter.force_extern_c = extern_fns is not None
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
        "#include <cstdint>\n"
        "#include <iostream>\n"
        "#include <vector>\n"
        "#include <map>\n"
        "#include <tuple>\n"
        "#include <cmath>\n"
        "#include <numeric>\n"
        "#include <algorithm>\n"
        "#include <set>\n"
        "#include <cctype>\n"
        "#include <string>\n\n"
        "using std::cout;\n"
        "using std::endl;\n\n"
    )

    # emit extern "C" declarations for cross-backend calls (Rust functions)
    if extern_fns:
        decls = []
        for u in extern_fns:
            if not u.supported:
                continue
            params = ", ".join(
                f"{'const std::vector<int64_t>&' if ptype == 'list' else SPEC.types.get(ptype, 'double')} {pname}"
                for pname, ptype in u.params)
            ret = SPEC.types.get(u.ret_type, "void") if u.ret_type != "None" else "void"
            decls.append(f'extern "C" {ret} {u.name}({params});')
        prelude += "\n// cross-backend declarations (Rust functions called from C++)\n" + "\n".join(decls) + "\n\n"

    # emit struct definitions
    if classes:
        struct_code = _emit_structs_cpp(classes)
        if struct_code:
            prelude += struct_code + "\n"

    # build function return type lookup for type inference
    for u in units:
        if u.supported:
            emitter.func_return_types[u.name] = u.ret_type

    # emit forward declarations so functions can call each other regardless of order
    # (also needed before preamble so preamble code can call GE-compiled functions)
    forward_decls: list[str] = []
    for u in units:
        if not u.supported or (u.is_method and u.name.endswith(".__init__")):
            continue
        params = ", ".join(
            f"{'std::vector<int64_t>' if ptype == 'list' else SPEC.types.get(ptype, 'double')} {pname}"
            for pname, ptype in u.params
        ) or ""
        # main always returns int in C++; list returns std::vector<int64_t>
        if u.name == "main":
            ret = "int"
        elif u.ret_type == "None":
            ret = "void"
        elif u.ret_type == "list":
            ret = "std::vector<int64_t>"
        else:
            ret = SPEC.types.get(u.ret_type, "void")
        if emitter.force_extern_c:
            forward_decls.append(f'extern "C" {ret} {u.name}({params});')
        else:
            forward_decls.append(f'{ret} {u.name}({params});')
    if forward_decls:
        prelude += "\n// forward declarations\n" + "\n".join(forward_decls) + "\n\n"

    # inject user preamble (file-scope code from ge_preamble("cpp", "..."))
    # (after forward declarations so preamble can call GE-compiled functions)
    if preamble and "cpp" in preamble:
        prelude += "\n// === user preamble (ge_preamble) ===\n" + preamble["cpp"] + "\n\n"

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
        if u is entry_u and u.name == "main":
            code = emitter.emit(u, sig_override="int main()", body_suffix="return 0;")
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
            wrapper = "int main() {\n    " + entry_u.name + "();\n    return 0;\n}\n"
        else:
            wrapper = "int main() {\n    auto _r = " + entry_u.name + "();\n    (void)_r;\n    return 0;\n}\n"
        fns.append(wrapper)

    program = prelude + "\n".join(fns) + "\n"
    # inject stdlib runtime after the prelude so #include <cmath> is in scope
    from ..stdlib import get_runtime
    runtime = get_runtime("cpp")
    if runtime:
        program = prelude + runtime + "\n" + "\n".join(fns) + "\n"
    return program, emitted
