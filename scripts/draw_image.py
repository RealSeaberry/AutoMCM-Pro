#!/usr/bin/env python3
"""
Generate an image via OpenAI image models and save it to disk.

Default model: gpt-image-2 (released 2026-04-21).
Fallback supported: gpt-image-1, gpt-image-1.5, gpt-image-1-mini.

Usage:
  python scripts/draw_image.py --prompt "..." --output "latex/images/fig_flow.png"
  python scripts/draw_image.py --prompt "..." --output "..." --size 1536x1024 --quality high
  python scripts/draw_image.py --prompt "..." --output "out.jpg" --output-format jpeg --compression 80

gpt-image-2 size rules (any WxH string is accepted):
  • Each edge must be a multiple of 16 px
  • Maximum edge ≤ 3840 px
  • Long-to-short edge ratio ≤ 3:1
  • Total pixels: 655,360 – 8,294,400
  Common presets: 1024x1024, 1536x1024, 1024x1536, 2048x2048,
                  2048x1152, 1152x2048, 3840x2160, 2160x3840

Requires:
  pip install openai>=1.0
  export OPENAI_API_KEY=sk-...
  Organization verification at platform.openai.com/settings/organization/general
  (required for all GPT Image models)
"""

import argparse
import base64
import os
import sys
from pathlib import Path


# gpt-image-2 does not support transparent backgrounds (API limitation as of 2026-04-21)
_TRANSPARENT_UNSUPPORTED = {"gpt-image-2"}


def _infer_format(output_path: str, explicit_format: str | None) -> str:
    """Derive output_format from file extension when not explicitly set."""
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
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed — run: pip install openai", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set", file=sys.stderr)
        print("       Get a key at https://platform.openai.com/api-keys", file=sys.stderr)
        print("       GPT Image models also require org verification:", file=sys.stderr)
        print("       https://platform.openai.com/settings/organization/general", file=sys.stderr)
        sys.exit(1)

    fmt = _infer_format(output, output_format)

    # gpt-image-2 does not support transparent backgrounds
    if background == "transparent" and model in _TRANSPARENT_UNSUPPORTED:
        print(f"WARNING: {model} does not support transparent backgrounds — using 'opaque'", file=sys.stderr)
        background = "opaque"

    client = OpenAI(api_key=api_key)

    print(f"[draw_image] model={model}  size={size}  quality={quality}  format={fmt}  background={background}")
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

    # Print token usage if available (gpt-image-2 / gpt-image-1)
    if hasattr(response, "usage") and response.usage:
        u = response.usage
        print(f"[draw_image] tokens — input: {u.input_tokens}  output: {u.output_tokens}  total: {u.total_tokens}")

    print(f"[draw_image] SAVED → {out.resolve()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Generate an image via OpenAI gpt-image-2 (or older models)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--prompt", required=True,
                    help="Image description (max 32,000 chars)")
    ap.add_argument("--output", required=True,
                    help="Destination file path (.png / .jpg / .webp)")
    ap.add_argument("--model", default="gpt-image-2",
                    choices=["gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini",
                             "dall-e-3", "dall-e-2"],
                    help="OpenAI image model (default: gpt-image-2)")
    ap.add_argument("--size", default="1024x1024",
                    help=(
                        "Image dimensions. gpt-image-2 accepts any WxH where each edge is a "
                        "multiple of 16, max 3840, ratio ≤ 3:1. "
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
                    help="Compression level for jpeg/webp (0=max quality, 100=max compression)")
    ap.add_argument("--background", default="opaque",
                    choices=["opaque", "transparent", "auto"],
                    help="Background type (default: opaque). Note: gpt-image-2 does not support transparent.")
    ap.add_argument("--moderation", default="auto",
                    choices=["auto", "low"],
                    help="Content moderation strictness (default: auto)")
    args = ap.parse_args()

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
