"""GE styling: a CSS-like style DSL that emits to multiple native targets.

One syntax, many backends. Write:
    style="fontSize:20; bold:true; color:#2196F3; padding:16; radius:12"

The parser turns it into a target-agnostic dict:
    {"fontSize": 20, "bold": True, "color": "#2196F3", "padding": 16, "radius": 12}

Emitters then convert that dict to target-native code:
  - style_to_flutter() -> TextStyle / EdgeInsets / BoxDecoration / Color
  - style_to_slint()   -> Slint property blocks (Rust/C++ GUI)  [stub for later]

This is the same pattern Slint (HTML/CSS-like DSL for Rust) and Wind (Tailwind
for Flutter) use, but unified under GE's single-source model.
"""
from __future__ import annotations

import re

# ---- named style shortcuts (backward-compatible with the old style="headline") ----
NAMED_STYLES: dict[str, str] = {
    "headline":  "fontSize:28; bold:true",
    "title":     "fontSize:20; bold:true",
    "subtitle":  "fontSize:16; color:grey700",
    "body":      "fontSize:16",
    "caption":   "fontSize:13; color:grey600",
    "button":    "fontSize:16; bold:true; color:white",
}

# named colors -> Flutter Colors.xxx (None = use hex Color(0xFF...))
NAMED_COLORS: dict[str, str] = {
    "red": "Colors.red", "blue": "Colors.blue", "green": "Colors.green",
    "white": "Colors.white", "black": "Colors.black", "grey": "Colors.grey",
    "orange": "Colors.orange", "yellow": "Colors.yellow", "purple": "Colors.purple",
    "pink": "Colors.pink", "teal": "Colors.teal", "cyan": "Colors.cyan",
    "indigo": "Colors.indigo", "lime": "Colors.lime", "amber": "Colors.amber",
    "brown": "Colors.brown",
}

# grey shade tokens like "grey700" -> Colors.grey[700]
def _grey_shade(token: str) -> str | None:
    m = re.fullmatch(r"grey(\d+)", token)
    if m:
        return f"Colors.grey[{m.group(1)}]"
    return None


def parse_style(style_str: str) -> dict:
    """Parse a CSS-like style string into a dict. Handles named shortcuts."""
    if not style_str:
        return {}
    s = style_str.strip()
    # named shortcut?
    if s in NAMED_STYLES:
        return parse_style(NAMED_STYLES[s])
    # also allow "headline; color:blue" (named + overrides)
    parts = [p.strip() for p in s.split(";") if p.strip()]
    result: dict = {}
    for part in parts:
        if part in NAMED_STYLES:
            result.update(parse_style(NAMED_STYLES[part]))
            continue
        if ":" not in part:
            continue
        key, val = part.split(":", 1)
        key = key.strip()
        val = val.strip()
        result[key] = _parse_value(key, val)
    return result


def _parse_value(key: str, val: str):
    """Convert a string value to the right Python type per property."""
    if key in ("bold", "italic", "underline"):
        return val.lower() in ("true", "yes", "1")
    if key in ("fontSize", "padding", "margin", "radius", "width", "height",
               "letterSpacing", "border", "gap", "spacing"):
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                return val
    # color / bg / border color: keep as string
    return val


# ---- Flutter emitter ----

def _flutter_color(val: str) -> str:
    """Convert a color value to a Flutter Dart expression."""
    if not isinstance(val, str):
        val = str(val)
    if val.startswith("#"):
        hexv = val[1:]
        if len(hexv) == 3:
            hexv = "".join(c * 2 for c in hexv)
        return f"Color(0xFF{hexv})"
    grey = _grey_shade(val)
    if grey:
        return grey
    # shade tokens like "blue.shade50"
    if ".shade" in val:
        name, shade = val.split(".shade")
        if name in NAMED_COLORS:
            return f"{NAMED_COLORS[name]}.shade{shade}"
    if val in NAMED_COLORS:
        return NAMED_COLORS[val]
    # fallback: treat as hex without #
    return f"Color(0xFF{val})"


def style_to_flutter_text(d: dict) -> str:
    """Emit a Flutter TextStyle from a style dict (text-related props)."""
    if not d:
        return "TextStyle(fontSize: 16)"
    parts = []
    if "fontSize" in d:
        parts.append(f"fontSize: {d['fontSize']}")
    if d.get("bold"):
        parts.append("fontWeight: FontWeight.bold")
    if d.get("italic"):
        parts.append("fontStyle: FontStyle.italic")
    if "color" in d:
        parts.append(f"color: {_flutter_color(d['color'])}")
    if "letterSpacing" in d:
        parts.append(f"letterSpacing: {d['letterSpacing']}")
    if not parts:
        return "TextStyle(fontSize: 16)"
    return f"TextStyle({', '.join(parts)})"


def style_to_flutter_padding(d: dict, key: str = "padding") -> str:
    """Emit Flutter EdgeInsets from padding/margin."""
    if key not in d:
        return "EdgeInsets.all(0)"
    v = d[key]
    return f"EdgeInsets.all({v})"


def style_to_flutter_box(d: dict) -> str:
    """Emit a Flutter BoxDecoration from bg/radius/border props."""
    decs = []
    if "bg" in d:
        decs.append(f"color: {_flutter_color(d['bg'])}")
    if "radius" in d:
        decs.append(f"borderRadius: BorderRadius.circular({d['radius']})")
    if "border" in d:
        bval = d["border"]
        if isinstance(bval, (int, float)):
            decs.append(f"border: Border.all(width: {bval})")
        elif isinstance(bval, str) and "," in bval:
            w, col = bval.split(",", 1)
            decs.append(
                f"border: Border.all(color: {_flutter_color(col.strip())}, width: {w.strip()})")
    if not decs:
        return ""
    return f"BoxDecoration({', '.join(decs)})"


def style_to_flutter_main_align(d: dict) -> str:
    """MainAxisAlignment from align prop."""
    a = d.get("align", "center")
    mapping = {"center": "center", "start": "start", "end": "end",
               "spaceBetween": "spaceBetween", "spaceEvenly": "spaceEvenly",
               "spaceAround": "spaceAround"}
    return f"MainAxisAlignment.{mapping.get(a, 'center')}"


# ---- Slint emitter (stub — proves the same dict targets Rust/C++ GUI later) ----

SLINT_TYPE_MAP = {
    "fontSize": "font-size", "bold": "font-weight", "color": "color",
    "padding": "padding", "bg": "background", "radius": "border-radius",
    "width": "width", "height": "height", "border": "border-width",
}


def style_to_slint(d: dict, indent: int = 2) -> str:
    """Emit Slint property assignments from the same style dict.

    Slint is a declarative GUI DSL for Rust/C++ with CSS-like properties.
    This stub shows the SAME dict that emits Flutter Dart above can emit
    Slint properties — proving multi-target UI from one style syntax.
    """
    pad = " " * indent
    lines = []
    for key, slint_key in SLINT_TYPE_MAP.items():
        if key not in d:
            continue
        v = d[key]
        if key == "bold":
            v = "700" if v else "400"
        if key == "border" and isinstance(v, str) and "," in v:
            w, col = v.split(",", 1)
            lines.append(f"{pad}border-width: {w.strip()};")
            lines.append(f"{pad}border-color: {col.strip()};")
            continue
        if key in ("color", "bg") and isinstance(v, str):
            if not v.startswith("#"):
                v = "#000000"  # fallback
        lines.append(f"{pad}{slint_key}: {v};")
    return "\n".join(lines)


def style_to_rust_egui(d: dict) -> str:
    """Emit egui (Rust immediate-mode GUI) style calls from the same dict.

    Another target proving the dict is portable. egui is a popular Rust GUI lib.
    """
    parts = []
    if "fontSize" in d:
        parts.append(f".font_size({d['fontSize']} as f32)")
    if d.get("bold"):
        parts.append(".strong()")
    if "color" in d and isinstance(d["color"], str) and d["color"].startswith("#"):
        hexv = d["color"][1:]
        parts.append(f".color(Color32::from_rgb(0x{hexv[0:2]}, 0x{hexv[2:4]}, 0x{hexv[4:6]}))")
    return "".join(parts) if parts else ""
