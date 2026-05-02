#!/usr/bin/env python3
"""
Call OpenAI gpt-image-1 to generate an image and save it to disk.

Usage:
  python scripts/draw_image.py --prompt "..." --output "latex/images/fig_flow.png"
  python scripts/draw_image.py --prompt "..." --output "..." --size 1536x1024 --quality high

Requires: pip install openai
Requires: OPENAI_API_KEY env var set
"""

import argparse
import base64
import os
import sys
from pathlib import Path


def generate(prompt: str, output: str, size: str, quality: str, model: str) -> None:
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed — run: pip install openai", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    print(f"[draw_image] model={model}  size={size}  quality={quality}")
    print(f"[draw_image] prompt: {prompt}")

    response = client.images.generate(
        model=model,
        prompt=prompt,
        n=1,
        size=size,
        quality=quality,
    )

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

    print(f"[draw_image] SAVED → {out.resolve()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate an image via OpenAI gpt-image-1")
    ap.add_argument("--prompt",   required=True,  help="Image description / prompt")
    ap.add_argument("--output",   required=True,  help="Destination file path (.png)")
    ap.add_argument("--size",     default="1024x1024",
                    choices=["1024x1024", "1536x1024", "1024x1536", "auto"],
                    help="Image dimensions (default: 1024x1024)")
    ap.add_argument("--quality",  default="medium",
                    choices=["low", "medium", "high", "auto"],
                    help="Rendering quality (default: medium)")
    ap.add_argument("--model",    default="gpt-image-1",
                    help="OpenAI image model (default: gpt-image-1)")
    args = ap.parse_args()
    generate(args.prompt, args.output, args.size, args.quality, args.model)
