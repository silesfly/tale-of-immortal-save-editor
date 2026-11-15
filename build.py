#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build script for Tale of Immortal Save Editor v1.0."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
OUT_HTML = DIST / "TaleOfImmortalSaveEditor-v1.0.html"
OUT_EXE = DIST / "TaleOfImmortalSaveEditor-v1.0.exe"

SCRIPT_ORDER = ("catalog-data.js", "cache-codec.js", "editor-core.js", "editor-ui.js")
BUNDLE_START = "<!-- BUNDLE_SCRIPTS_START -->"
BUNDLE_END = "<!-- BUNDLE_SCRIPTS_END -->"

EXTERNAL_URL_RE = re.compile(
    r'(?i)\b(?:https?|ftp|wss?)://|\b(?:src|href|action|poster|data|cite)\s*=\s*["\']?\s*//|\burl\(\s*["\']?\s*(?:https?|ftp|wss?)?//'
)
REQUIRED_SDK_FILES = (
    "Microsoft.Web.WebView2.Core.dll",
    "Microsoft.Web.WebView2.WinForms.dll",
    "WebView2Loader.dll",
    "LICENSE.txt",
)


def has_external_url_ref(html_text: str) -> bool:
    return isinstance(html_text, str) and EXTERNAL_URL_RE.search(html_text) is not None


def build_html() -> str:
    page_path = SRC / "editor-page.html"
    if not page_path.is_file():
        raise SystemExit(f"missing HTML template: {page_path}")
    page = page_path.read_text(encoding="utf-8")
    start = page.find(BUNDLE_START)
    end = page.find(BUNDLE_END, start + len(BUNDLE_START)) if start >= 0 else -1
    if start < 0 or end < 0:
        raise SystemExit("missing bundle markers in src/editor-page.html")

    blocks = []
    for name in SCRIPT_ORDER:
        js_path = SRC / name
        if not js_path.is_file():
            raise SystemExit(f"missing script: {js_path}")
        code = js_path.read_text(encoding="utf-8")
        code = re.sub(r"(?i)</(script)", lambda m: "<\\/" + m.group(1), code)
        blocks.append(f"<script>\n{code}\n</script>")

    html = page[:start] + "\n".join(blocks) + page[end + len(BUNDLE_END) :]
    if has_external_url_ref(html):
        raise SystemExit("bundled HTML still contains an external URL reference")

    DIST.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8", newline="\n")
    print(f"wrote {OUT_HTML} ({OUT_HTML.stat().st_size} bytes)")
    return html


def build_exe(webview2_dir: Path) -> None:
    sdk = webview2_dir.resolve()
    if not sdk.is_dir():
        raise SystemExit(f"WebView2 SDK folder does not exist: {sdk}")
    for fname in REQUIRED_SDK_FILES:
        if not (sdk / fname).is_file():
            raise SystemExit(f"missing WebView2 SDK file: {sdk / fname}")

    if not OUT_HTML.is_file():
        build_html()

    csc = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    netfx = csc.parent

    def ref_path(dll_name: str) -> str:
        cand = netfx / dll_name
        return str(cand) if cand.is_file() else dll_name

    cmd = [
        str(csc),
        "/nologo",
        "/target:winexe",
        "/platform:x64",
        "/optimize+",
        "/debug-",
        f"/out:{OUT_EXE}",
        f"/reference:{ref_path('System.Windows.Forms.dll')}",
        f"/reference:{ref_path('System.Drawing.dll')}",
        f"/reference:{ref_path('System.Web.Extensions.dll')}",
        f"/reference:{sdk / 'Microsoft.Web.WebView2.Core.dll'}",
        f"/reference:{sdk / 'Microsoft.Web.WebView2.WinForms.dll'}",
        f"/resource:{sdk / 'Microsoft.Web.WebView2.Core.dll'},Microsoft.Web.WebView2.Core.dll",
        f"/resource:{sdk / 'Microsoft.Web.WebView2.WinForms.dll'},Microsoft.Web.WebView2.WinForms.dll",
        f"/resource:{sdk / 'WebView2Loader.dll'},WebView2Loader.dll",
        f"/resource:{sdk / 'LICENSE.txt'},WebView2-LICENSE.txt",
        f"/resource:{OUT_HTML},editor.html",
        str(SRC / "SaveStore.cs"),
        str(SRC / "SaveEditor.cs"),
    ]
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0 or not OUT_EXE.is_file():
        raise SystemExit(f"csc.exe failed with exit code {rc}")
    print(f"wrote {OUT_EXE} ({OUT_EXE.stat().st_size} bytes)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build Tale of Immortal Save Editor v1.0")
    ap.add_argument("--exe", action="store_true", help="also compile Windows x64 WebView2 exe")
    ap.add_argument("--webview2", default=None, type=Path, help="path to WebView2 SDK folder")
    args = ap.parse_args(argv)
    build_html()
    if args.exe:
        if not args.webview2:
            ap.error("--exe requires --webview2 <dir>")
        build_exe(args.webview2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
