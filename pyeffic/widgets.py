"""Widget DSL stubs.

These exist so a UI Python file is valid and importable in pure Python (you can
even render a text preview). pyeffic does NOT execute them at build time — it
interprets the `build()` function's AST directly (see ui.py). But importing this
module lets you run your UI file as plain Python for quick checking.

The `style` parameter accepts a CSS-like string on ALL widgets:
    Text("Hello", style="fontSize:20; bold:true; color:#2196F3")
    Container(child=..., style="bg:#f0f0f0; radius:12; padding:16; border:1,#ccc")
    Column([...], style="align:spaceBetween")

Named shortcuts still work: style="headline", "title", "subtitle", "body".
The same style dict emits to Flutter (now), Slint/Rust/C++ GUI (later) — one
syntax, multiple native targets. See pyeffic/styling.py.
"""
from __future__ import annotations


class Widget:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __repr__(self):
        return f"{type(self).__name__}({self.kwargs})"


class Text(Widget):
    def __init__(self, text: str = "", *, style: str = "body", state: str = ""):
        super().__init__(text=text, style=style, state=state)


class Column(Widget):
    def __init__(self, children, *, align: str = "center"):
        super().__init__(children=children, align=align)


class Row(Widget):
    def __init__(self, children, *, align: str = "center"):
        super().__init__(children=children, align=align)


class Container(Widget):
    def __init__(self, child=None, *, padding: int = 8, color: str = ""):
        super().__init__(child=child, padding=padding, color=color)


class ElevatedButton(Widget):
    def __init__(self, label: str = "", *, on_click=None, style: str = ""):
        super().__init__(label=label, on_click=on_click, style=style)


class SizedBox(Widget):
    """Explicit spacing widget. height=N or width=N."""
    def __init__(self, *, height: float = 0, width: float = 0, style: str = ""):
        super().__init__(height=height, width=width, style=style)


class Divider(Widget):
    """A horizontal line separator."""
    def __init__(self, *, style: str = ""):
        super().__init__(style=style)


class Expanded(Widget):
    """Expands to fill available space in a Row/Column."""
    def __init__(self, child=None, *, flex: int = 1, style: str = ""):
        super().__init__(child=child, flex=flex, style=style)


class Action:
    """Declares a button handler: call an FFI function, store result in state.

    on_click can be a single Action or a LIST of Actions (multi-action: one
    button click triggers several FFI calls and updates several state fields).
    """
    def __init__(self, call: str, args, update: str = ""):
        self.call = call
        self.args = args
        self.update = update

    def __repr__(self):
        return f"Action(call={self.call!r}, args={self.args!r}, update={self.update!r})"


__all__ = ["Widget", "Text", "Column", "Row", "Container", "ElevatedButton",
           "SizedBox", "Divider", "Expanded", "Action"]
