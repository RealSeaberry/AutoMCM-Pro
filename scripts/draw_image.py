#!/usr/bin/env python3
"""
Generate an image via OpenAI image models and save it to disk.

Default model: gpt-image-2 (released 2026-04-21).
Fallback supported: gpt-image-1.5, gpt-image-1, gpt-image-1-mini, dall-e-3.

Auth priority (checked in order):
  1. OPENAI_API_KEY env var  → uses OpenAI Python SDK directly
  2. Codex OAuth session     → exits with code 2 and prints $imagegen command
  3. Neither                 → exits with code 2 (skip signal, not error)

Exit codes:
  0  Image saved successfully
  1  Runtime error (API failure, bad params, import missing)
  2  Auth unavailable — caller should skip quietly (not an error)

Usage:
  python scripts/draw_image.py --prompt "..." --output "latex/images/fig_flow.png"
  python scripts/draw_image.py --check          # auth check only, no generation
  python scripts/draw_image.py --prompt "..." --output "..." --size 1536x1024 --quality high
  python scripts/draw_image.py --prompt "..." --output "out.jpg" --output-format jpeg --compression 80

gpt-image-2 size rules (any WxH string is accepted):
  • Each edge must be a multiple of 16 px
  • Maximum edge ≤ 3840 px
  • Long-to-short edge ratio ≤ 3:1
  • Total pixels: 655,360 – 8,294,400
  Common presets: 1024x1024, 1536x1024, 1024x1536, 2048x2048,
                  2048x1152, 1152x2048, 3840x2160, 2160x3840

Requires (API path):
  pip install openai>=1.0
  export OPENAI_API_KEY=sk-...
  Organization verification at platform.openai.com/settings/organization/general
"""

import argparse
import base64
import json
import os
import shutil
import sys
from pathlib import Path


# gpt-image-2 does not yet support transparent backgrounds (as of 2026-04-21)
_TRANSPARENT_UNSUPPORTED = {"gpt-image-2"}

# Candidate paths where Codex CLI stores its OAuth session on Linux/WSL/macOS
_CODEX_AUTH_PATHS = [
    Path.home() / ".codex" / "auth.json",
    Path.home() / ".codex" / "config.json",
    Path.home() / ".config" / "codex" / "auth.json",
    Path.home() / ".config" / "openai" / "codex.json",
    Path.home() / "AppData" / "Roaming" / "Codex" / "auth.json",  # Windows
]


def _find_codex_oauth() -> str | None:
    """
    Return a Codex OAuth access_token if a valid session file is found,
    else return None.  The token cannot be used directly with the OpenAI
    Python SDK (it is a ChatGPT OAuth token, not an API key), so callers
    should route generation through the Codex CLI's native $imagegen.
    """
    # Explicit override
    env_token = os.environ.get("CODEX_AUTH_TOKEN") or os.environ.get("OPENAI_OAUTH_TOKEN")
    if env_token:
        return env_token

    for path in _CODEX_AUTH_PATHS:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            token = (
                data.get("access_token")
                or data.get("token")
                or data.get("api_key")
            )
            if token:
                return token
        except Exception:
            continue
    return None


def check_auth() -> dict:
    """
    Probe available authentication and return a status dict.

    Returns:
        {
            "available": bool,
            "method": "api_key" | "codex_oauth" | "none",
            "key": str | None,   # set only for api_key method
            "message": str,
        }
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        return {
            "available": True,
            "method": "api_key",
            "key": api_key,
            "message": "OPENAI_API_KEY is set — API path available",
        }

    oauth_token = _find_codex_oauth()
    codex_cli = shutil.which("codex")
    if oauth_token or codex_cli:
        return {
            "available": True,
            "method": "codex_oauth",
            "key": None,
            "message": (
                "Codex OAuth session detected — image generation available via Codex CLI.\n"
                "  Use: $imagegen <prompt>  inside the Codex CLI, or\n"
                "       set OPENAI_API_KEY to also enable this script."
            ),
        }

    return {
        "available": False,
        "method": "none",
        "key": None,
        "message": (
            "No auth available.  To enable draw-image:\n"
            "  API path :  export OPENAI_API_KEY=sk-proj-...\n"
            "              (get key at https://platform.openai.com/api-keys)\n"
            "  Codex path: install Codex CLI and sign in (no API key needed)\n"
            "              then use $imagegen inside Codex instead of this script."
        ),
    }


def _infer_format(output_path: str, explicit_format: str | None) -> str:
    if explicit_format:
        return explicit_format
    ext = Path(output_path).suffix.lower().lstrip(".")
    return {"jpg": "jpeg"}.get(ext, ext) if ext in ("jpg", "jpeg", "webp") else "png"


def generate(
    prompt: str,
    output: str,
    size: str,
    quality: str,
    model: str,
    output_format: str | None,
    compression: int | None,
    background: str,
    moderation: str,
) -> None:
    auth = check_auth()

    if not auth["available"]:
        print(f"[draw_image] SKIP — {auth['message']}", file=sys.stderr)
        sys.exit(2)

    if auth["method"] == "codex_oauth":
        print(
            f"[draw_image] SKIP — Codex OAuth detected but cannot use SDK.\n"
            f"  Run this inside Codex CLI instead:\n"
            f"  $imagegen {prompt[:120]}",
            file=sys.stderr,
        )
        sys.exit(2)

    # ── API key path ──────────────────────────────────────────────────
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed — run: pip install openai", file=sys.stderr)
        sys.exit(1)

    fmt = _infer_format(output, output_format)

    if background == "transparent" and model in _TRANSPARENT_UNSUPPORTED:
        print(
            f"[draw_image] WARNING: {model} does not support transparent backgrounds"
            " — falling back to 'opaque'",
            file=sys.stderr,
        )
        background = "opaque"

    client = OpenAI(api_key=auth["key"])
    print(
        f"[draw_image] model={model}  size={size}  quality={quality}"
        f"  format={fmt}  background={background}"
    )
    print(f"[draw_image] prompt: {prompt}")

    kwargs: dict = dict(
        model=model,
        prompt=prompt,
        n=1,
        size=size,
        quality=quality,
        output_format=fmt,
        background=background,
        moderation=moderation,
    )
    if compression is not None and fmt in ("jpeg", "webp"):
        kwargs["output_compression"] = compression

    response = client.images.generate(**kwargs)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    img = response.data[0]
    if getattr(img, "b64_json", None):
        out.write_bytes(base64.b64decode(img.b64_json))
    elif getattr(img, "url", None):
        import urllib.request
        urllib.request.urlretrieve(img.url, str(out))
    else:
        print("ERROR: API returned no image data", file=sys.stderr)
        sys.exit(1)

    if hasattr(response, "usage") and response.usage:
        u = response.usage
        print(
            f"[draw_image] tokens — input: {u.input_tokens}"
            f"  output: {u.output_tokens}  total: {u.total_tokens}"
        )

    print(f"[draw_image] SAVED → {out.resolve()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Generate an image via OpenAI gpt-image-2 (or older models)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--check", action="store_true",
                    help="Check auth status only, do not generate an image")
    ap.add_argument("--prompt",
                    help="Image description (max 32,000 chars)")
    ap.add_argument("--output",
                    help="Destination file path (.png / .jpg / .webp)")
    ap.add_argument("--model", default="gpt-image-2",
                    choices=["gpt-image-2", "gpt-image-1.5", "gpt-image-1",
                             "gpt-image-1-mini", "dall-e-3", "dall-e-2"],
                    help="OpenAI image model (default: gpt-image-2)")
    ap.add_argument("--size", default="1024x1024",
                    help=(
                        "Image dimensions. gpt-image-2: any WxH where each edge is a multiple "
                        "of 16, max 3840, ratio ≤ 3:1. "
                        "Common: 1024x1024, 1536x1024, 1024x1536, 2048x2048, 3840x2160. "
                        "(default: 1024x1024)"
                    ))
    ap.add_argument("--quality", default="medium",
                    choices=["low", "medium", "high", "auto"],
                    help="Rendering quality (default: medium). Use 'high' for final figures.")
    ap.add_argument("--output-format", dest="output_format", default=None,
                    choices=["png", "jpeg", "webp"],
                    help="Image file format (default: inferred from --output extension, else png)")
    ap.add_argument("--compression", type=int, default=None, metavar="0-100",
                    help="Compression for jpeg/webp (0=max quality, 100=max compression)")
    ap.add_argument("--background", default="opaque",
                    choices=["opaque", "transparent", "auto"],
                    help="Background type. Note: gpt-image-2 does not support transparent.")
    ap.add_argument("--moderation", default="auto",
                    choices=["auto", "low"],
                    help="Content moderation strictness (default: auto)")
    args = ap.parse_args()

    if args.check:
        auth = check_auth()
        print(f"[draw_image:check] method={auth['method']}  available={auth['available']}")
        print(f"[draw_image:check] {auth['message']}")
        sys.exit(0 if auth["available"] else 2)

    if not args.prompt or not args.output:
        ap.error("--prompt and --output are required (or use --check for auth check only)")

    generate(
        prompt=args.prompt,
        output=args.output,
        size=args.size,
        quality=args.quality,
        model=args.model,
        output_format=args.output_format,
        compression=args.compression,
        background=args.background,
        moderation=args.moderation,
    )
