#!/usr/bin/env python3
"""Render the product SVG into a complete deterministic macOS iconset."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import tempfile
from typing import Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "desktop" / "assets" / "app-icon.svg"
DEFAULT_OUTPUT = ROOT / "build" / "macos" / "E-WasteTriage.icns"
ICONSET_FILES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def render_icon(
    source: Path,
    output: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    """Render *source* at every required size and compile *output* with iconutil."""
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != ".svg" or not source.is_file():
        raise ValueError("icon source must be an SVG file")
    output = Path(output).resolve()
    if output.suffix.lower() != ".icns":
        raise ValueError("icon output must use the .icns extension")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ewaste-icon-") as temporary:
        iconset = Path(temporary) / "E-WasteTriage.iconset"
        iconset.mkdir()
        for filename, pixels in ICONSET_FILES.items():
            destination = iconset / filename
            runner(
                [
                    "/usr/bin/sips",
                    "-s",
                    "format",
                    "png",
                    "--resampleHeightWidth",
                    str(pixels),
                    str(pixels),
                    str(source),
                    "--out",
                    str(destination),
                ],
                check=True,
            )
            if not destination.is_file():
                raise RuntimeError(f"sips did not create {filename}")
        runner(
            ["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(output)],
            check=True,
        )
    if not output.is_file():
        raise RuntimeError("iconutil did not create the requested .icns file")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)
    print(render_icon(arguments.source, arguments.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
