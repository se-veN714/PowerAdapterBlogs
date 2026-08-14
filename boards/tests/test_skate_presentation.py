"""SK8 S3 测试：Presentation——Index 焦点预览消费 ready 派生资源。

验证：
- assemble_skateboard / prepare_skate_clips 为 ready media 附加 main_url/preview_url/poster_url
- 非 ready media 不附加 URL（模板回退到旧字段）
- SkateClipListView 的 clips 也通过 prepare_skate_clips 附加 URL
- 模板渲染优先使用派生 URL
"""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from boards.board_index import prepare_skate_clips
from boards.models import (
    Board,
    SkateClip,
    SkateClipMedia,
    SkateClipMediaState,
    SkateClipOrientation,
    SkateHomie,
    skate_delivery_storage,
)


def _make_board_and_homie():
    board, _ = Board.objects.get_or_create(slug="skateboard", name="Skateboard")
    homie = SkateHomie.objects.create(
        board=board,
        node_index=SkateHomie.objects.count() + 1,
        name="Tester",
        joined_at="2026-08-01",
    )
    return board, homie


def _make_clip(homie, **overrides):
    defaults = dict(homie=homie, order=0, title="Ollie", is_public=True)
    defaults.update(overrides)
    return SkateClip.objects.create(**defaults)


def _make_ready_media(clip, **overrides):
    defaults = dict(state=SkateClipMediaState.READY)
    defaults.update(overrides)
    return SkateClipMedia.objects.create(clip=clip, **defaults)


class AttachMediaUrlsTests(TestCase):
    """prepare_skate_clips 为 clip 附加 ready media 派生 URL。"""

    def test_ready_media_urls_attached(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(SKATE_CLIP_DELIVERY_ROOT=Path(tmp)):
                _, homie = _make_board_and_homie()
                clip = _make_clip(homie)
                delivery = skate_delivery_storage()
                media = _make_ready_media(clip)
                main_key = f"delivery/{media.media_key}/main.webm"
                preview_key = f"preview/{media.media_key}/preview.webm"
                poster_key = f"poster/{media.media_key}.webp"
                delivery.save(main_key, ContentFile(b"main"))
                delivery.save(preview_key, ContentFile(b"preview"))
                delivery.save(poster_key, ContentFile(b"poster"))
                media.main_file = main_key
                media.preview_file = preview_key
                media.poster_file = poster_key
                media.save()

                prepare_skate_clips([clip])

                self.assertTrue(clip.main_url)
                self.assertTrue(clip.preview_url)
                self.assertTrue(clip.poster_url)
                self.assertIn("main.webm", clip.main_url)
                self.assertIn("preview.webm", clip.preview_url)
                self.assertIn(str(media.media_key), clip.poster_url)

    def test_non_ready_media_urls_empty(self):
        _, homie = _make_board_and_homie()
        clip = _make_clip(homie)
        _make_ready_media(clip, state=SkateClipMediaState.UPLOADED)

        prepare_skate_clips([clip])

        self.assertEqual(clip.main_url, "")
        self.assertEqual(clip.preview_url, "")
        self.assertEqual(clip.poster_url, "")

    def test_groups_follow_probed_orientation_not_input_position(self):
        _, homie = _make_board_and_homie()
        clips = [_make_clip(homie, order=index, title=f"Clip {index}") for index in range(5)]
        orientations = (
            SkateClipOrientation.LANDSCAPE,
            SkateClipOrientation.PORTRAIT,
            SkateClipOrientation.LANDSCAPE,
            SkateClipOrientation.PORTRAIT,
            SkateClipOrientation.SQUARE,
        )
        for clip, orientation in zip(clips, orientations, strict=True):
            _make_ready_media(clip, orientation=orientation)

        groups = prepare_skate_clips(clips)

        self.assertEqual([clip.pk for clip in groups[0]["vertical"]], [clips[1].pk, clips[3].pk])
        self.assertEqual(
            [clip.pk for clip in groups[0]["horizontal"]],
            [clips[0].pk, clips[2].pk, clips[4].pk],
        )

    def test_known_landscape_is_not_forced_into_portrait_slot(self):
        _, homie = _make_board_and_homie()
        clips = [_make_clip(homie, order=index, title=f"Wide {index}") for index in range(4)]
        for clip in clips:
            _make_ready_media(clip, orientation=SkateClipOrientation.LANDSCAPE)

        groups = prepare_skate_clips(clips)

        self.assertEqual(groups[0]["vertical"], [])
        self.assertEqual(len(groups[0]["horizontal"]), 3)
        self.assertEqual(len(groups[1]["horizontal"]), 1)

    def test_legacy_unknown_orientation_keeps_two_plus_three_fallback(self):
        _, homie = _make_board_and_homie()
        clips = [_make_clip(homie, order=index, title=f"Legacy {index}") for index in range(5)]

        groups = prepare_skate_clips(clips)

        self.assertEqual(groups[0]["vertical"], clips[:2])
        self.assertEqual(groups[0]["horizontal"], clips[2:])

    def test_no_media_urls_empty(self):
        _, homie = _make_board_and_homie()
        clip = _make_clip(homie)

        prepare_skate_clips([clip])

        self.assertEqual(clip.main_url, "")
        self.assertEqual(clip.preview_url, "")
        self.assertEqual(clip.poster_url, "")

    def test_failed_media_urls_empty(self):
        _, homie = _make_board_and_homie()
        clip = _make_clip(homie)
        _make_ready_media(clip, state=SkateClipMediaState.FAILED)

        prepare_skate_clips([clip])

        self.assertEqual(clip.main_url, "")


class SkateboardIndexRenderingTests(TestCase):
    """Index 页面渲染时 ready media 的派生 URL 出现在 HTML 中。"""

    def test_ready_clip_renders_main_url_in_video_source(self):
        from django.urls import reverse

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(SKATE_CLIP_DELIVERY_ROOT=Path(tmp)):
                board, _ = Board.objects.get_or_create(slug="skateboard", name="Skateboard")
                board.is_active = True
                board.save()
                homie = SkateHomie.objects.create(
                    board=board, node_index=1, name="Tester", joined_at="2026-08-01",
                )
                clip = SkateClip.objects.create(
                    homie=homie, order=0, title="Ollie", is_public=True,
                )
                delivery = skate_delivery_storage()
                media = SkateClipMedia.objects.create(
                    clip=clip, state=SkateClipMediaState.READY,
                )
                main_key = f"delivery/{media.media_key}/main.webm"
                poster_key = f"poster/{media.media_key}.webp"
                preview_key = f"preview/{media.media_key}/preview.webm"
                delivery.save(main_key, ContentFile(b"main"))
                delivery.save(poster_key, ContentFile(b"poster"))
                delivery.save(preview_key, ContentFile(b"preview"))
                media.main_file = main_key
                media.poster_file = poster_key
                media.preview_file = preview_key
                media.save()

                response = self.client.get(reverse("boards:index", args=["skateboard"]))

                self.assertEqual(response.status_code, 200)
                content = response.content.decode()
                # main_url 出现在 <source src="...">
                self.assertIn("main.webm", content)
                # poster_url 出现在 poster="..."
                self.assertIn(str(media.media_key), content)
                self.assertIn("poster/", content)
                # preview_url 出现在 data-skate-preview="..."
                self.assertIn("preview.webm", content)
                self.assertIn("data-skate-preview", content)
                self.assertIn(f'id="sk-media-{clip.pk}"', content)
                self.assertIn(f'data-skate-watch="sk-media-{clip.pk}"', content)
                self.assertIn("data-skate-main", content)

    def test_clip_without_media_falls_back_to_placeholder(self):
        from django.urls import reverse

        board, _ = Board.objects.get_or_create(slug="skateboard", name="Skateboard")
        board.is_active = True
        board.save()
        homie = SkateHomie.objects.create(
            board=board, node_index=1, name="Tester", joined_at="2026-08-01",
        )
        SkateClip.objects.create(
            homie=homie, order=0, title="Ollie", is_public=True,
        )

        response = self.client.get(reverse("boards:index", args=["skateboard"]))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("sk-clip-placeholder", content)

    def test_clip_list_page_renders_poster_url(self):
        from django.urls import reverse

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(SKATE_CLIP_DELIVERY_ROOT=Path(tmp)):
                board, _ = Board.objects.get_or_create(slug="skateboard", name="Skateboard")
                board.is_active = True
                board.save()
                homie = SkateHomie.objects.create(
                    board=board, node_index=1, name="Tester", joined_at="2026-08-01",
                )
                clip = SkateClip.objects.create(
                    homie=homie, order=0, title="Ollie", is_public=True,
                    filmed_at=datetime.date(2024, 1, 1),
                )
                delivery = skate_delivery_storage()
                media = SkateClipMedia.objects.create(
                    clip=clip, state=SkateClipMediaState.READY,
                )
                poster_key = f"poster/{media.media_key}.webp"
                delivery.save(poster_key, ContentFile(b"poster"))
                media.poster_file = poster_key
                media.save()

                response = self.client.get(reverse("boards:skate-clip-list"))

                self.assertEqual(response.status_code, 200)
                content = response.content.decode()
                self.assertIn(str(media.media_key), content)
                self.assertIn("poster/", content)
