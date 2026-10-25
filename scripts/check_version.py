"""Check that manifest.json and pyproject.toml carry the same version, and that it's the one
being released when a version is given: python scripts/check_version.py [X.Y.Z]."""

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    manifest = json.loads(
        (ROOT / "custom_components" / "tts_http_gateway" / "manifest.json").read_text("utf-8")
    )["version"]
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    if manifest != pyproject:
        print(f"manifest.json has {manifest} but pyproject.toml has {pyproject}")
        return 1
    if len(sys.argv) > 1 and sys.argv[1] != manifest:
        print(f"Releasing {sys.argv[1]} but manifest.json and pyproject.toml have {manifest}")
        return 1
    print(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
