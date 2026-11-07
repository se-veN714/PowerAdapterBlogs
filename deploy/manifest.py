"""Generate and verify the production source-file manifest.

The manifest deliberately scans the working tree instead of ``git ls-files``:
agent-facing files may be present before their eventual commit, and those files
still need to be part of the release artifact.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
from pathlib import Path


SCHEMA_VERSION = 1
DEFAULT_ROOTS = (
    "manage.py",
    "requirements.txt",
    "compose.production.yml",
    "Dockerfile",
    "PowerAdapterBlogs",
    "Blogs",
    "accounts",
    "agent_mcp",
    "boards",
    "comment",
    "config",
    "moderation",
    "operations",
    "padif",
    "security",
    "themes/devenir/templates",
    "themes/devenir/static",
    "static",
    "deploy/docker",
    "deploy/manifest.py",
    "deploy/mongo",
    "deploy/nginx",
    "deploy/logrotate",
    "deploy/systemd",
)
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        ".local",
        ".agents",
        ".codex",
        ".workbuddy",
        ".idea",
        "node_modules",
        "__pycache__",
        "media",
        "media-private",
        "logs",
        "common_static",
        "var",
        "secrets",
    }
)
EXCLUDED_FILE_NAMES = frozenset(
    {
        ".env.production",
        "production-manifest.json",
    }
)
EXCLUDED_PATH_PATTERNS = (
    "themes/devenir/static/images/boards/*.png",
    "themes/devenir/static/images/errors/source/*",
    "themes/devenir/static/images/errors/work/*",
)


def _iter_files(root: Path, relative_root: Path, project_root: Path):
    if not root.exists():
        raise FileNotFoundError(relative_root.as_posix())
    if root.is_file():
        yield root, relative_root
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root)
        if any(part in EXCLUDED_DIR_NAMES for part in relative.parts[:-1]):
            continue
        relative_name = relative.as_posix()
        if (
            path.name in EXCLUDED_FILE_NAMES
            or path.suffix == ".pyc"
            or any(fnmatch.fnmatch(relative_name, pattern) for pattern in EXCLUDED_PATH_PATTERNS)
        ):
            continue
        yield path, relative


def iter_manifest_files(project_root: Path):
    seen: set[str] = set()
    for entry in DEFAULT_ROOTS:
        path = project_root / entry
        for absolute, relative in _iter_files(path, Path(entry), project_root):
            key = relative.as_posix()
            if key in seen:
                continue
            seen.add(key)
            yield absolute, relative


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(project_root: Path) -> dict:
    files = []
    for absolute, relative in iter_manifest_files(project_root):
        files.append(
            {
                "path": relative.as_posix(),
                "size": absolute.stat().st_size,
                "sha256": _sha256(absolute),
            }
        )
    files.sort(key=lambda item: item["path"])
    return {"schema_version": SCHEMA_VERSION, "files": files}


def write_manifest(project_root: Path, output: Path) -> dict:
    manifest = build_manifest(project_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_manifest(project_root: Path, manifest_path: Path) -> tuple[list[str], list[str]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported deployment manifest schema")
    expected = {
        item["path"]: item
        for item in payload.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if len(expected) != len(payload.get("files", [])):
        raise ValueError("deployment manifest contains invalid or duplicate entries")

    missing_or_mismatched = []
    for relative, item in expected.items():
        path = project_root / Path(relative)
        if not path.is_file():
            missing_or_mismatched.append(f"missing: {relative}")
            continue
        actual_size = path.stat().st_size
        actual_hash = _sha256(path)
        if actual_size != item.get("size") or actual_hash != item.get("sha256"):
            missing_or_mismatched.append(f"changed: {relative}")

    actual_paths = {
        relative.as_posix()
        for _absolute, relative in iter_manifest_files(project_root)
    }
    unexpected = sorted(actual_paths - set(expected))
    return sorted(missing_or_mismatched), unexpected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--root", type=Path, default=Path.cwd())
    generate.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--root", type=Path, default=Path.cwd())
    verify.add_argument("--manifest", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "generate":
        manifest = write_manifest(args.root.resolve(), args.output)
        print(f"manifest generated: {len(manifest['files'])} files")
        return 0

    try:
        problems, unexpected = verify_manifest(args.root.resolve(), args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"manifest verification failed: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    for path in unexpected:
        print(f"warning: unexpected runtime file: {path}")
    if problems:
        print(f"manifest verification failed: {len(problems)} mismatches", file=sys.stderr)
        return 1
    print(f"manifest verified: {len(expected_paths(args.manifest))} files")
    return 0


def expected_paths(manifest_path: Path) -> list[str]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [item["path"] for item in payload["files"]]


if __name__ == "__main__":
    raise SystemExit(main())
