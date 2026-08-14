"""SK8 S4 测试：运维——GC（孤儿/tmp/retention/磁盘水位）与 Worker 可观测性。

验证：
- skate_media_gc 默认 dry-run 不删除；--apply 才执行
- 孤儿 = 派生目录中 media_key 不在数据库的文件；已知 key 的文件保留
- tmp/ 只清理无媒体行 / 非 processing / 卡死超时的目录，进行中的跳过
- retention=0 禁用；超期 ready 原片删除且 source_file 置空、审计字段保留
- 磁盘水位超阈值时以 CommandError 非零退出（JSON 报告先输出）
- process_skate_clips --json 汇总（队列水位、failed_by_error 分组、逐条耗时）
"""

from __future__ import annotations

import json
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from boards.models import (
    Board,
    SkateClip,
    SkateClipMedia,
    SkateClipMediaState,
    SkateHomie,
    skate_delivery_storage,
    skate_source_storage,
)


def _make_clip():
    board, _ = Board.objects.get_or_create(slug="skateboard", name="Skateboard")
    homie = SkateHomie.objects.create(
        board=board,
        node_index=SkateHomie.objects.count() + 1,
        name="Tester",
        joined_at="2026-08-01",
    )
    return SkateClip.objects.create(homie=homie, order=0, title="Ollie", is_public=True)


def _make_media(**overrides):
    defaults = dict(clip=_make_clip(), state=SkateClipMediaState.READY)
    defaults.update(overrides)
    return SkateClipMedia.objects.create(**defaults)


def _put(delivery, name, content=b"asset"):
    delivery.save(name, ContentFile(content))


class _StorageSandbox:
    """每个测试独立的 source/delivery 目录 + settings 覆盖。"""

    def __enter__(self):
        self.src_tmp = tempfile.TemporaryDirectory()
        self.dst_tmp = tempfile.TemporaryDirectory()
        self.ctx = override_settings(
            SKATE_CLIP_SOURCE_ROOT=Path(self.src_tmp.name),
            SKATE_CLIP_DELIVERY_ROOT=Path(self.dst_tmp.name),
        )
        self.ctx.enable()
        return skate_source_storage(), skate_delivery_storage()

    def __exit__(self, *exc):
        self.ctx.disable()
        self.dst_tmp.cleanup()
        self.src_tmp.cleanup()
        return False


def _run_gc(*args):
    out = StringIO()
    call_command("skate_media_gc", *args, stdout=out)
    return out.getvalue()


def _run_gc_json(*args):
    out = StringIO()
    call_command("skate_media_gc", *args, "--json", stdout=out)
    return json.loads(out.getvalue())


# ---------------------------------------------------------------------------
# 孤儿派生文件
# ---------------------------------------------------------------------------


class GcOrphanTests(TestCase):
    def test_dry_run_reports_orphans_without_deleting(self):
        with _StorageSandbox() as (_src, delivery):
            orphan_key = uuid.uuid4()
            _put(delivery, f"delivery/{orphan_key}/main.webm")
            _put(delivery, f"poster/{orphan_key}.webp")
            report = _run_gc_json("--orphans")
            self.assertEqual(report["orphans"]["count"], 2)
            self.assertTrue(delivery.exists(f"delivery/{orphan_key}/main.webm"))
            self.assertTrue(delivery.exists(f"poster/{orphan_key}.webp"))

    def test_apply_removes_orphans_keeps_known_keys(self):
        with _StorageSandbox() as (_src, delivery):
            media = _make_media()
            orphan_key = uuid.uuid4()
            known_name = f"delivery/{media.media_key}/main.webm"
            _put(delivery, known_name)
            SkateClipMedia.objects.filter(pk=media.pk).update(main_file=known_name)
            _put(delivery, f"delivery/{orphan_key}/main.webm")
            report = _run_gc_json("--orphans", "--apply")
            self.assertEqual(report["orphans"]["count"], 1)
            self.assertTrue(delivery.exists(f"delivery/{media.media_key}/main.webm"))
            self.assertFalse(delivery.exists(f"delivery/{orphan_key}/main.webm"))

    def test_non_uuid_entries_reported_and_cleaned(self):
        with _StorageSandbox() as (_src, delivery):
            _put(delivery, "poster/.DS_Store")
            report = _run_gc_json("--orphans", "--apply")
            self.assertIn("poster/.DS_Store", report["orphans"]["unexpected"])
            self.assertEqual(report["orphans"]["count"], 1)
            self.assertFalse(delivery.exists("poster/.DS_Store"))

    def test_source_orphan_and_missing_ready_asset_are_reported(self):
        with _StorageSandbox() as (source, _delivery):
            media = _make_media(main_file="delivery/missing/main.webm")
            source.save("orphan.mp4", ContentFile(b"src"))

            report = _run_gc_json("--orphans")

            self.assertEqual(report["orphans"]["source_orphans"], ["orphan.mp4"])
            self.assertTrue(
                any(
                    item["media_key"] == str(media.media_key) and item["asset"] == "main"
                    for item in report["orphans"]["missing"]
                )
            )


# ---------------------------------------------------------------------------
# tmp/ 残留
# ---------------------------------------------------------------------------


class GcTmpTests(TestCase):
    def test_tmp_removed_when_media_row_missing(self):
        with _StorageSandbox() as (_src, delivery):
            ghost = uuid.uuid4()
            _put(delivery, f"tmp/{ghost}/2/main.webm")
            report = _run_gc_json("--tmp", "--apply")
            self.assertEqual(report["tmp"]["count"], 1)
            self.assertFalse(delivery.exists(f"tmp/{ghost}/2/main.webm"))

    def test_tmp_skipped_while_processing_claimed_recently(self):
        with _StorageSandbox() as (_src, delivery):
            media = _make_media(state=SkateClipMediaState.PROCESSING)
            SkateClipMedia.objects.filter(pk=media.pk).update(
                claimed_at=timezone.now()
            )
            _put(delivery, f"tmp/{media.media_key}/1/main.webm")
            report = _run_gc_json("--tmp", "--apply")
            self.assertEqual(report["tmp"]["count"], 0)
            self.assertEqual(report["tmp"]["skipped_active"], 1)
            self.assertTrue(delivery.exists(f"tmp/{media.media_key}/1/main.webm"))

    def test_tmp_removed_when_processing_stuck(self):
        with _StorageSandbox() as (_src, delivery):
            media = _make_media(state=SkateClipMediaState.PROCESSING)
            SkateClipMedia.objects.filter(pk=media.pk).update(
                claimed_at=timezone.now() - timezone.timedelta(hours=2)
            )
            _put(delivery, f"tmp/{media.media_key}/1/main.webm")
            report = _run_gc_json("--tmp", "--apply")
            self.assertEqual(report["tmp"]["count"], 1)
            self.assertFalse(delivery.exists(f"tmp/{media.media_key}/1/main.webm"))

    def test_tmp_removed_when_media_not_processing(self):
        with _StorageSandbox() as (_src, delivery):
            media = _make_media(state=SkateClipMediaState.READY)
            _put(delivery, f"tmp/{media.media_key}/3/main.webm")
            report = _run_gc_json("--tmp", "--apply")
            self.assertEqual(report["tmp"]["count"], 1)
            self.assertFalse(delivery.exists(f"tmp/{media.media_key}/3/main.webm"))


# ---------------------------------------------------------------------------
# 原片保留政策
# ---------------------------------------------------------------------------


class GcRetentionTests(TestCase):
    def test_retention_disabled_by_default(self):
        with _StorageSandbox() as (source, delivery):
            media = _make_media()
            source_name = "legacy.mp4"
            source.save(source_name, ContentFile(b"src"))
            SkateClipMedia.objects.filter(pk=media.pk).update(
                source_file=source_name,
                processed_at=timezone.now() - timezone.timedelta(days=90),
            )
            report = _run_gc_json("--retention", "--apply")
            self.assertFalse(report["retention"]["enabled"])
            self.assertTrue(source.exists(source_name))
            media.refresh_from_db()
            self.assertEqual(media.source_file, source_name)

    def test_retention_prunes_expired_source(self):
        with _StorageSandbox() as (source, delivery):
            media = _make_media()
            source_name = f"{media.media_key}.mp4"
            source.save(source_name, ContentFile(b"src" * 100))
            SkateClipMedia.objects.filter(pk=media.pk).update(
                source_file=source_name,
                processed_at=timezone.now() - timezone.timedelta(days=30),
                source_size=300,
                source_sha256="0" * 64,
            )
            with override_settings(SKATE_CLIP_SOURCE_RETENTION_DAYS=7):
                report = _run_gc_json("--retention", "--apply")
            self.assertTrue(report["retention"]["enabled"])
            self.assertEqual(report["retention"]["count"], 1)
            self.assertFalse(source.exists(source_name))
            media.refresh_from_db()
            self.assertEqual(media.source_file, "")
            self.assertEqual(media.state, SkateClipMediaState.READY)
            # 审计字段保留（恢复演练/对账仍可追溯）
            self.assertEqual(media.source_size, 300)
            self.assertEqual(media.source_sha256, "0" * 64)

    def test_retention_keeps_recent_source(self):
        with _StorageSandbox() as (source, delivery):
            media = _make_media()
            source_name = f"{media.media_key}.mp4"
            source.save(source_name, ContentFile(b"src"))
            SkateClipMedia.objects.filter(pk=media.pk).update(
                source_file=source_name,
                processed_at=timezone.now() - timezone.timedelta(days=1),
            )
            with override_settings(SKATE_CLIP_SOURCE_RETENTION_DAYS=7):
                report = _run_gc_json("--retention", "--apply")
            self.assertEqual(report["retention"]["count"], 0)
            self.assertTrue(source.exists(source_name))

    def test_retention_cas_does_not_delete_replaced_source(self):
        with _StorageSandbox() as (source, _delivery):
            media = _make_media()
            old_name = f"{media.media_key}.mp4"
            source.save(old_name, ContentFile(b"old"))
            processed_at = timezone.now() - timezone.timedelta(days=30)
            SkateClipMedia.objects.filter(pk=media.pk).update(
                source_file=old_name,
                source_sha256="a" * 64,
                processed_at=processed_at,
            )

            original_filter = SkateClipMedia.objects.filter

            def replace_before_cas(*args, **kwargs):
                if kwargs.get("source_file") == old_name:
                    original_filter(pk=media.pk).update(
                        source_file="replacement.mp4", source_sha256="b" * 64
                    )
                return original_filter(*args, **kwargs)

            with override_settings(SKATE_CLIP_SOURCE_RETENTION_DAYS=7):
                with mock.patch.object(
                    SkateClipMedia.objects, "filter", side_effect=replace_before_cas
                ):
                    report = _run_gc_json("--retention", "--apply")

            self.assertEqual(report["retention"]["count"], 0)
            self.assertTrue(source.exists(old_name))


# ---------------------------------------------------------------------------
# 磁盘水位
# ---------------------------------------------------------------------------


class GcDiskTests(TestCase):
    def test_disk_below_watermark_passes(self):
        usage = SimpleNamespace(total=100, used=50, free=50)
        with mock.patch("shutil.disk_usage", return_value=usage):
            report = _run_gc_json("--check-disk")
        self.assertFalse(report["disk"]["exceeded"])
        self.assertEqual(report["disk"]["watermark"], 90)

    def test_disk_exceeds_watermark_raises_after_report(self):
        usage = SimpleNamespace(total=100, used=95, free=5)
        with mock.patch("shutil.disk_usage", return_value=usage):
            out = StringIO()
            with self.assertRaises(CommandError):
                call_command("skate_media_gc", "--check-disk", "--json", stdout=out)
            report = json.loads(out.getvalue())
        self.assertTrue(report["disk"]["exceeded"])
        self.assertEqual(report["disk"]["volumes"][0]["percent"], 95.0)

    def test_missing_configured_roots_probe_existing_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            usage = SimpleNamespace(total=100, used=40, free=60)
            with override_settings(
                SKATE_CLIP_SOURCE_ROOT=base / "missing" / "source",
                SKATE_CLIP_DELIVERY_ROOT=base / "missing" / "delivery",
            ):
                with mock.patch("shutil.disk_usage", return_value=usage) as disk_usage:
                    report = _run_gc_json("--check-disk")
            self.assertFalse(report["disk"]["unavailable"])
            self.assertEqual(Path(report["disk"]["volumes"][0]["probe_path"]), base)
            self.assertEqual(disk_usage.call_count, 2)


# ---------------------------------------------------------------------------
# Worker 可观测性（process_skate_clips --json）
# ---------------------------------------------------------------------------


class WorkerObservabilityTests(TestCase):
    def test_dry_run_json_summary_with_failed_grouping(self):
        _make_media(state=SkateClipMediaState.FAILED, error_code="probe_timeout")
        _make_media(state=SkateClipMediaState.FAILED, error_code="probe_timeout")
        _make_media(state=SkateClipMediaState.UPLOADED)
        out = StringIO()
        call_command("process_skate_clips", "--dry-run", "--json", stdout=out)
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["failed_total"], 2)
        self.assertEqual(summary["failed_by_error"], {"probe_timeout": 2})
        self.assertIn("duration_ms", summary)

    def test_empty_queue_json_run_processes_nothing(self):
        out = StringIO()
        call_command("process_skate_clips", "--json", stdout=out)
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["processed"], 0)
        self.assertEqual(summary["media"], [])
