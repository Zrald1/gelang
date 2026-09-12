"""GE UI DSL — a declarative UI designer language.

This is a separate language from the major backends (C++, Rust, Dart, C#,
Zig, Go). It uses a simple, readable syntax to describe UI screens that
compile to Flutter widgets. It can be combined with any backend when
building a complete application.

Syntax example (.ge.ui file):

    Screen "MyRent Dashboard" {
        state: total_rent: int = 0
        state: total_paid: int = 0
        state: outstanding: int = 0

        Column {
            padding: 16
            children:
                Text "Total Rent" style="headline"
                Text state="total_rent" style="value"
                Divider
                Text "Total Paid" style="headline"
                Text state="total_paid" style="value"
                SizedBox height=20
                ElevatedButton "Refresh" on_click=Action(call="compute_total_rent")
        }
    }

The DSL supports:
  - Screen definitions with title and state declarations
  - Container widgets: Column, Row, Container, Expanded, SizedBox
  - Display widgets: Text, Divider, Icon
  - Interactive widgets: ElevatedButton, TextField
  - Style strings: "fontSize:20; bold:true; color:#1565C0"
  - State bindings: state="variable_name"
  - Actions: on_click=Action(call="function_name", args=[...], update="state_var")
  - Named styles: headline, value, title, subtitle, error

The parser produces a tree of WidgetNode dicts that can be converted to
Flutter Dart code by the dartgen module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WidgetNode:
    """A node in the UI widget tree."""
    kind: str
    children: list["WidgetNode"] = field(default_factory=list)
    props: dict[str, Any] = field(default_factory=dict)
    style_dict: dict[str, Any] = field(default_factory=dict)
    state: str | None = None
    text: str | None = None
    label: str | None = None
    action: dict[str, Any] | None = None


@dataclass
class StateVar:
    """A state variable declaration."""
    name: str
    type: str
    default: Any = None


@dataclass
class Screen:
    """A UI screen definition."""
    title: str
    state_vars: list[StateVar] = field(default_factory=list)
    root: WidgetNode | None = None


# ---- Tokenizer ----

class Token:
    def __init__(self, kind: str, value: str, line: int):
        self.kind = kind
        self.value = value
        self.line = line

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, line={self.line})"


def tokenize(source: str) -> list[Token]:
    """Tokenize the UI DSL source."""
    tokens: list[Token] = []
    line = 1
    i = 0
    while i < len(source):
        c = source[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if c == "#":  # comment
            while i < len(source) and source[i] != "\n":
                i += 1
            continue
        if source.startswith('"""', i) or source.startswith("'''", i):
            # module/block docstring — skip to the closing triple quote
            quote = source[i:i + 3]
            end = source.find(quote, i + 3)
            if end == -1:
                end = len(source)
            line += source.count("\n", i, end)
            i = end + 3
            continue
        if c == "{":
            tokens.append(Token("LBRACE", "{", line))
            i += 1
            continue
        if c == "}":
            tokens.append(Token("RBRACE", "}", line))
            i += 1
            continue
        if c == ":":
            tokens.append(Token("COLON", ":", line))
            i += 1
            continue
        if c == "=":
            tokens.append(Token("EQUALS", "=", line))
            i += 1
            continue
        if c == "[":
            tokens.append(Token("LBRACKET", "[", line))
            i += 1
            continue
        if c == "]":
            tokens.append(Token("RBRACKET", "]", line))
            i += 1
            continue
        if c == ",":
            tokens.append(Token("COMMA", ",", line))
            i += 1
            continue
        if c == "(":
            tokens.append(Token("LPAREN", "(", line))
            i += 1
            continue
        if c == ")":
            tokens.append(Token("RPAREN", ")", line))
            i += 1
            continue
        if c == '"':
            # string literal
            j = i + 1
            while j < len(source) and source[j] != '"':
                if source[j] == "\\":
                    j += 1
                j += 1
            tokens.append(Token("STRING", source[i + 1:j], line))
            i = j + 1
            continue
        if c.isdigit() or (c == "-" and i + 1 < len(source) and source[i + 1].isdigit()):
            # number literal
            j = i + 1
            while j < len(source) and (source[j].isdigit() or source[j] == "."):
                j += 1
            tokens.append(Token("NUMBER", source[i:j], line))
            i = j
            continue
        if c.isalpha() or c == "_":
            # identifier or keyword
            j = i + 1
            while j < len(source) and (source[j].isalnum() or source[j] in "_."):
                j += 1
            word = source[i:j]
            tokens.append(Token("IDENT", word, line))
            i = j
            continue
        raise SyntaxError(f"Unexpected character {c!r} at line {line}")

    tokens.append(Token("EOF", "", line))
    return tokens


# ---- Parser ----

CONTAINER_WIDGETS = {"Column", "Row", "Container", "Expanded", "SizedBox",
                     "ListView", "Stack", "Padding", "Center", "Card",
                     "Scaffold", "AppBar"}
LEAF_WIDGETS = {"Text", "Divider", "Icon", "ElevatedButton", "TextButton",
                "TextField", "Image", "CircularProgressIndicator",
                "Switch", "Checkbox", "Slider"}
ALL_WIDGETS = CONTAINER_WIDGETS | LEAF_WIDGETS


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def next(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, kind: str) -> Token:
        t = self.next()
        if t.kind != kind:
            raise SyntaxError(f"Expected {kind} but got {t.kind} ({t.value!r}) at line {t.line}")
        return t

    def parse_screen(self) -> Screen:
        """Parse a screen definition.

        Both forms are accepted:
            Screen "My App" { ... }
            Window { title: "My App" ... }
        """
        self.expect("IDENT")  # "Screen" / "Window"
        title = ""
        if self.peek().kind == "STRING":
            title = self.next().value
        screen = Screen(title=title)
        self.expect("LBRACE")

        while self.peek().kind != "RBRACE":
            t = self.peek()
            if t.kind == "IDENT" and t.value in ("title", "name"):
                self.next()  # consume "title" / "name"
                self.expect("COLON")
                screen.title = self.expect("STRING").value
            elif t.kind == "IDENT" and t.value == "state":
                self.next()  # consume "state"
                self.expect("COLON")
                state_var = self.parse_state_decl()
                screen.state_vars.append(state_var)
            elif t.kind == "IDENT" and t.value in ALL_WIDGETS:
                widget = self.parse_widget()
                screen.root = widget
            elif t.kind == "IDENT" and t.value == "children":
                self.next()  # consume "children"
                self.expect("COLON")
                # parse child widgets until we hit something that's not a widget
                while self.peek().kind == "IDENT" and self.peek().value in ALL_WIDGETS:
                    child = self.parse_widget()
                    if screen.root is None:
                        screen.root = WidgetNode(kind="Column")
                    screen.root.children.append(child)
            else:
                raise SyntaxError(f"Unexpected token {t.value!r} at line {t.line}")

        self.expect("RBRACE")
        return screen

    def parse_state_decl(self) -> StateVar:
        """Parse a state variable declaration: name: type = default"""
        name_tok = self.expect("IDENT")
        self.expect("COLON")
        type_tok = self.expect("IDENT")
        default = None
        if self.peek().kind == "EQUALS":
            self.next()
            dt = self.next()
            if dt.kind == "NUMBER":
                default = int(dt.value) if "." not in dt.value else float(dt.value)
            elif dt.kind == "STRING":
                default = dt.value
            elif dt.kind == "IDENT":
                if dt.value == "true":
                    default = True
                elif dt.value == "false":
                    default = False
                else:
                    default = dt.value
        return StateVar(name=name_tok.value, type=type_tok.value, default=default)

    def parse_widget(self) -> WidgetNode:
        """Parse a widget definition."""
        kind_tok = self.expect("IDENT")
        node = WidgetNode(kind=kind_tok.value)

        # handle text/label directly after widget name: Text "Hello" or Button "Click"
        if self.peek().kind == "STRING":
            text_tok = self.next()
            if kind_tok.value == "Text":
                node.text = text_tok.value
            elif kind_tok.value in ("ElevatedButton", "TextButton"):
                node.label = text_tok.value
            else:
                node.props["text"] = text_tok.value

        # parse properties until we see children or RBRACE
        while self.peek().kind == "IDENT":
            prop_tok = self.peek()
            if prop_tok.value in ALL_WIDGETS:
                # this is a child widget, not a property
                break
            if prop_tok.value == "children":
                self.next()
                self.expect("COLON")
                while self.peek().kind == "IDENT" and self.peek().value in ALL_WIDGETS:
                    child = self.parse_widget()
                    node.children.append(child)
                break
            # parse property: name = value or name: value
            self.next()  # consume property name
            if self.peek().kind == "COLON":
                self.next()
            elif self.peek().kind == "EQUALS":
                self.next()
            else:
                # property without value (e.g., "Divider")
                node.props[prop_tok.value] = True
                continue

            val_tok = self.next()
            if val_tok.kind == "STRING":
                if prop_tok.value == "style":
                    from .styling import parse_style
                    node.style_dict = parse_style(val_tok.value)
                elif prop_tok.value == "state":
                    node.state = val_tok.value
                elif prop_tok.value == "text":
                    node.text = val_tok.value
                elif prop_tok.value == "label":
                    node.label = val_tok.value
                elif prop_tok.value == "on_click":
                    node.action = {"call": val_tok.value}
                else:
                    node.props[prop_tok.value] = val_tok.value
            elif val_tok.kind == "NUMBER":
                if "." in val_tok.value:
                    node.props[prop_tok.value] = float(val_tok.value)
                else:
                    node.props[prop_tok.value] = int(val_tok.value)
            elif val_tok.kind == "IDENT":
                if val_tok.value == "Action":
                    # parse Action(call="fn", args=[...], update="state")
                    node.action = self.parse_action()
                elif val_tok.value in ("true", "false"):
                    node.props[prop_tok.value] = (val_tok.value == "true")
                else:
                    node.props[prop_tok.value] = val_tok.value

        # parse body block if present
        if self.peek().kind == "LBRACE":
            self.next()  # consume {
            while self.peek().kind != "RBRACE":
                if self.peek().kind == "IDENT" and self.peek().value in ALL_WIDGETS:
                    child = self.parse_widget()
                    node.children.append(child)
                elif self.peek().kind == "IDENT" and self.peek().value == "children":
                    self.next()
                    self.expect("COLON")
                    while self.peek().kind == "IDENT" and self.peek().value in ALL_WIDGETS:
                        child = self.parse_widget()
                        node.children.append(child)
                elif self.peek().kind == "STRING":
                    # bare string in body — treat as Text widget
                    text_tok = self.next()
                    child = WidgetNode(kind="Text", text=text_tok.value)
                    node.children.append(child)
                elif self.peek().kind == "IDENT":
                    # property inside body block: name: value or name = value
                    prop_tok = self.next()
                    if self.peek().kind == "COLON":
                        self.next()
                    elif self.peek().kind == "EQUALS":
                        self.next()
                    else:
                        node.props[prop_tok.value] = True
                        continue
                    val_tok = self.next()
                    if val_tok.kind == "STRING":
                        if prop_tok.value == "style":
                            from .styling import parse_style
                            node.style_dict = parse_style(val_tok.value)
                        elif prop_tok.value == "state":
                            node.state = val_tok.value
                        elif prop_tok.value == "text":
                            node.text = val_tok.value
                        elif prop_tok.value == "label":
                            node.label = val_tok.value
                        elif prop_tok.value == "on_click":
                            node.action = {"call": val_tok.value}
                        else:
                            node.props[prop_tok.value] = val_tok.value
                    elif val_tok.kind == "NUMBER":
                        if "." in val_tok.value:
                            node.props[prop_tok.value] = float(val_tok.value)
                        else:
                            node.props[prop_tok.value] = int(val_tok.value)
                    elif val_tok.kind == "IDENT":
                        if val_tok.value == "Action":
                            node.action = self.parse_action()
                        elif val_tok.value in ("true", "false"):
                            node.props[prop_tok.value] = (val_tok.value == "true")
                        else:
                            node.props[prop_tok.value] = val_tok.value
                else:
                    raise SyntaxError(f"Unexpected token in widget body: {self.peek().value!r}")
            self.expect("RBRACE")

        return node

    def parse_action(self) -> dict[str, Any]:
        """Parse an Action(...) expression."""
        self.expect("LPAREN")
        action: dict[str, Any] = {"args": []}
        while self.peek().kind != "RPAREN":
            prop = self.expect("IDENT")
            self.expect("EQUALS")
            val = self.next()
            if val.kind == "STRING":
                action[prop.value] = val.value
            elif val.kind == "NUMBER":
                action[prop.value] = int(val.value) if "." not in val.value else float(val.value)
            elif val.kind == "LBRACKET":
                # parse array
                while self.peek().kind != "RBRACKET":
                    v = self.next()
                    if v.kind == "STRING":
                        action["args"].append(v.value)
                    elif v.kind == "NUMBER":
                        action["args"].append(int(v.value) if "." not in v.value else float(v.value))
                    if self.peek().kind == "COMMA":
                        self.next()
                self.expect("RBRACKET")
            if self.peek().kind == "COMMA":
                self.next()
        self.expect("RPAREN")
        return action


def parse_ui_dsl(source: str) -> Screen:
    """Parse a .ge.ui file and return a Screen definition."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse_screen()


def parse_ui_file(path) -> Screen:
    """Parse a .ge.ui file from disk."""
    from pathlib import Path
    p = Path(path)
    source = p.read_text(encoding="utf-8")
    return parse_ui_dsl(source)


def collect_state_from_screen(screen: Screen) -> dict[str, str]:
    """Collect all state variables referenced in the screen."""
    states: dict[str, str] = {}
    for sv in screen.state_vars:
        states[sv.name] = sv.type
    if screen.root:
        _collect_state_recursive(screen.root, states)
    return states


def _collect_state_recursive(node: WidgetNode, states: dict[str, str]) -> None:
    if node.state:
        states[node.state] = "int"  # default type
    if node.action and "update" in node.action:
        states[node.action["update"]] = "int"
    for child in node.children:
        _collect_state_recursive(child, states)


# ---- Flutter code generation from UI DSL ----

def ui_dsl_to_flutter(screen: Screen) -> str:
    """Convert a parsed UI DSL Screen to Flutter Dart code.

    This generates a complete Flutter widget that can be merged into
    main.dart alongside the existing UI generation.
    """
    lines: list[str] = []
    lines.append("// AUTO-GENERATED from GE UI DSL — do not edit by hand.")
    lines.append("import 'package:flutter/material.dart';")
    lines.append("import 'bindings.dart' as ffi;")
    lines.append("")

    # generate state class
    class_name = screen.title.replace(" ", "") + "Screen"
    lines.append(f"class {class_name} extends StatefulWidget {{")
    lines.append(f"  const {class_name}({{super.key}});")
    lines.append(f"  @override")
    lines.append(f"  State<{class_name}> createState() => _{class_name}State();")
    lines.append(f"}}")
    lines.append("")

    # generate state class body
    lines.append(f"class _{class_name}State extends State<{class_name}> {{")
    for sv in screen.state_vars:
        dart_type = _dart_type(sv.type)
        default_val = _dart_default(sv.default, sv.type)
        lines.append(f"  {dart_type} {sv.name} = {default_val};")
    lines.append("")

    lines.append("  @override")
    lines.append("  Widget build(BuildContext context) {")
    lines.append("    return Scaffold(")
    lines.append(f"      appBar: AppBar(title: const Text('{screen.title}')),")
    lines.append("      body: " + _widget_to_flutter(screen.root, 8))
    lines.append("    );")
    lines.append("  }")
    lines.append("}")

    return "\n".join(lines) + "\n"


def _dart_type(ge_type: str) -> str:
    return {"int": "int", "float": "double", "bool": "bool",
            "str": "String", "string": "String"}.get(ge_type, "int")


def _dart_default(val: Any, ge_type: str) -> str:
    if val is None:
        return {"int": "0", "float": "0.0", "bool": "false",
                "str": "''", "string": "''"}.get(ge_type, "0")
    if isinstance(val, str):
        return f"'{val}'"
    return str(val)


def _widget_to_flutter(node: WidgetNode | None, indent: int) -> str:
    """Convert a widget node to Flutter Dart code."""
    if node is None:
        return "const SizedBox.shrink()"
    ind = " " * indent
    kind = node.kind

    if kind == "Column":
        children = ",\n".join(_widget_to_flutter(c, indent + 6) for c in node.children)
        return f"Column(\n{ind}  crossAxisAlignment: CrossAxisAlignment.start,\n{ind}  children: [\n{children},\n{ind}  ],\n{ind})"
    elif kind == "Row":
        children = ",\n".join(_widget_to_flutter(c, indent + 6) for c in node.children)
        return f"Row(\n{ind}  children: [\n{children},\n{ind}  ],\n{ind})"
    elif kind == "Text":
        if node.state:
            return f"Text('$\\{{{node.state}\\}}', style: {_style_to_flutter(node.style_dict)})"
        elif node.text:
            return f"Text('{node.text}', style: {_style_to_flutter(node.style_dict)})"
        return "Text('')"
    elif kind == "Divider":
        return "const Divider()"
    elif kind == "SizedBox":
        h = node.props.get("height", "")
        w = node.props.get("width", "")
        if h and w:
            return f"const SizedBox(height: {h}, width: {w})"
        elif h:
            return f"const SizedBox(height: {h})"
        elif w:
            return f"const SizedBox(width: {w})"
        return "const SizedBox.shrink()"
    elif kind == "ElevatedButton":
        label = node.label or node.text or "Click"
        if node.action:
            call = node.action.get("call", "")
            update = node.action.get("update", "")
            if update:
                return f"ElevatedButton(onPressed: () {{ setState(() {{ {update} = ffi.{call}(); }}); }}, child: const Text('{label}'))"
            else:
                return f"ElevatedButton(onPressed: () {{ ffi.{call}(); }}, child: const Text('{label}'))"
        return f"ElevatedButton(onPressed: () {{}}, child: const Text('{label}'))"
    elif kind == "Container":
        padding = node.style_dict.get("padding", 0)
        child = _widget_to_flutter(node.children[0] if node.children else None, indent + 2)
        return f"Container(padding: const EdgeInsets.all({padding}), child: {child})"
    elif kind == "Expanded":
        child = _widget_to_flutter(node.children[0] if node.children else None, indent + 2)
        return f"Expanded(child: {child})"
    elif kind == "Card":
        child = _widget_to_flutter(node.children[0] if node.children else None, indent + 2)
        return f"Card(child: {child})"
    elif kind == "Center":
        child = _widget_to_flutter(node.children[0] if node.children else None, indent + 2)
        return f"Center(child: {child})"
    elif kind == "Padding":
        padding = node.props.get("padding", 16)
        child = _widget_to_flutter(node.children[0] if node.children else None, indent + 2)
        return f"Padding(padding: const EdgeInsets.all({padding}), child: {child})"
    else:
        return f"// Unknown widget: {kind}"


def _style_to_flutter(style_dict: dict[str, Any]) -> str:
    """Convert a style dict to a Flutter TextStyle."""
    if not style_dict:
        return "const TextStyle()"
    parts = []
    if "fontSize" in style_dict:
        parts.append(f"fontSize: {style_dict['fontSize']}")
    if style_dict.get("bold"):
        parts.append("fontWeight: FontWeight.bold")
    if "color" in style_dict:
        color = style_dict["color"]
        if color.startswith("#"):
            parts.append(f"color: const Color(0xFF{color[1:]})")
        else:
            parts.append(f"color: Colors.{_map_color(color)}")
    if not parts:
        return "const TextStyle()"
    return f"TextStyle({', '.join(parts)})"


def _map_color(color: str) -> str:
    """Map a named color to a Flutter Colors name."""
    mapping = {
        "red": "red", "blue": "blue", "green": "green",
        "black": "black", "white": "white", "grey": "grey",
        "orange": "orange", "purple": "purple", "teal": "teal",
    }
    return mapping.get(color, "black")
