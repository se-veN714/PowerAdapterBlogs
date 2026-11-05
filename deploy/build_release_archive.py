"""Build a complete runtime release archive from a verified manifest."""

from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path

try:
    from deploy.manifest import verify_manifest
except ModuleNotFoundError:  # direct execution as deploy/build_release_archive.py
    from manifest import verify_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    manifest_path = args.manifest.resolve()
    problems, _unexpected = verify_manifest(root, manifest_path)
    if problems:
        raise SystemExit("manifest verification failed before archive creation")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = [item["path"] for item in payload["files"]]
    paths.append(manifest_path.relative_to(root).as_posix())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, "w:gz") as archive:
        for relative in paths:
            archive.add(root / relative, arcname=relative)
    print(f"release archive created: {args.output} ({len(paths)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
