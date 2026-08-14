"""SK8 S4 运维：孤儿派生文件清理、tmp 残留清理、原片保留政策、磁盘水位。

用法：
    python manage.py skate_media_gc             # 全量 dry-run 报告（不删除）
    python manage.py skate_media_gc --apply     # 真正执行删除/裁剪
    python manage.py skate_media_gc --json      # 单行 JSON（供监控采集）
    python manage.py skate_media_gc --orphans --tmp   # 只跑子集

安全设计（SKATEBOARD_GUIDE §9 S4）：
- 默认 dry-run：任何删除动作都必须显式 --apply。
- 孤儿 = 派生目录中 media_key 不在数据库的文件（Clip/Media 行已删后的残留）。
  数据库中存在但状态非 ready 的文件不删（可能是 stale Worker 刚发布的输出）。
- tmp/ 只清理「无对应媒体行 / 状态非 processing / processing 已卡死超时」的目录，
  正在进行的处理不受影响。
- 原片保留：ready 且 processed_at 早于 SKATE_CLIP_SOURCE_RETENTION_DAYS 天前
  的私有原片删除并把 source_file 置空（0 = 永久保留，默认）。原片删除后该媒体
  不可再重build（重试得到 source_missing），审计字段 source_size/sha256 保留。
- 磁盘水位：对私有原片与派生根所在卷计算使用率，超过
  SKATE_CLIP_DISK_HIGH_WATERMARK（百分比）时打印报告后以非零退出码告警。
"""

from __future__ import annotations

import json
import shutil
import uuid as uuid_lib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from boards.models import (
    SkateClipMedia,
    SkateClipMediaState,
    skate_delivery_storage,
    skate_source_storage,
)

# 派生目录布局（与 skate_worker 发布路径一一对应）
_ORPHAN_SCANS = ("delivery", "preview", "poster")


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def _tree_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    pass
    return total


def _parse_key(name: str) -> uuid_lib.UUID | None:
    try:
        return uuid_lib.UUID(name)
    except (ValueError, AttributeError, TypeError):
        return None


class Command(BaseCommand):
    help = (
        "SK8 S4 运维：派生孤儿清理、tmp 残留清理、原片保留政策、磁盘水位检查。"
        "默认 dry-run 只报告，--apply 才执行删除。"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="真正执行删除/裁剪（默认 dry-run 只报告）",
        )
        parser.add_argument("--orphans", action="store_true", help="扫描派生孤儿文件")
        parser.add_argument("--tmp", action="store_true", help="清理 tmp/ 残留目录")
        parser.add_argument("--retention", action="store_true", help="按保留政策裁剪私有原片")
        parser.add_argument(
            "--check-disk", action="store_true", help="检查私有/派生根磁盘水位"
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="单行 JSON 输出（供监控采集）",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        run_all = not any(
            options[name] for name in ("orphans", "tmp", "retention", "check_disk")
        )
        do_apply = options["apply"]
        report: dict = {"apply": do_apply}

        if run_all or options["orphans"]:
            report["orphans"] = self._gc_orphans(do_apply)
        if run_all or options["tmp"]:
            report["tmp"] = self._gc_tmp(do_apply)
        if run_all or options["retention"]:
            report["retention"] = self._gc_retention(do_apply)
        if run_all or options["check_disk"]:
            report["disk"] = self._check_disk()

        if options["as_json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False))
        else:
            self._print_report(report)

        if report.get("disk", {}).get("exceeded"):
            raise CommandError(
                "磁盘水位超过 SKATE_CLIP_DISK_HIGH_WATERMARK="
                f"{report['disk']['watermark']}%"
            )
        if report.get("disk", {}).get("unavailable"):
            raise CommandError("无法读取 SK8 媒体根目录所在磁盘的空间信息。")

    # ------------------------------------------------------------------
    def _known_media(self) -> dict[uuid_lib.UUID, tuple[str, object]]:
        return {
            row["media_key"]: (row["state"], row["claimed_at"])
            for row in SkateClipMedia.objects.values("media_key", "state", "claimed_at")
        }

    def _gc_orphans(self, do_apply: bool) -> dict:
        """清理无数据库引用的公私文件，并报告 ready 行缺失的派生文件。"""
        storage = skate_delivery_storage()
        known = set(self._known_media())
        referenced_derived = {
            name
            for row in SkateClipMedia.objects.values(
                "main_file", "preview_file", "poster_file"
            )
            for name in (row["main_file"], row["preview_file"], row["poster_file"])
            if name
        }
        targets: list[str] = []
        unexpected: list[str] = []
        for section in _ORPHAN_SCANS:
            try:
                dirs, files = storage.listdir(section)
            except FileNotFoundError:
                continue
            for name in dirs:
                key = _parse_key(name)
                if key is None:
                    # 非 UUID 目录名：按垃圾清理并单独报告
                    targets.append(f"{section}/{name}")
                    unexpected.append(f"{section}/{name}/")
                elif key not in known:
                    targets.append(f"{section}/{name}")
                else:
                    base = Path(storage.path(f"{section}/{name}"))
                    for child in base.rglob("*"):
                        if child.is_file():
                            rel = child.relative_to(Path(storage.location)).as_posix()
                            if rel not in referenced_derived:
                                targets.append(rel)
            for name in files:
                stem = name.rsplit(".", 1)[0] if "." in name else name
                key = _parse_key(stem)
                if key is None:
                    targets.append(f"{section}/{name}")
                    unexpected.append(f"{section}/{name}")
                elif key not in known:
                    targets.append(f"{section}/{name}")
                elif f"{section}/{name}" not in referenced_derived:
                    targets.append(f"{section}/{name}")

        freed = 0
        removed: list[str] = []
        for rel in targets:
            path = Path(storage.path(rel))
            size = _tree_size(path)
            if do_apply:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    storage.delete(rel)
            removed.append(rel)
            freed += size
        source_storage = skate_source_storage()
        referenced_sources = {
            name
            for name in SkateClipMedia.objects.exclude(source_file="").values_list(
                "source_file", flat=True
            )
        }
        source_orphans = []
        try:
            source_dirs, source_files = source_storage.listdir("")
        except FileNotFoundError:
            source_dirs, source_files = [], []
        for name in source_files:
            if name not in referenced_sources:
                source_orphans.append(name)
                freed += _tree_size(Path(source_storage.path(name)))
                if do_apply:
                    source_storage.delete(name)
        # 私有原片应为平铺 UUID 文件；目录属于异常孤儿，保守报告、不递归删除。
        unexpected.extend(f"source/{name}/" for name in source_dirs)

        missing = []
        for media in SkateClipMedia.objects.filter(state=SkateClipMediaState.READY):
            for label, field in (
                ("main", media.main_file),
                ("preview", media.preview_file),
                ("poster", media.poster_file),
            ):
                if not field or not storage.exists(field.name):
                    missing.append(
                        {"media_key": str(media.media_key), "asset": label, "key": field.name if field else ""}
                    )

        return {
            "count": len(removed),
            "bytes": freed,
            "keys": removed,
            "unexpected": unexpected,
            "source_orphans": source_orphans,
            "missing": missing,
        }

    # ------------------------------------------------------------------
    def _gc_tmp(self, do_apply: bool) -> dict:
        """清理 tmp/<key>/<generation>/：无媒体行 / 非 processing / 卡死超时。"""
        storage = skate_delivery_storage()
        known = self._known_media()
        stuck_after = getattr(settings, "SKATE_CLIP_STUCK_PROCESSING_SECONDS", 1800)
        now = timezone.now()
        removed: list[str] = []
        skipped_active = 0
        freed = 0
        try:
            dirs, _files = storage.listdir("tmp")
        except FileNotFoundError:
            return {"count": 0, "bytes": 0, "keys": [], "skipped_active": 0}

        for name in dirs:
            rel = f"tmp/{name}"
            key = _parse_key(name)
            if key is None or key not in known:
                pass  # 无对应媒体行 → 可清理
            else:
                state, claimed_at = known[key]
                if state == SkateClipMediaState.PROCESSING:
                    age = None if claimed_at is None else (now - claimed_at).total_seconds()
                    if age is None or age <= stuck_after:
                        skipped_active += 1
                        continue
            path = Path(storage.path(rel))
            size = _tree_size(path)
            if do_apply:
                shutil.rmtree(path, ignore_errors=True)
            removed.append(rel)
            freed += size
        return {
            "count": len(removed),
            "bytes": freed,
            "keys": removed,
            "skipped_active": skipped_active,
        }

    # ------------------------------------------------------------------
    def _gc_retention(self, do_apply: bool) -> dict:
        """按 SKATE_CLIP_SOURCE_RETENTION_DAYS 裁剪 ready 媒体的私有原片。"""
        days = getattr(settings, "SKATE_CLIP_SOURCE_RETENTION_DAYS", 0) or 0
        if days <= 0:
            return {"enabled": False, "days": days, "count": 0, "bytes": 0, "keys": []}
        cutoff = timezone.now() - timezone.timedelta(days=days)
        queryset = (
            SkateClipMedia.objects.filter(
                state=SkateClipMediaState.READY,
                processed_at__lt=cutoff,
            )
            .exclude(source_file="")
            .exclude(processed_at=None)
        )
        storage = skate_source_storage()
        removed: list[str] = []
        freed = 0
        for media in queryset.iterator():
            name = media.source_file.name  # FieldFile → 相对名
            try:
                size = storage.size(name)
            except OSError:
                size = 0
            if do_apply:
                rows = SkateClipMedia.objects.filter(
                    pk=media.pk,
                    state=SkateClipMediaState.READY,
                    source_file=name,
                    source_sha256=media.source_sha256,
                    processed_at=media.processed_at,
                ).update(source_file="")
                if rows != 1:
                    continue
                try:
                    storage.delete(name)
                except OSError:
                    # 数据库已不再引用旧原片；下次 --orphans 会报告并可清理。
                    continue
            removed.append(str(media.media_key))
            freed += size
        return {
            "enabled": True,
            "days": days,
            "count": len(removed),
            "bytes": freed,
            "keys": removed,
        }

    # ------------------------------------------------------------------
    def _check_disk(self) -> dict:
        watermark = getattr(settings, "SKATE_CLIP_DISK_HIGH_WATERMARK", 90)
        volumes = []
        for label, root in (
            ("source", Path(settings.SKATE_CLIP_SOURCE_ROOT)),
            ("delivery", Path(settings.SKATE_CLIP_DELIVERY_ROOT)),
        ):
            probe = root
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            try:
                usage = shutil.disk_usage(str(probe))
            except OSError as exc:
                volumes.append(
                    {
                        "label": label,
                        "path": str(root),
                        "probe_path": str(probe),
                        "percent": None,
                        "error": str(exc)[:160],
                    }
                )
                continue
            percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
            volumes.append(
                {"label": label, "path": str(root), "probe_path": str(probe), "percent": percent}
            )
        unavailable = any(v["percent"] is None for v in volumes)
        exceeded = any(v["percent"] is not None and v["percent"] > watermark for v in volumes)
        return {
            "watermark": watermark,
            "volumes": volumes,
            "exceeded": exceeded,
            "unavailable": unavailable,
        }

    # ------------------------------------------------------------------
    def _print_report(self, report: dict) -> None:
        orphans = report.get("orphans")
        if orphans is not None:
            self.stdout.write(
                f"orphans: {orphans['count']} 个 / {_human_size(orphans['bytes'])}"
            )
            for rel in orphans["keys"]:
                self.stdout.write(f"  - {rel}")
            for rel in orphans["unexpected"]:
                self.stdout.write(self.style.WARNING(f"  ! 非预期条目: {rel}"))
            for rel in orphans["source_orphans"]:
                self.stdout.write(f"  - source/{rel}")
            for item in orphans["missing"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ! 缺失派生资源: {item['media_key']} {item['asset']} {item['key']}"
                    )
                )
        tmp = report.get("tmp")
        if tmp is not None:
            self.stdout.write(
                f"tmp: {tmp['count']} 个 / {_human_size(tmp['bytes'])}"
                f"（跳过进行中 {tmp['skipped_active']} 个）"
            )
            for rel in tmp["keys"]:
                self.stdout.write(f"  - {rel}/")
        retention = report.get("retention")
        if retention is not None:
            if retention["enabled"]:
                self.stdout.write(
                    f"retention: {retention['days']} 天政策，裁剪 "
                    f"{retention['count']} 个 / {_human_size(retention['bytes'])}"
                )
            else:
                self.stdout.write(
                    f"retention: 已禁用（SKATE_CLIP_SOURCE_RETENTION_DAYS="
                    f"{retention['days']}）"
                )
        disk = report.get("disk")
        if disk is not None:
            parts = " / ".join(
                f"{v['label']} {v['percent']}%" if v["percent"] is not None
                else f"{v['label']} unavailable"
                for v in disk["volumes"]
            )
            line = f"disk: {parts}（阈值 {disk['watermark']}%）"
            self.stdout.write(self.style.ERROR(line) if disk["exceeded"] else line)
        if report["apply"]:
            self.stdout.write(self.style.SUCCESS("已按 --apply 执行。"))
        else:
            self.stdout.write("dry-run：未删除任何文件；加 --apply 执行。")
