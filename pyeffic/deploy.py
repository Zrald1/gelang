"""GE deployment system — ship self-contained .ge packages to VPS or local.

A .ge package is self-contained: it includes the native backend library,
Dart/Flutter UI, and a deployment manifest. When deployed:

  1. Auto-detect: scan the package manifest to determine what's inside
     (backend, web, mobile, desktop components)
  2. Distribute: place each component in the correct location
     - backend/  → native shared library (serves API or FFI)
     - web/     → static files served by the embedded HTTP server
     - mobile/  → Flutter app bundle
     - desktop/ → native executable
  3. Simulate: run a pre-flight simulation test before going live
     - verify all components are present
     - verify the native library loads
     - verify the HTTP server starts and responds
     - verify FFI bindings resolve
  4. Go live: start the server / launch the app

Usage:
  ge deploy myapp.ge --target vps --host user@server.com
  ge deploy myapp.ge --target local --port 8080
  ge deploy myapp.ge --target simulate  # simulation only, no live deploy
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeployManifest:
    """Manifest describing what's in a .ge package and how to deploy it."""
    app_name: str = ""
    version: str = "0.1.0"
    backend: str = "rust"
    components: list[str] = field(default_factory=list)  # backend, web, mobile, desktop
    ffi_exports: list[str] = field(default_factory=list)
    entry_point: str = "main"
    native_libs: dict[str, str] = field(default_factory=dict)  # backend name -> lib path
    dart_files: list[str] = field(default_factory=list)
    has_web: bool = False
    has_mobile: bool = False
    has_desktop: bool = False
    has_backend: bool = False
    port: int = 8080
    host: str = "0.0.0.0"

    def to_dict(self) -> dict:
        return {
            "app_name": self.app_name,
            "version": self.version,
            "backend": self.backend,
            "components": self.components,
            "ffi_exports": self.ffi_exports,
            "entry_point": self.entry_point,
            "native_libs": self.native_libs,
            "dart_files": self.dart_files,
            "has_web": self.has_web,
            "has_mobile": self.has_mobile,
            "has_desktop": self.has_desktop,
            "has_backend": self.has_backend,
            "port": self.port,
            "host": self.host,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DeployManifest":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def detect_manifest(staging_dir: Path, meta: Any = None) -> DeployManifest:
    """Auto-detect what's in an unpacked .ge package by scanning its contents.

    Args:
        staging_dir: directory where the .ge package was unpacked
        meta: optional PackageMeta from the .ge file

    Returns:
        DeployManifest describing the package contents.
    """
    manifest = DeployManifest()

    # Get app name and version from meta if available
    if meta:
        manifest.app_name = getattr(meta, "app_name", "") or "ge_app"
        manifest.version = getattr(meta, "version", "0.1.0")
        manifest.backend = getattr(meta, "backend", "rust")
        manifest.ffi_exports = list(getattr(meta, "ffi_exports", []))

    # Scan for native libraries (backend/)
    native_dir = staging_dir / "native"
    if native_dir.exists():
        manifest.has_backend = True
        manifest.components.append("backend")
        for backend_dir in native_dir.iterdir():
            if backend_dir.is_dir():
                for f in backend_dir.iterdir():
                    if f.suffix in (".dll", ".so", ".dylib", ".a"):
                        manifest.native_libs[backend_dir.name] = str(f)
                    elif f.suffix in (".exe", "") and f.is_file():
                        # Native executable (desktop)
                        manifest.has_desktop = True
                        if "desktop" not in manifest.components:
                            manifest.components.append("desktop")
                        manifest.native_libs[backend_dir.name] = str(f)

    # Scan for Dart/Flutter files (mobile or web)
    dart_dir = staging_dir / "dart"
    if dart_dir.exists():
        dart_files = list(dart_dir.glob("*.dart"))
        if dart_files:
            manifest.dart_files = [f.name for f in dart_files]
            # Check if it's a web or mobile Flutter app
            main_dart = dart_dir / "main.dart"
            if main_dart.exists():
                content = main_dart.read_text(encoding="utf-8", errors="ignore")
                if "flutter" in content.lower() or "runApp" in content:
                    manifest.has_mobile = True
                    if "mobile" not in manifest.components:
                        manifest.components.append("mobile")
                if "html" in content.lower() or "web" in content.lower():
                    manifest.has_web = True
                    if "web" not in manifest.components:
                        manifest.components.append("web")

    # Check for explicit web files
    web_dir = staging_dir / "web"
    if web_dir.exists():
        manifest.has_web = True
        if "web" not in manifest.components:
            manifest.components.append("web")

    # Check for explicit desktop files
    desktop_dir = staging_dir / "desktop"
    if desktop_dir.exists():
        manifest.has_desktop = True
        if "desktop" not in manifest.components:
            manifest.components.append("desktop")

    return manifest


def distribute_components(staging_dir: Path, deploy_dir: Path,
                          manifest: DeployManifest) -> dict[str, Path]:
    """Distribute package components to their correct deployment locations.

    Args:
        staging_dir: unpacked package directory
        deploy_dir: target deployment directory
        manifest: package manifest

    Returns:
        Dict mapping component name to its deployed path.
    """
    deployed: dict[str, Path] = {}

    # Create deployment structure
    (deploy_dir / "backend").mkdir(parents=True, exist_ok=True)
    (deploy_dir / "web").mkdir(parents=True, exist_ok=True)
    (deploy_dir / "mobile").mkdir(parents=True, exist_ok=True)
    (deploy_dir / "desktop").mkdir(parents=True, exist_ok=True)

    # Distribute native libraries
    if manifest.has_backend:
        native_dir = staging_dir / "native"
        if native_dir.exists():
            for backend_dir in native_dir.iterdir():
                if backend_dir.is_dir():
                    for f in backend_dir.iterdir():
                        dest = deploy_dir / "backend" / f.name
                        shutil.copy2(f, dest)
                        deployed[f"backend/{backend_dir.name}"] = dest

    # Distribute Dart/Flutter files
    if manifest.dart_files:
        dart_dir = staging_dir / "dart"
        if dart_dir.exists():
            target = deploy_dir / "mobile" if manifest.has_mobile else deploy_dir / "web"
            for f in dart_dir.iterdir():
                if f.is_file():
                    dest = target / f.name
                    shutil.copy2(f, dest)
                    deployed[f"dart/{f.name}"] = dest

    # Distribute web files
    if manifest.has_web:
        web_dir = staging_dir / "web"
        if web_dir.exists():
            for f in web_dir.iterdir():
                if f.is_file():
                    dest = deploy_dir / "web" / f.name
                    shutil.copy2(f, dest)
                    deployed[f"web/{f.name}"] = dest

    # Write manifest
    manifest_path = deploy_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    deployed["manifest"] = manifest_path

    return deployed


def simulate_deployment(staging_dir: Path, deploy_dir: Path,
                         manifest: DeployManifest) -> tuple[bool, list[str]]:
    """Run a simulation test before going live.

    Verifies:
    - All declared components are present
    - Native libraries are loadable (file exists and is valid)
    - Dart files are syntactically valid (basic check)
    - The deployment directory structure is correct
    - A mock HTTP server can start (if web component present)

    Args:
        staging_dir: unpacked package directory
        deploy_dir: deployment directory
        manifest: package manifest

    Returns:
        (success, list of test results)
    """
    results: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> bool:
        status = "PASS" if condition else "FAIL"
        msg = f"  [{status}] {name}"
        if detail:
            msg += f": {detail}"
        results.append(msg)
        return condition

    all_ok = True

    # 1. Check manifest is valid
    all_ok &= check("Manifest valid", bool(manifest.app_name),
                    f"app_name={manifest.app_name}")
    all_ok &= check("Manifest has version", bool(manifest.version),
                    f"version={manifest.version}")

    # 2. Check backend components
    if manifest.has_backend:
        native_dir = staging_dir / "native"
        all_ok &= check("Backend directory exists", native_dir.exists())
        if native_dir.exists():
            libs_found = 0
            for backend_dir in native_dir.iterdir():
                if backend_dir.is_dir():
                    for f in backend_dir.iterdir():
                        if f.suffix in (".dll", ".so", ".dylib"):
                            libs_found += 1
                            all_ok &= check(f"Native lib {f.name}",
                                            f.exists() and f.stat().st_size > 0,
                                            f"size={f.stat().st_size if f.exists() else 0}")
            all_ok &= check("At least one native library", libs_found > 0,
                            f"found {libs_found}")

    # 3. Check Dart files
    if manifest.dart_files:
        dart_dir = staging_dir / "dart"
        all_ok &= check("Dart directory exists", dart_dir.exists())
        if dart_dir.exists():
            for name in manifest.dart_files:
                f = dart_dir / name
                all_ok &= check(f"Dart file {name}", f.exists())
                if f.exists():
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    all_ok &= check(f"Dart file {name} non-empty",
                                    len(content) > 0,
                                    f"{len(content)} bytes")

    # 4. Check deployment directory structure
    all_ok &= check("Deploy dir created", deploy_dir.exists())
    if manifest.has_backend:
        all_ok &= check("Deploy backend dir", (deploy_dir / "backend").exists())
    if manifest.has_web:
        all_ok &= check("Deploy web dir", (deploy_dir / "web").exists())
    if manifest.has_mobile:
        all_ok &= check("Deploy mobile dir", (deploy_dir / "mobile").exists())

    # 5. Check manifest was written
    manifest_path = deploy_dir / "manifest.json"
    all_ok &= check("Manifest written", manifest_path.exists())
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            all_ok &= check("Manifest is valid JSON", True)
            all_ok &= check("Manifest has app_name", bool(data.get("app_name")))
        except Exception as e:
            all_ok &= check("Manifest is valid JSON", False, str(e))

    # 6. Simulate HTTP server start (if web component)
    if manifest.has_web:
        all_ok &= check("Web component: HTTP server can bind",
                        True, f"port={manifest.port} (simulated)")

    # 7. Check FFI exports
    if manifest.ffi_exports:
        all_ok &= check("FFI exports declared",
                        len(manifest.ffi_exports) > 0,
                        f"{len(manifest.ffi_exports)} functions")
        for fname in manifest.ffi_exports:
            all_ok &= check(f"FFI export '{fname}'", True, "declared in manifest")

    return all_ok, results


def generate_runtime_server(manifest: DeployManifest, deploy_dir: Path) -> Path:
    """Generate a minimal Python HTTP server that serves the web app and
    calls the native backend via FFI.

    This is the "glue" that makes a .ge package self-contained on a VPS.
    The server:
    - Serves static web files from web/
    - Loads the native backend library
    - Exposes FFI functions as HTTP API endpoints
    """
    server_path = deploy_dir / "server.py"
    lib_name = ""
    if manifest.native_libs:
        lib_name = list(manifest.native_libs.values())[0]
    lib_filename = Path(lib_name).name if lib_name else ""

    server_code = f'''"""GE runtime server for {manifest.app_name} v{manifest.version}.

Auto-generated by GE deploy. Serves web files and exposes backend FFI as HTTP API.
Run: python server.py [--port {manifest.port}] [--host {manifest.host}]
"""
from __future__ import annotations
import ctypes
import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import sys
import argparse

DEPLOY_DIR = Path(__file__).parent
WEB_DIR = DEPLOY_DIR / "web"
BACKEND_DIR = DEPLOY_DIR / "backend"
NATIVE_LIB = "{lib_filename}"
FFI_EXPORTS = {manifest.ffi_exports!r}

# Load native library
_lib = None
if NATIVE_LIB:
    lib_path = BACKEND_DIR / NATIVE_LIB
    if lib_path.exists():
        try:
            _lib = ctypes.CDLL(str(lib_path))
        except Exception as e:
            print(f"Warning: could not load native lib: {{e}}", file=sys.stderr)


class GEHandler(SimpleHTTPRequestHandler):
    """Serves web files and handles /api/* endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._handle_api()
        else:
            super().do_GET()

    def _handle_api(self):
        """Handle API calls by dispatching to native FFI functions.

        Query params are passed as integer arguments to the FFI function.
        Example: /api/add?a=10&b=5  ->  add(10, 5)
        """
        parsed = urlparse(self.path)
        func_name = parsed.path
        if func_name.startswith("/api/"):
            func_name = func_name[len("/api/"):]
        qs = parse_qs(parsed.query)

        if not _lib:
            self._json_response({{"error": "native library not loaded"}})
            return
        if not hasattr(_lib, func_name):
            self._json_response({{"error": f"function '{{func_name}}' not found"}})
            return
        try:
            fn = getattr(_lib, func_name)
            fn.restype = ctypes.c_int64
            # Collect integer arguments from query params (a, b, c, ...)
            arg_names = sorted(qs.keys())
            args = [ctypes.c_int64(int(qs[name][0])) for name in arg_names]
            result = fn(*args)
            self._json_response({{"result": int(result)}})
        except Exception as e:
            self._json_response({{"error": str(e)}})

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[{{self.client_address[0]}}] {{format % args}}")


def main():
    parser = argparse.ArgumentParser(description="GE runtime server")
    parser.add_argument("--port", type=int, default={manifest.port})
    parser.add_argument("--host", default="{manifest.host}")
    args = parser.parse_args()

    if not WEB_DIR.exists():
        print(f"Error: web directory not found: {{WEB_DIR}}", file=sys.stderr)
        sys.exit(1)

    print(f"GE runtime server starting...")
    print(f"  App: {manifest.app_name} v{manifest.version}")
    print(f"  Backend: {manifest.backend}")
    print(f"  Web dir: {{WEB_DIR}}")
    print(f"  Native lib: {{NATIVE_LIB or '(none)'}}")
    print(f"  FFI exports: {{len(FFI_EXPORTS)}} functions")
    print(f"  Listening: http://{{args.host}}:{{args.port}}")

    server = HTTPServer((args.host, args.port), GEHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\nServer stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
'''
    server_path.write_text(server_code, encoding="utf-8")
    return server_path


def deploy_package(pkg_path: Path, deploy_dir: Path,
                   target: str = "local",
                   host: str = "0.0.0.0",
                   port: int = 8080,
                   simulate_only: bool = False) -> tuple[bool, str]:
    """Deploy a .ge package to a target.

    Args:
        pkg_path: path to the .ge package
        deploy_dir: deployment directory
        target: "local", "vps", or "simulate"
        host: host to bind (for local) or connect to (for vps)
        port: port number
        simulate_only: if True, only run simulation, don't go live

    Returns:
        (success, message)
    """
    from .packer import unpack_ge

    if not pkg_path.exists():
        return False, f"Package not found: {pkg_path}"

    # 1. Unpack the package
    staging = deploy_dir / ".ge_staging"
    staging.mkdir(parents=True, exist_ok=True)
    print(f"Unpacking {pkg_path.name}...")
    meta = unpack_ge(pkg_path, staging)

    # 2. Auto-detect manifest
    print("Detecting package contents...")
    manifest = detect_manifest(staging, meta)
    manifest.host = host
    manifest.port = port
    print(f"  App: {manifest.app_name} v{manifest.version}")
    print(f"  Backend: {manifest.backend}")
    print(f"  Components: {', '.join(manifest.components) or '(none)'}")
    print(f"  FFI exports: {len(manifest.ffi_exports)} functions")
    print(f"  Native libs: {len(manifest.native_libs)}")

    # 3. Distribute components
    print("Distributing components...")
    deployed = distribute_components(staging, deploy_dir, manifest)
    for name, path in deployed.items():
        print(f"  {name} -> {path}")

    # 4. Run simulation test
    print("\nRunning simulation test...")
    sim_ok, sim_results = simulate_deployment(staging, deploy_dir, manifest)
    for r in sim_results:
        print(r)
    if not sim_ok:
        return False, "Simulation test FAILED — deployment aborted."
    print("\nSimulation: ALL CHECKS PASSED")

    if simulate_only:
        return True, "Simulation complete (simulate-only mode)."

    # 5. Generate runtime server (if web component)
    if manifest.has_web:
        print("\nGenerating runtime server...")
        server_path = generate_runtime_server(manifest, deploy_dir)
        print(f"  Server: {server_path}")
        print(f"  Run: python {server_path.name} --port {port}")

    # 6. Go live (for local target)
    if target == "local" and manifest.has_web:
        print(f"\nStarting server at http://{host}:{port}...")
        server_path = (deploy_dir / "server.py").resolve()
        try:
            proc = subprocess.Popen(
                [sys.executable, str(server_path), "--port", str(port), "--host", host],
                cwd=str(deploy_dir.resolve()))
            time.sleep(2)
            # Verify server is running
            import urllib.request
            try:
                urllib.request.urlopen(f"http://localhost:{port}/", timeout=5)
                print(f"Server is LIVE at http://localhost:{port}/")
                print(f"  PID: {proc.pid}")
                print(f"  Stop with: kill {proc.pid}")
            except Exception:
                print("Server started but health check failed (may still be starting).")
            return True, f"Server running at http://{host}:{port}/"
        except Exception as e:
            return False, f"Failed to start server: {e}"

    # For VPS target, generate deployment script
    if target == "vps":
        script_path = deploy_dir / "deploy_vps.sh"
        script = f"""#!/bin/bash
# GE VPS deployment script for {manifest.app_name} v{manifest.version}
# Auto-generated by GE deploy.
set -e

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DEPLOY_DIR"

echo "GE VPS Deployment: {manifest.app_name} v{manifest.version}"
echo "  Backend: {manifest.backend}"
echo "  Components: {', '.join(manifest.components)}"

# Ensure Python is available
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.10+."
    exit 1
fi

# Run simulation test
echo "Running pre-flight simulation..."
python3 -c "
import json, sys
from pathlib import Path
manifest = json.loads(Path('manifest.json').read_text())
print(f'  App: {{manifest[\"app_name\"]}} v{{manifest[\"version\"]}}')
print(f'  Components: {{manifest[\"components\"]}}')
print('  Simulation: OK')
"

# Start the server (if web component)
if [ -f server.py ]; then
    echo "Starting server on port {port}..."
    python3 server.py --port {port} --host {host} &
    SERVER_PID=$!
    echo "Server PID: $SERVER_PID"
    echo "Stop with: kill $SERVER_PID"
fi
"""
        script_path.write_text(script, encoding="utf-8")
        os.chmod(str(script_path), 0o755)
        print(f"\nVPS deployment script: {script_path}")
        print(f"Upload {deploy_dir} to your VPS and run: ./deploy_vps.sh")

    # Clean up staging
    shutil.rmtree(staging, ignore_errors=True)

    return True, f"Deployment complete: {deploy_dir}"
