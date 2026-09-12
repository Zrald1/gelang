"""React + TypeScript UI generator.

Turns a `.ge.ui` Screen tree into a modern React 19 + TypeScript + Vite
project. One component per file, so every generated file is small,
readable, and editable by hand — the same contract the native templates use.

    .ge.ui  --ui_dsl.parse_ui_dsl-->  Screen tree
            --reactgen-->             React/TS project (dict of path -> content)

Generated layout
----------------
    index.html
    package.json
    vite.config.ts
    tsconfig.json
    tsconfig.node.json
    src/main.tsx
    src/App.tsx
    src/styles.css
    src/api/client.ts
    src/api/types.ts
    src/components/GeText.tsx
    src/components/GeButton.tsx
    src/components/GeColumn.tsx
    src/components/GeRow.tsx
    src/components/GeContainer.tsx
    src/components/GeSizedBox.tsx
    src/components/GeDivider.tsx
    src/components/GeTextField.tsx

Design notes (from the React/Rust template research):
  - React 19 + TypeScript + Vite is the current default stack.
  - The Rust backend serves the built SPA from one binary.
  - Components are dumb/presentational; data flows from `useGeState`.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .analyzer import FuncUnit
from .ui_dsl import Screen, WidgetNode, collect_state_from_screen

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS_TYPE = {
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "str": "string",
    "list": "number[]",
}

_TS_DEFAULT = {
    "number": "0",
    "boolean": "false",
    "string": '""',
    "number[]": "[]",
}

_NAMED_STYLES = {
    "headline": {"fontSize": "1.75rem", "fontWeight": "600"},
    "title": {"fontSize": "1.25rem", "fontWeight": "600"},
    "subtitle": {"fontSize": "1rem", "color": "var(--ge-text-dim)"},
    "body": {"fontSize": "0.95rem"},
    "value": {"fontSize": "2rem", "fontWeight": "700", "color": "var(--ge-accent)"},
    "error": {"color": "var(--ge-danger)"},
}

_COLOR_VARS = {
    "red": "var(--ge-danger)",
    "green": "var(--ge-success)",
    "blue": "var(--ge-accent)",
    "amber": "var(--ge-warning)",
    "grey": "var(--ge-text-dim)",
    "gray": "var(--ge-text-dim)",
}

# Material-style shades used in the UI DSL (e.g. "grey700", "blue500").
_SHADE_COLORS = {
    "grey": {50: "#f8fafc", 100: "#f1f5f9", 200: "#e2e8f0", 300: "#cbd5e1",
             400: "#94a3b8", 500: "#64748b", 600: "#475569", 700: "#334155",
             800: "#1e293b", 900: "#0f172a"},
    "gray": {50: "#f8fafc", 100: "#f1f5f9", 200: "#e2e8f0", 300: "#cbd5e1",
             400: "#94a3b8", 500: "#64748b", 600: "#475569", 700: "#334155",
             800: "#1e293b", 900: "#0f172a"},
    "blue": {300: "#93c5fd", 400: "#60a5fa", 500: "#3b82f6", 600: "#2563eb",
             700: "#1d4ed8"},
    "green": {300: "#86efac", 400: "#4ade80", 500: "#22c55e", 600: "#16a34a"},
    "red": {300: "#fca5a5", 400: "#f87171", 500: "#ef4444", 600: "#dc2626"},
    "amber": {300: "#fcd34d", 400: "#fbbf24", 500: "#f59e0b"},
    "white": {0: "#ffffff"},
    "black": {0: "#000000"},
}


def _map_dsl_color(raw: str) -> str:
    """Map a UI DSL color name onto a CSS value.

    Handles `grey700`, `blue500`, plain names, and already-CSS values.
    """
    c = str(raw).strip()
    if not c:
        return "inherit"
    low = c.lower()
    if low in _COLOR_VARS:
        return _COLOR_VARS[low]
    m = re.match(r"^([a-z]+)(\d{2,3})$", low)
    if m and m.group(1) in _SHADE_COLORS:
        shade = int(m.group(2))
        table = _SHADE_COLORS[m.group(1)]
        if shade in table:
            return table[shade]
        nearest = min(table, key=lambda k: abs(k - shade))
        return table[nearest]
    if low in _SHADE_COLORS and 0 in _SHADE_COLORS[low]:
        return _SHADE_COLORS[low][0]
    # hex, rgb(), or a CSS variable — pass through
    return c


def _js_str(value: Any) -> str:
    """Render a Python value as a TypeScript literal."""
    if value is None:
        return "undefined"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def _camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _style_to_react(style_dict: dict[str, Any], style_name: str | None = None) -> str:
    """Build a React style object literal from DSL style info."""
    merged: dict[str, Any] = {}
    if style_name and style_name in _NAMED_STYLES:
        merged.update(_NAMED_STYLES[style_name])
    for key, val in (style_dict or {}).items():
        if key == "fontSize":
            merged["fontSize"] = f"{val}px" if str(val).isdigit() else str(val)
        elif key == "bold":
            if val:
                merged["fontWeight"] = "700"
        elif key == "italic":
            if val:
                merged["fontStyle"] = "italic"
        elif key == "color":
            merged["color"] = _map_dsl_color(val)
        elif key == "padding":
            merged["padding"] = f"{val}px"
        elif key == "margin":
            merged["margin"] = f"{val}px"
        elif key == "width":
            merged["width"] = f"{val}px"
        elif key == "height":
            merged["height"] = f"{val}px"
        elif key == "align":
            merged["alignItems"] = {
                "center": "center", "start": "flex-start",
                "end": "flex-end", "spaceBetween": "space-between",
            }.get(str(val), "center")
        else:
            merged[_camel(key)] = val
    if not merged:
        return "undefined"
    body = ", ".join(f"{k}: {_js_str(v)}" for k, v in merged.items())
    return "{ " + body + " }"


def _infer_state_types(node: WidgetNode | None, types: dict[str, str]) -> None:
    """Refine state variable types from how widgets bind them.

    Types here are GE type names (str/int/bool/...) because the caller maps
    them to TypeScript through _TS_TYPE.
    """
    if node is None:
        return
    if node.kind in ("TextField", "Input"):
        bind = node.state or node.props.get("state")
        if bind:
            types[bind] = "str"
    for child in node.children:
        _infer_state_types(child, types)
    child = node.props.get("child")
    if isinstance(child, WidgetNode):
        _infer_state_types(child, types)


def _collect_widget_kinds(node: WidgetNode | None, out: set[str]) -> None:
    if node is None:
        return
    out.add(node.kind)
    for child in node.children:
        _collect_widget_kinds(child, out)
    if node.props.get("child") is not None and isinstance(node.props["child"], WidgetNode):
        _collect_widget_kinds(node.props["child"], out)


# ---------------------------------------------------------------------------
# Component files (one widget per file)
# ---------------------------------------------------------------------------

def _component_text() -> str:
    return '''import type { CSSProperties } from "react";

export interface GeTextProps {
  text?: string;
  value?: string | number;
  style?: CSSProperties;
}

/** Leaf: a single line of text (or a bound state value). */
export function GeText({ text, value, style }: GeTextProps) {
  const content = value !== undefined ? value : text ?? "";
  return <span style={style}>{content}</span>;
}
'''


def _component_button() -> str:
    return '''import type { CSSProperties } from "react";

export interface GeButtonProps {
  label: string;
  onClick?: () => void;
  style?: CSSProperties;
  disabled?: boolean;
}

/** Leaf: a clickable button. */
export function GeButton({ label, onClick, style, disabled }: GeButtonProps) {
  return (
    <button className="ge-button" onClick={onClick} style={style} disabled={disabled}>
      {label}
    </button>
  );
}
'''


def _component_column() -> str:
    return '''import type { CSSProperties, ReactNode } from "react";

export interface GeColumnProps {
  children?: ReactNode;
  style?: CSSProperties;
}

/** Container: vertical flex stack. */
export function GeColumn({ children, style }: GeColumnProps) {
  return (
    <div className="ge-column" style={{ display: "flex", flexDirection: "column", ...style }}>
      {children}
    </div>
  );
}
'''


def _component_row() -> str:
    return '''import type { CSSProperties, ReactNode } from "react";

export interface GeRowProps {
  children?: ReactNode;
  style?: CSSProperties;
}

/** Container: horizontal flex row. */
export function GeRow({ children, style }: GeRowProps) {
  return (
    <div className="ge-row" style={{ display: "flex", flexDirection: "row", ...style }}>
      {children}
    </div>
  );
}
'''


def _component_container() -> str:
    return '''import type { CSSProperties, ReactNode } from "react";

export interface GeContainerProps {
  children?: ReactNode;
  style?: CSSProperties;
}

/** Container: padded, optionally bordered surface. */
export function GeContainer({ children, style }: GeContainerProps) {
  return (
    <div className="ge-container" style={style}>
      {children}
    </div>
  );
}
'''


def _component_sized_box() -> str:
    return '''export interface GeSizedBoxProps {
  width?: number;
  height?: number;
}

/** Container: fixed spacer. */
export function GeSizedBox({ width, height }: GeSizedBoxProps) {
  return <div style={{ width, height, flexShrink: 0 }} aria-hidden="true" />;
}
'''


def _component_divider() -> str:
    return '''/** Leaf: horizontal rule. */
export function GeDivider() {
  return <hr className="ge-divider" />;
}
'''


def _component_text_field() -> str:
    return '''import type { CSSProperties } from "react";

export interface GeTextFieldProps {
  label?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  style?: CSSProperties;
}

/** Leaf: single-line text input bound to state. */
export function GeTextField({ label, value, onChange, placeholder, style }: GeTextFieldProps) {
  return (
    <label className="ge-field" style={style}>
      {label ? <span className="ge-field-label">{label}</span> : null}
      <input
        className="ge-input"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
'''


_COMPONENT_FILES = {
    "GeText.tsx": _component_text,
    "GeButton.tsx": _component_button,
    "GeColumn.tsx": _component_column,
    "GeRow.tsx": _component_row,
    "GeContainer.tsx": _component_container,
    "GeSizedBox.tsx": _component_sized_box,
    "GeDivider.tsx": _component_divider,
    "GeTextField.tsx": _component_text_field,
}


# ---------------------------------------------------------------------------
# Widget tree -> JSX
# ---------------------------------------------------------------------------

def widget_to_jsx(node: WidgetNode | dict | None, indent: int = 2,
                  state_names: set[str] | None = None) -> str:
    """Render a widget tree as JSX."""
    pad = "  " * indent
    if node is None:
        return f"{pad}<></>"
    if not isinstance(node, WidgetNode):
        node = WidgetNode(kind="Text", text=str(node))
    state_names = state_names or set()
    k = node.kind

    if k == "Text":
        sd = node.style_dict or {}
        style = _style_to_react(sd, node.props.get("style"))
        if node.state:
            var = _camel(node.state)
            return f'{pad}<GeText value={{String({var})}} style={{{style}}} />'
        text = node.text if node.text is not None else node.props.get("text", "")
        return f'{pad}<GeText text={_js_str(text)} style={{{style}}} />'

    if k in ("Button", "ElevatedButton", "TextButton"):
        label = node.label or node.props.get("label", "")
        action = node.action
        handler = "undefined"
        if isinstance(action, dict) and action.get("call"):
            handler = f"() => run({_js_str(action['call'])})"
        elif isinstance(action, list) and action and action[0].get("call"):
            handler = f"() => run({_js_str(action[0]['call'])})"
        return f'{pad}<GeButton label={_js_str(label)} onClick={{{handler}}} />'

    if k in ("Column", "Row"):
        comp = "GeColumn" if k == "Column" else "GeRow"
        sd = node.style_dict or {}
        style = _style_to_react(sd)
        inner = "\n".join(widget_to_jsx(c, indent + 1, state_names) for c in node.children)
        if not inner:
            return f"{pad}<{comp} style={{{style}}} />"
        return f"{pad}<{comp} style={{{style}}}>\n{inner}\n{pad}</{comp}>"

    if k == "Container":
        sd = node.style_dict or {}
        style = _style_to_react(sd)
        child = node.props.get("child")
        if child is None and node.children:
            child = node.children[0]
        if child is None:
            return f"{pad}<GeContainer style={{{style}}} />"
        inner = widget_to_jsx(child, indent + 1, state_names)
        return f"{pad}<GeContainer style={{{style}}}>\n{inner}\n{pad}</GeContainer>"

    if k == "Expanded":
        child = node.props.get("child")
        if child is None and node.children:
            child = node.children[0]
        inner = widget_to_jsx(child, indent, state_names)
        return f'{pad}<div style={{{{ flex: {node.props.get("flex", 1)} }}}}>\n{inner}\n{pad}</div>'

    if k == "SizedBox":
        w = node.props.get("width", node.style_dict.get("width"))
        h = node.props.get("height", node.style_dict.get("height"))
        parts = []
        if w:
            parts.append(f"width={{{w}}}")
        if h:
            parts.append(f"height={{{h}}}")
        return f"{pad}<GeSizedBox {' '.join(parts)} />"

    if k == "Divider":
        return f"{pad}<GeDivider />"

    if k in ("TextField", "Input"):
        label = node.props.get("label", "")
        bind = node.state or node.props.get("state")
        var = _camel(bind) if bind else "input"
        return (f'{pad}<GeTextField label={_js_str(label)} value={{String({var})}} '
                f'onChange={{(v) => set{var[0].upper() + var[1:]}(v)}} />')

    if k == "Icon":
        return f'{pad}<GeText text={_js_str(node.props.get("name", ""))} />'

    return f'{pad}<GeText text={_js_str("unsupported: " + k)} />'


# ---------------------------------------------------------------------------
# Project files
# ---------------------------------------------------------------------------

def _package_json(app_name: str) -> str:
    pkg = {
        "name": app_name.lower().replace("_", "-"),
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "tsc -b && vite build",
            "preview": "vite preview",
            "typecheck": "tsc --noEmit",
        },
        "dependencies": {
            "react": "^19.0.0",
            "react-dom": "^19.0.0",
        },
        "devDependencies": {
            "@types/react": "^19.0.0",
            "@types/react-dom": "^19.0.0",
            "@vitejs/plugin-react": "^4.3.4",
            "typescript": "^5.7.2",
            "vite": "^6.0.7",
        },
    }
    return json.dumps(pkg, indent=2) + "\n"


def _vite_config() -> str:
    return '''import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to the GE Rust backend so the frontend and
// backend share an origin in development, exactly like production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
'''


def _tsconfig() -> str:
    cfg = {
        "compilerOptions": {
            "target": "ES2022",
            "lib": ["ES2022", "DOM", "DOM.Iterable"],
            "module": "ESNext",
            "moduleResolution": "bundler",
            "jsx": "react-jsx",
            "strict": True,
            "noUnusedLocals": True,
            "noUnusedParameters": True,
            "noFallthroughCasesInSwitch": True,
            "skipLibCheck": True,
            "isolatedModules": True,
            "noEmit": True,
        },
        "include": ["src"],
    }
    return json.dumps(cfg, indent=2) + "\n"


def _index_html(app_name: str) -> str:
    return f'''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{app_name}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
'''


def _main_tsx() -> str:
    return '''import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

const el = document.getElementById("root");
if (!el) {
  throw new Error("root element missing");
}

createRoot(el).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
'''


def _vite_env_dts() -> str:
    return '''/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
'''


def _api_types(ffi_units: list[FuncUnit]) -> str:
    lines = [
        "// Types shared with the GE Rust backend.",
        "",
        "export interface ApiResult {",
        "  ok: boolean;",
        "  value: number;",
        "  error?: string;",
        "}",
        "",
        "export interface FunctionSpec {",
        "  name: string;",
        "  params: number;",
        "}",
        "",
        "// Functions exported by the backend (from the @rust GE functions).",
        "export const BACKEND_FUNCTIONS: FunctionSpec[] = [",
    ]
    for u in ffi_units:
        lines.append(f'  {{ name: {json.dumps(u.name)}, params: {len(u.params)} }},')
    lines += ["];", ""]
    return "\n".join(lines)


def _api_client(app_name: str) -> str:
    return f'''// API client for the {app_name} Rust backend.
//
// Every call goes through `callFunction`, which POSTs to /api/call.
// The backend is a GE-compiled Rust binary, so the wire format is plain
// JSON with no framework on either side.

import type {{ ApiResult }} from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "";

export async function callFunction(
  name: string,
  args: number[],
): Promise<ApiResult> {{
  try {{
    const res = await fetch(`${{BASE}}/api/call`, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ name, args }}),
    }});
    if (!res.ok) {{
      return {{ ok: false, value: 0, error: `HTTP ${{res.status}}` }};
    }}
    return (await res.json()) as ApiResult;
  }} catch (err) {{
    return {{ ok: false, value: 0, error: String(err) }};
  }}
}}

export async function health(): Promise<boolean> {{
  try {{
    const res = await fetch(`${{BASE}}/api/health`);
    return res.ok;
  }} catch {{
    return false;
  }}
}}
'''


def _styles_css() -> str:
    return ''':root {
  --ge-bg: #0f172a;
  --ge-panel: #1e293b;
  --ge-card: #1e293b;
  --ge-border: #334155;
  --ge-accent: #60a5fa;
  --ge-text: #f1f5f9;
  --ge-text-dim: #94a3b8;
  --ge-success: #4ade80;
  --ge-warning: #fbbf24;
  --ge-danger: #f87171;
  --ge-radius: 12px;
  --ge-space: 16px;
  color-scheme: dark;
}

* { box-sizing: border-box; }

html, body, #root {
  margin: 0;
  height: 100%;
}

body {
  background: var(--ge-bg);
  color: var(--ge-text);
  font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

.ge-app {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.ge-header {
  padding: var(--ge-space) calc(var(--ge-space) * 1.5);
  border-bottom: 1px solid var(--ge-border);
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.ge-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--ge-accent);
}

.ge-subtitle {
  color: var(--ge-text-dim);
  font-size: 0.85rem;
}

.ge-main {
  flex: 1;
  padding: calc(var(--ge-space) * 1.5);
  display: flex;
  gap: calc(var(--ge-space) * 1.5);
  align-items: flex-start;
  flex-wrap: wrap;
}

.ge-column { gap: 12px; }

.ge-container {
  background: var(--ge-card);
  border: 1px solid var(--ge-border);
  border-radius: var(--ge-radius);
  padding: var(--ge-space);
  min-width: 260px;
}

.ge-button {
  background: var(--ge-accent);
  color: #0b1220;
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: filter 120ms ease, transform 120ms ease;
}

.ge-button:hover:not(:disabled) { filter: brightness(1.08); }
.ge-button:active:not(:disabled) { transform: translateY(1px); }
.ge-button:disabled { opacity: 0.5; cursor: not-allowed; }

.ge-divider {
  border: none;
  border-top: 1px solid var(--ge-border);
  width: 100%;
  margin: 4px 0;
}

.ge-field { display: flex; flex-direction: column; gap: 6px; }
.ge-field-label { color: var(--ge-text-dim); font-size: 0.8rem; }

.ge-input {
  background: #0b1220;
  border: 1px solid var(--ge-border);
  border-radius: 8px;
  padding: 9px 12px;
  color: var(--ge-text);
  font-size: 0.95rem;
  outline: none;
}

.ge-input:focus { border-color: var(--ge-accent); }

.ge-result {
  font-size: 2rem;
  font-weight: 700;
  color: var(--ge-success);
}

.ge-error { color: var(--ge-danger); font-size: 0.85rem; }

.ge-footer {
  padding: var(--ge-space);
  border-top: 1px solid var(--ge-border);
  color: var(--ge-text-dim);
  font-size: 0.8rem;
}
'''


def _app_tsx(screen: Screen, app_name: str, ffi_units: list[FuncUnit]) -> str:
    state = collect_state_from_screen(screen)
    _infer_state_types(screen.root, state)
    state_names = set(state.keys())

    state_lines: list[str] = []
    for name, ge_type in state.items():
        var = _camel(name)
        ts_type = _TS_TYPE.get(ge_type, "number")
        default = _TS_DEFAULT.get(ts_type, "0")
        setter = "set" + var[0].upper() + var[1:]
        state_lines.append(f"  const [{var}, {setter}] = useState<{ts_type}>({default});")

    # only import the components the tree actually uses, so `tsc` stays clean
    used: set[str] = set()
    _collect_widget_kinds(screen.root, used)
    kind_to_component = {
        "Text": "GeText", "Button": "GeButton", "ElevatedButton": "GeButton",
        "TextButton": "GeButton", "Column": "GeColumn", "Row": "GeRow",
        "Container": "GeContainer", "SizedBox": "GeSizedBox",
        "Divider": "GeDivider", "TextField": "GeTextField", "Input": "GeTextField",
        "Icon": "GeText", "Expanded": None,
    }
    # the generated App always renders a result card, so force those imports
    needed = {"GeText", "GeColumn", "GeContainer"}
    for kind in used:
        comp = kind_to_component.get(kind)
        if comp:
            needed.add(comp)

    imports = "\n".join(
        f'import {{ {c} }} from "./components/{c}";' for c in sorted(needed)
    )

    # callFunction is only referenced when there are backend functions to call
    if ffi_units:
        client_import = 'import { callFunction } from "./api/client";\n'
        run_body = (
            "      const res = await callFunction(name, args);\n"
            "      if (!res.ok) {\n"
            "        setApiError(res.error ?? \"call failed\");\n"
            "        return;\n"
            "      }\n"
            "      setApiError(\"\");\n"
            "      setApiResult(res.value);\n"
        )
        use_callback = "useCallback, "
    else:
        client_import = ""
        run_body = (
            "      // No @rust/@cpp backend functions were found for this UI.\n"
            "      // Add them under app/ and rebuild to enable real calls.\n"
            "      void name;\n"
            "      void args;\n"
        )
        use_callback = ""

    # Unused-locals suppression. Every state value and setter is referenced
    # once so the generated file typechecks under `noUnusedLocals` before you
    # have wired any handlers. Delete this block as you add real handlers.
    refs: list[str] = []
    for n in state:
        var = _camel(n)
        refs.append(var)
        refs.append("set" + var[0].upper() + var[1:])
    if not ffi_units:
        refs.extend(["setApiResult", "setApiError"])
    used_refs = ""
    if refs:
        used_refs = (
            "  // Wiring placeholders: keeps every state value/setter referenced so\n"
            "  // `tsc --noEmit` is clean before handlers exist. Delete as you wire up.\n"
            f"  const wiring = {{ {', '.join(refs)} }};\n"
            "  void wiring;\n"
        )

    body = widget_to_jsx(screen.root, 3, state_names)

    return f'''// {app_name} — generated from {screen.title or "ui/main.ge.ui"}.
//
// This file is generated once and then yours to edit: the GE build never
// overwrites src/ unless you pass --force.

import {{ {use_callback}useState }} from "react";
{client_import}{imports}

export function App() {{
{chr(10).join(state_lines) if state_lines else "  // no state declared in the UI DSL"}
  const [apiResult, setApiResult] = useState(0);
  const [apiError, setApiError] = useState("");
{used_refs}
  const run = async (name: string, args: number[] = []) => {{
{run_body}  }};
  void run;

  return (
    <div className="ge-app">
      <header className="ge-header">
        <span className="ge-title">{screen.title or app_name}</span>
        <span className="ge-subtitle">GE · React · Rust</span>
      </header>

      <main className="ge-main">
{body}
        <GeContainer>
          <GeColumn>
            <GeText text="Result" style={{{{ color: "var(--ge-text-dim)", fontSize: "0.8rem" }}}} />
            <span className="ge-result">{{apiResult}}</span>
            {{apiError ? <span className="ge-error">{{apiError}}</span> : null}}
          </GeColumn>
        </GeContainer>
      </main>

      <footer className="ge-footer">
        {app_name} · frontend generated by GE reactgen
      </footer>
    </div>
  );
}}
'''


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_react_app(screen: Screen, app_name: str,
                       ffi_units: list[FuncUnit] | None = None,
                       out_dir: str = "web/frontend") -> dict[str, str]:
    """Generate a React + TypeScript project from a parsed .ge.ui Screen.

    Returns a mapping of relative path -> file content. Callers decide where
    to write them (the scaffold writes them under out_dir).
    """
    ffi_units = ffi_units or []
    files: dict[str, str] = {}

    files["index.html"] = _index_html(app_name)
    files["package.json"] = _package_json(app_name)
    files["vite.config.ts"] = _vite_config()
    files["tsconfig.json"] = _tsconfig()
    files["src/main.tsx"] = _main_tsx()
    files["src/vite-env.d.ts"] = _vite_env_dts()
    files["src/App.tsx"] = _app_tsx(screen, app_name, ffi_units)
    files["src/styles.css"] = _styles_css()
    files["src/api/client.ts"] = _api_client(app_name)
    files["src/api/types.ts"] = _api_types(ffi_units)

    # only emit the components the UI actually uses, so the tree stays lean
    used: set[str] = set()
    _collect_widget_kinds(screen.root, used)
    mapping = {
        "Text": "GeText.tsx",
        "Button": "GeButton.tsx",
        "ElevatedButton": "GeButton.tsx",
        "TextButton": "GeButton.tsx",
        "Column": "GeColumn.tsx",
        "Row": "GeRow.tsx",
        "Container": "GeContainer.tsx",
        "SizedBox": "GeSizedBox.tsx",
        "Divider": "GeDivider.tsx",
        "TextField": "GeTextField.tsx",
        "Input": "GeTextField.tsx",
    }
    wanted = {mapping[k] for k in used if k in mapping}
    # App.tsx imports all of them, so always emit the full set
    wanted = set(_COMPONENT_FILES)
    for fname in sorted(wanted):
        files[f"src/components/{fname}"] = _COMPONENT_FILES[fname]()

    return files


def write_react_app(files: dict[str, str], root, force: bool = False) -> list[str]:
    """Write generated React files under `root`.

    Existing files are left untouched unless `force=True`, so hand edits are
    never clobbered by a rebuild.
    """
    from pathlib import Path

    root = Path(root)
    written: list[str] = []
    for rel, content in files.items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and not force:
            continue
        dst.write_text(content, encoding="utf-8")
        written.append(rel)
    return written
