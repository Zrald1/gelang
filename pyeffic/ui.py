"""Interpret the `build()` function's AST into a widget tree.

Does NOT execute the Python — it walks the AST of `build()` and evaluates
widget-constructor calls with literal/nested args into a plain dict tree. This
is safe (no arbitrary code execution) and deterministic.

Tree node shapes:
  {"kind": "Text", "text": str, "style": str, "state": str}
  {"kind": "Column"|"Row", "children": [node,...], "align": str}
  {"kind": "Container", "child": node|None, "padding": int, "color": str}
  {"kind": "Button", "label": str, "action": action_node|None}
  {"kind": "Action", "call": str, "args": [literal,...], "update": str}
"""
from __future__ import annotations

import ast

from .styling import parse_style

WIDGETS = {"Text", "Column", "Row", "Container", "ElevatedButton",
           "SizedBox", "Divider", "Expanded"}


class UIParseError(Exception):
    pass


def _lit(node: ast.AST):
    """Evaluate a literal/constant node."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_lit(node.operand)
    raise UIParseError(f"expected a literal, got {type(node).__name__}")


def _parse_action_or_list(on_click):
    """on_click can be a single Action dict or a list of Action dicts."""
    if on_click is None:
        return None
    if isinstance(on_click, list):
        return on_click
    return [on_click]


def _eval(node: ast.AST):
    """Evaluate a widget expression node into a tree dict."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_eval(e) for e in node.elts]
    if isinstance(node, ast.Call):
        fname = getattr(node.func, "id", None)
        if fname == "Action":
            kw = {k.arg: _lit(k.value) if isinstance(k.value, ast.Constant) else _eval(k.value)
                  for k in node.keywords}
            args = [_eval(a) for a in node.args]
            call = kw.get("call") or (args[0] if args else "")
            arglist = kw.get("args") or (args[1] if len(args) > 1 else [])
            update = kw.get("update") or (args[2] if len(args) > 2 else "")
            return {"kind": "Action", "call": call, "args": arglist, "update": update}
        if fname in WIDGETS:
            kw = {k.arg: (_lit(k.value) if isinstance(k.value, ast.Constant) else _eval(k.value))
                  for k in node.keywords}
            pos = [_eval(a) for a in node.args]
            if fname == "Text":
                text = kw.get("text") or (pos[0] if pos else "")
                style_raw = kw.get("style", "body")
                return {"kind": "Text", "text": text,
                        "style": style_raw, "style_dict": parse_style(style_raw),
                        "state": kw.get("state", "")}
            if fname in ("Column", "Row"):
                children = kw.get("children") or (pos[0] if pos else [])
                style_raw = kw.get("style", "")
                return {"kind": fname, "children": children,
                        "align": kw.get("align", "center"),
                        "style_dict": parse_style(style_raw)}
            if fname == "Container":
                child = kw.get("child") or (pos[0] if pos else None)
                style_raw = kw.get("style", "")
                return {"kind": "Container", "child": child,
                        "padding": kw.get("padding", 8), "color": kw.get("color", ""),
                        "style_dict": parse_style(style_raw)}
            if fname == "ElevatedButton":
                label = kw.get("label") or (pos[0] if pos else "")
                style_raw = kw.get("style", "")
                # on_click can be a single Action or a list of Actions
                on_click = kw.get("on_click")
                action = _parse_action_or_list(on_click)
                return {"kind": "Button", "label": label, "action": action,
                        "style_dict": parse_style(style_raw)}
            if fname == "SizedBox":
                return {"kind": "SizedBox",
                        "height": kw.get("height", 0),
                        "width": kw.get("width", 0),
                        "style_dict": parse_style(kw.get("style", ""))}
            if fname == "Divider":
                return {"kind": "Divider",
                        "style_dict": parse_style(kw.get("style", ""))}
            if fname == "Expanded":
                child = kw.get("child") or (pos[0] if pos else None)
                return {"kind": "Expanded", "child": child,
                        "flex": kw.get("flex", 1),
                        "style_dict": parse_style(kw.get("style", ""))}
        raise UIParseError(f"unsupported call: {fname}")
    raise UIParseError(f"unsupported expression: {type(node).__name__}")


def parse_ui(source: str) -> dict:
    """Parse a Python source string, find `build()`, return its widget tree."""
    tree = ast.parse(source)
    build_fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build":
            build_fn = node
            break
    if build_fn is None:
        raise UIParseError("no build() function found in UI source")
    # build() must be a single return of a widget tree
    ret = None
    for stmt in build_fn.body:
        if isinstance(stmt, ast.Return):
            ret = stmt
            break
    if ret is None or ret.value is None:
        raise UIParseError("build() must return a widget tree")
    return _eval(ret.value)


def collect_state(tree: dict) -> set[str]:
    """Find all state field names referenced (Text state= / Action update=)."""
    fields: set[str] = set()

    def walk(n):
        if not isinstance(n, dict):
            return
        k = n.get("kind")
        if k == "Text" and n.get("state"):
            fields.add(n["state"])
        if k == "Button" and isinstance(n.get("action"), list):
            for act in n["action"]:
                upd = act.get("update")
                if upd:
                    fields.add(upd)
        for key in ("children", "child"):
            v = n.get(key)
            if isinstance(v, list):
                for c in v:
                    walk(c)
            elif isinstance(v, dict):
                walk(v)

    walk(tree)
    return fields
