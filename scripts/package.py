"""Pack the files of custom_components/tts_http_gateway at the root of an archive.

Without arguments, writes dist/tts_http_gateway.zip for a release, which is what HACS unpacks with
zip_release (hacs.json). With --tar, writes a tar of the same files to stdout, to pipe to a Home
Assistant over SSH while developing.
"""

import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "custom_components" / "tts_http_gateway"
TARGET = ROOT / "dist" / "tts_http_gateway.zip"


def _files() -> list[Path]:
    return sorted(
        path
        for path in SOURCE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def _owned_by_root(info: tarfile.TarInfo) -> tarfile.TarInfo:
    # Windows reports every file as world-writable
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mode = 0o644
    return info


def main() -> int:
    files = _files()
    if sys.argv[1:] == ["--tar"]:
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
            for path in files:
                archive.add(path, path.relative_to(SOURCE).as_posix(), filter=_owned_by_root)
        return 0

    TARGET.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(SOURCE).as_posix())
    print(f"{TARGET.relative_to(ROOT).as_posix()}: {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
