"""处理 SK8 Clip 媒体：uploaded → processing → ready/failed。

用法：
    python manage.py process_skate_clips [--limit N] [--reset-stuck]
        [--media-id ID] [--dry-run]

轻量 Worker（SKATEBOARD_GUIDE §6）：Django management command +
FFprobe/FFmpeg；不引入 Celery/Redis。可由计划任务按分钟级轮询。
多实例并发安全（select_for_update + skip_locked + claim token）。
"""

from django.core.management.base import BaseCommand, CommandError

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

    def handle(self, *args, **options):
        if options["reset_stuck"]:
            count = reset_stuck_media()
            if count:
                self.stdout.write(self.style.WARNING(f"reset stuck media: {count}"))

        pending = SkateClipMedia.objects.filter(state=SkateClipMediaState.UPLOADED).count()
        processing = SkateClipMedia.objects.filter(
            state=SkateClipMediaState.PROCESSING
        ).count()
        self.stdout.write(f"pending={pending} processing={processing}")

        if options["dry_run"]:
            return

        limit = options["limit"]
        media_id = options["media_id"]
        done = failed = 0

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
            if process_media(media):
                done += 1
            else:
                failed += 1
        else:
            processed = 0
            while (limit <= 0 or processed < limit) and (
                media := claim_next_media()
            ):
                processed += 1
                if process_media(media):
                    done += 1
                else:
                    failed += 1

        style = self.style.SUCCESS if not failed else self.style.WARNING
        self.stdout.write(style(f"processed: ready={done} failed={failed}"))
