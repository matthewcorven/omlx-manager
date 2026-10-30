#!/usr/bin/env python3
"""Configurable base paths for the oMLX harness.

Every machine-specific location this repo needs is a base path with an
environment-variable override and a default that matches the machine the
harness was developed on. Nothing is hardcoded to a working directory: the
scripts are run from the repo root, so every repo-relative path (corpora,
results, manifests) stays relative.

The defaults are documented in the `## Development` section of the root
`README.md`. Override any of them by exporting the variable before running a
script:

    export OMLX_BASE_URL=http://127.0.0.1:8001
    export OMLX_MODELS_DIR="$HOME/.omlx/models/mlx-community"

Run this module directly to print the resolved configuration:

    python3 scripts/omlx_config.py          # human-readable
    python3 scripts/omlx_config.py --json   # machine-readable
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# defaults
#
# These match the development machine (M4 Max / 128 GB). They are defaults,
# not requirements: every one is overridable, and no script reads the literal
# value below.
# --------------------------------------------------------------------------
DEFAULTS = {
    # HTTP surface
    "OMLX_BASE_URL": "http://127.0.0.1:8001",
    # oMLX install and its shipped Python source
    "OMLX_APP": "/Applications/oMLX.app",
    "OMLX_SOURCE_DIR": "/Applications/oMLX.app/Contents/Resources/omlx",
    # Interpreter that has Pillow + OpenCV. The stock python3 has neither.
    "OMLX_PYTHON": "/Applications/oMLX.app/Contents/MacOS/omlx-cluster-python",
    # oMLX state directory (settings.json, model_settings.json, cache/)
    "OMLX_HOME": "~/.omlx",
    # Model storage
    "OMLX_MODELS_DIR": "~/.omlx/models/mlx-community",
    "OMLX_EXTERNAL_MODELS_DIR": "/Volumes/NVMe/omlx-models",
    "OMLX_CACHE_DIR": "~/.omlx/cache",
    # Volume that holds the model dirs, for free-space checks
    "OMLX_DATA_VOLUME": "/System/Volumes/Data",
    # Corpus generation
    "OMLX_FONT_DIR": "/System/Library/Fonts/Supplemental",
    # Optional external tooling
    "OMLX_FFMPEG": "/opt/homebrew/bin/ffmpeg",
    "OMLX_SPLASH_BIN": "/opt/homebrew/bin/splash",
}


def _resolve(name: str) -> str:
    """Return the override for `name`, else its default, with `~` expanded."""
    return os.path.expanduser(os.environ.get(name) or DEFAULTS[name])


def _path(name: str) -> Path:
    return Path(_resolve(name))


# --------------------------------------------------------------------------
# resolved values
#
# Import these directly: `from omlx_config import BASE_URL, FONT_DIR`.
# --------------------------------------------------------------------------
BASE_URL = _resolve("OMLX_BASE_URL")
APP_DIR = _path("OMLX_APP")
SOURCE_DIR = _path("OMLX_SOURCE_DIR")
PYTHON = _path("OMLX_PYTHON")
HOME_DIR = _path("OMLX_HOME")
MODELS_DIR = _path("OMLX_MODELS_DIR")
EXTERNAL_MODELS_DIR = _path("OMLX_EXTERNAL_MODELS_DIR")
CACHE_DIR = _path("OMLX_CACHE_DIR")
DATA_VOLUME = _path("OMLX_DATA_VOLUME")
FONT_DIR = _path("OMLX_FONT_DIR")
FFMPEG = _path("OMLX_FFMPEG")
SPLASH_BIN = _path("OMLX_SPLASH_BIN")


def font(name: str) -> Path:
    """Resolve a font file inside `FONT_DIR`, failing with a usable message.

    A missing font is a configuration problem, not a corpus problem, so it is
    reported as one instead of surfacing as a Pillow traceback.
    """
    path = FONT_DIR / name
    if not path.is_file():
        raise SystemExit(
            f"font not found: {path}\n"
            f"set OMLX_FONT_DIR to a directory containing {name!r} "
            f"(currently {FONT_DIR})"
        )
    return path


def as_dict() -> dict[str, str]:
    """The resolved configuration, keyed by environment variable name."""
    return {name: _resolve(name) for name in DEFAULTS}


def main() -> int:
    if "--json" in sys.argv[1:]:
        json.dump(as_dict(), sys.stdout, indent=1)
        sys.stdout.write("\n")
        return 0

    width = max(len(n) for n in DEFAULTS)
    for name, value in as_dict().items():
        source = "env" if os.environ.get(name) else "default"
        print(f"{name:<{width}}  {value}  ({source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
