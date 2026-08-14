"""处理 SK8 Clip 媒体：uploaded → processing → ready/failed。

用法：
    python manage.py process_skate_clips [--limit N] [--reset-stuck]
        [--media-id ID] [--dry-run] [--json]

轻量 Worker（SKATEBOARD_GUIDE §6）：Django management command +
FFprobe/FFmpeg；不引入 Celery/Redis。可由计划任务按分钟级轮询。
多实例并发安全（select_for_update + skip_locked + claim token）。

可观测性（S4）：
- 每条处理输出 media_key、结果与耗时；
- --json 输出单行 JSON 汇总（队列水位、失败按 error_code 分组、逐条耗时），
  供外部监控采集；--dry-run --json 组合可做无副作用的状态探针。
"""

from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from boards.models import SkateClipMedia, SkateClipMediaState
from boards.skate_worker import (
    claim_media_by_pk,
    claim_next_media,
    process_media,
    reset_stuck_media,
)


class Command(BaseCommand):
    help = "Process uploaded skate clip media into derived delivery assets."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="最多处理条数（0=不限）")
        parser.add_argument(
            "--reset-stuck",
            action="store_true",
            help="先把超时卡死的 processing 复位回 uploaded",
        )
        parser.add_argument("--media-id", type=int, default=0, help="只处理指定媒体行")
        parser.add_argument(
            "--dry-run", action="store_true", help="只打印待处理统计，不执行"
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="单行 JSON 汇总输出（供监控采集）",
        )

    def handle(self, *args, **options):
        started = time.monotonic()
        as_json = options["as_json"]
        reset_count = 0
        if options["reset_stuck"]:
            reset_count = reset_stuck_media()
            if reset_count and not as_json:
                self.stdout.write(self.style.WARNING(f"reset stuck media: {reset_count}"))

        pending = SkateClipMedia.objects.filter(state=SkateClipMediaState.UPLOADED).count()
        processing = SkateClipMedia.objects.filter(
            state=SkateClipMediaState.PROCESSING
        ).count()
        if not as_json:
            self.stdout.write(f"pending={pending} processing={processing}")

        summary = {
            "pending": pending,
            "processing": processing,
            "ready_total": SkateClipMedia.objects.filter(
                state=SkateClipMediaState.READY
            ).count(),
            "failed_total": SkateClipMedia.objects.filter(
                state=SkateClipMediaState.FAILED
            ).count(),
            "reset_stuck": reset_count,
            "processed": 0,
            "ok": 0,
            "failed": 0,
            "media": [],
        }
        summary["failed_by_error"] = {
            row["error_code"] or "unknown": row["n"]
            for row in SkateClipMedia.objects.filter(
                state=SkateClipMediaState.FAILED
            )
            .values("error_code")
            .annotate(n=Count("pk"))
        }

        if options["dry_run"]:
            summary["duration_ms"] = int((time.monotonic() - started) * 1000)
            if as_json:
                self.stdout.write(json.dumps(summary, ensure_ascii=False))
            else:
                failed_by_error = summary["failed_by_error"]
                if failed_by_error:
                    detail = ", ".join(
                        f"{code}={n}" for code, n in sorted(failed_by_error.items())
                    )
                    self.stdout.write(f"failed_by_error: {detail}")
                self.stdout.write("dry-run：未处理任何条目。")
            return

        limit = options["limit"]
        media_id = options["media_id"]
        done = failed = 0

        def _run(media):
            nonlocal done, failed
            item_started = time.monotonic()
            ok = process_media(media)
            elapsed_ms = int((time.monotonic() - item_started) * 1000)
            media.refresh_from_db(fields=["state", "error_code"])
            if ok:
                done += 1
            else:
                failed += 1
            entry = {
                "key": str(media.media_key),
                "state": media.state,
                "ms": elapsed_ms,
            }
            if not ok:
                entry["error"] = media.error_code or "unknown"
            summary["media"].append(entry)
            if not as_json:
                line = f"[{media.state}] {media.media_key} in {elapsed_ms}ms"
                if ok:
                    self.stdout.write(line)
                else:
                    self.stdout.write(f"{line} error={entry['error']}")

        if media_id:
            media = claim_media_by_pk(media_id)
            if media is None:
                existing = SkateClipMedia.objects.filter(pk=media_id).first()
                if existing is None:
                    raise CommandError(f"media {media_id} not found")
                raise CommandError(
                    f"media {media_id} state={existing.state} "
                    f"(expected uploaded or not claimable)"
                )
            summary["processed"] = 1
            _run(media)
        else:
            processed = 0
            while (limit <= 0 or processed < limit) and (
                media := claim_next_media()
            ):
                processed += 1
                summary["processed"] = processed
                _run(media)

        summary["ok"] = done
        summary["failed"] = failed
        summary["duration_ms"] = int((time.monotonic() - started) * 1000)
        if as_json:
            self.stdout.write(json.dumps(summary, ensure_ascii=False))
        else:
            style = self.style.SUCCESS if not failed else self.style.WARNING
            self.stdout.write(style(f"processed: ready={done} failed={failed}"))
