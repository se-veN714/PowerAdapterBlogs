from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
import base64

from accounts.models import MyUser
from Blogs.models import Category, Post, PostRevision
from Blogs.revisions import (
    DIFF_ALGORITHM,
    build_structured_diff,
    create_revision,
    render_structured_diff,
)
from Blogs.management.commands.generate_posts import GENERATED_SLUG_PREFIX
from boards.models import Board, BoardMembership


class PublicSurfaceContractTest(TestCase):
    def test_site_root_renders_devenir_homepage(self):
        response = self.client.get(reverse("index"), HTTP_HOST="localhost:8000")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/index.html")

    def test_removed_legacy_api_stays_unreachable(self):
        response = self.client.get("/Blogs/api/")

        self.assertEqual(response.status_code, 404)


@override_settings(PUBLIC_SITE_URL="https://blog.example.test")
class PublicArchiveFeedTest(TestCase):
    def setUp(self):
        self.author = MyUser.objects.create_user(
            email="archive@example.test",
            username="archive-author",
            password="pass",
            is_active=True,
        )
        self.category = Category.objects.create(name="Archive", owner=self.author)
        self.public_post = Post.objects.create(
            title="Public archive entry",
            slug="public-archive-entry",
            desc="A public transmission.",
            content="body",
            category=self.category,
            owner=self.author,
            status=Post.STATUS_NORMAL,
            visibility=Post.VISIBILITY_PUBLIC,
        )
        self.older_public_post = Post.objects.create(
            title="Older public entry",
            slug="older-public-entry",
            desc="An older public transmission.",
            content="body",
            category=self.category,
            owner=self.author,
            status=Post.STATUS_NORMAL,
            visibility=Post.VISIBILITY_PUBLIC,
        )
        older_time = timezone.now() - timedelta(days=40)
        Post.objects.filter(pk=self.older_public_post.pk).update(created_time=older_time)
        self.older_public_post.refresh_from_db()
        Post.objects.create(
            title="Internal entry",
            slug="internal-entry",
            content="body",
            category=self.category,
            owner=self.author,
            status=Post.STATUS_NORMAL,
            visibility=Post.VISIBILITY_STAFF_ONLY,
        )
        Post.objects.create(
            title="Draft entry",
            slug="draft-entry",
            content="body",
            category=self.category,
            owner=self.author,
            status=Post.STATUS_DRAFT,
            visibility=Post.VISIBILITY_PUBLIC,
        )

    def test_public_queryset_is_the_shared_visibility_boundary(self):
        self.assertQuerySetEqual(
            Post.publicly_visible_posts().order_by("pk"),
            [self.public_post, self.older_public_post],
        )

    def test_archive_groups_public_posts_by_month_and_reuses_stream(self):
        response = self.client.get(reverse("Blogs:post_archive"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["archive_count"], 2)
        self.assertEqual(len(response.context["archive_groups"]), 2)
        self.assertContains(response, self.public_post.title)
        self.assertContains(response, self.older_public_post.title)
        self.assertNotContains(response, "Internal entry")
        self.assertNotContains(response, "Draft entry")
        self.assertTemplateUsed(response, "pages/blog/_post_stream.html")

    def test_rss_and_atom_publish_only_public_posts_with_absolute_links(self):
        for route_name in ("feed", "atom-feed"):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                content = response.content.decode("utf-8")

                self.assertEqual(response.status_code, 200)
                self.assertIn(self.public_post.title, content)
                self.assertIn(self.older_public_post.title, content)
                self.assertNotIn("Internal entry", content)
                self.assertNotIn("Draft entry", content)
                self.assertIn(
                    "https://blog.example.test/Blogs/post/public-archive-entry",
                    content,
                )

    def test_public_detail_exposes_article_metadata_from_fixed_site_url(self):
        response = self.client.get(self.public_post.get_absolute_url())

        self.assertContains(
            response,
            'rel="canonical" href="https://blog.example.test/Blogs/post/public-archive-entry"',
        )
        self.assertContains(response, 'property="og:type" content="article"')
        self.assertContains(response, 'property="og:title" content="Public archive entry"')
        self.assertContains(response, 'content="A public transmission."')
        self.assertContains(response, 'name="robots" content="index, follow"')

    def test_sitemap_uses_shared_public_queryset(self):
        response = self.client.get(reverse("sitemap"))
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("public-archive-entry", content)
        self.assertIn("older-public-entry", content)
        self.assertNotIn("internal-entry", content)
        self.assertNotIn("draft-entry", content)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class HotPostsVisibilityTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = MyUser.objects.create_user(
            email='author@example.com', username='author', password='pass', is_active=True
        )
        self.category = Category.objects.create(name='Test', owner=self.user)

    def test_public_hot_posts_never_include_staff_only_posts(self):
        public = Post.objects.create(
            title='Public', slug='public', content='body', category=self.category,
            owner=self.user, pv=10, visibility=Post.VISIBILITY_PUBLIC,
        )
        Post.objects.create(
            title='Private', slug='private', content='body', category=self.category,
            owner=self.user, pv=999, visibility=Post.VISIBILITY_STAFF_ONLY,
        )

        self.assertEqual([post.pk for post in Post.hot_posts()], [public.pk])

    def test_staff_hot_posts_use_separate_cache(self):
        Post.objects.create(
            title='Public', slug='public', content='body', category=self.category,
            owner=self.user, pv=10, visibility=Post.VISIBILITY_PUBLIC,
        )
        private = Post.objects.create(
            title='Private', slug='private', content='body', category=self.category,
            owner=self.user, pv=999, visibility=Post.VISIBILITY_STAFF_ONLY,
        )

        Post.hot_posts()
        self.assertEqual(Post.hot_posts(include_staff_only=True)[0].pk, private.pk)


class BlogSecurityTest(TestCase):
    def setUp(self):
        self.owner = MyUser.objects.create_user(
            email='owner2@example.com', username='owner2', password='pass',
            is_active=True, is_dashboard_user=True,
        )
        self.other = MyUser.objects.create_user(
            email='other2@example.com', username='other2', password='pass',
            is_active=True, is_dashboard_user=True,
        )
        category = Category.objects.create(name='Secure', owner=self.owner)
        board = Board.objects.create(slug='secure', name='Secure', category=category)
        BoardMembership.objects.create(
            board=board,
            user=self.owner,
            role=BoardMembership.Role.EDITOR,
        )
        BoardMembership.objects.create(
            board=board,
            user=self.other,
            role=BoardMembership.Role.EDITOR,
        )
        self.post = Post.objects.create(
            title='Secure Post', slug='secure-post', content='first body',
            category=category, owner=self.owner,
        )

    def test_non_owner_editor_cannot_use_frontend_edit_view(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('blogs:post_edit', kwargs={'slug': self.post.slug}))
        self.assertEqual(response.status_code, 404)

    def test_staff_only_revision_endpoints_return_404_to_anonymous_user(self):
        self.post.visibility = Post.VISIBILITY_STAFF_ONLY
        self.post.save(update_fields=['visibility'])
        revision = create_revision(self.post, self.owner, change_type='major')
        body_url = reverse(
            'blogs:revision_body', kwargs={'slug': self.post.slug, 'version': revision.version}
        )
        diff_url = reverse('blogs:revision_diff', kwargs={'slug': self.post.slug})
        self.assertEqual(self.client.get(body_url).status_code, 404)
        self.assertEqual(self.client.get(diff_url, {'from': '1.0', 'to': '1.1'}).status_code, 404)

    def test_revision_versions_increment_and_snapshots_remain_immutable(self):
        first = create_revision(self.post, self.owner, change_type='major')
        self.post.content = 'second body'
        self.post.save(update_fields=['content'])
        second = create_revision(self.post, self.owner, change_type='minor')
        first.refresh_from_db()
        self.assertEqual(first.version, '1.0')
        self.assertEqual(first.content, 'first body')
        self.assertEqual(second.version, '1.1')

    def test_image_upload_requires_csrf_and_rejects_fake_image(self):
        self.client.force_login(self.owner)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        upload_url = reverse('blogs:post_img_upload')
        fake = SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')
        self.assertEqual(csrf_client.post(upload_url, {'image': fake}).status_code, 403)

        self.client.force_login(self.owner)
        fake = SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')
        self.assertEqual(self.client.post(upload_url, {'image': fake}).status_code, 400)

    def test_valid_png_upload_uses_server_generated_filename(self):
        png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        )
        self.client.force_login(self.owner)
        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            image = SimpleUploadedFile('unsafe-name.png', png, content_type='image/png')
            response = self.client.post(reverse('blogs:post_img_upload'), {'image': image})
            self.assertEqual(response.status_code, 200)
            stored_name = response.json()['url'].rsplit('/', 1)[-1]
            self.assertNotEqual(stored_name, 'unsafe-name.png')
            self.assertTrue(Path(media_root, 'post_images', stored_name).exists())

class PostRevisionCharacterizationTest(TestCase):
    """Lock down the v2.0 revision contract before the service is refactored."""

    def setUp(self):
        self.editor = MyUser.objects.create_user(
            email='revision-editor@example.com',
            username='revision-editor',
            password='pass',
            is_active=True,
        )
        self.category = Category.objects.create(name='Revision', owner=self.editor)
        self.post = Post.objects.create(
            title='Revision title',
            desc='Revision description',
            slug='revision-contract',
            content='First sentence.\n\nSecond paragraph.',
            category=self.category,
            owner=self.editor,
        )

    def test_version_allocation_and_major_reset(self):
        first = create_revision(
            self.post,
            self.editor,
            change_type='major',
            edit_summary='Initial version',
        )
        second = create_revision(self.post, self.editor, change_type='minor')
        third = create_revision(self.post, self.editor, change_type='major')

        self.assertEqual(
            [(first.major, first.minor), (second.major, second.minor),
             (third.major, third.minor)],
            [(1, 0), (1, 1), (2, 0)],
        )
        self.assertEqual([first.version, second.version, third.version],
                         ['1.0', '1.1', '2.0'])

    def test_revision_copies_editorial_snapshot_and_metadata(self):
        revision = create_revision(
            self.post,
            self.editor,
            change_type='major',
            edit_summary='Initial version',
        )

        self.assertEqual(revision.post, self.post)
        self.assertEqual(revision.title, self.post.title)
        self.assertEqual(revision.desc, self.post.desc)
        self.assertEqual(revision.content, self.post.content)
        self.assertEqual(revision.slug, self.post.slug)
        self.assertEqual(revision.editor, self.editor)
        self.assertEqual(revision.change_type, 'major')
        self.assertEqual(revision.edit_summary, 'Initial version')
        self.assertIsNone(revision.diff_from_previous)
        self.assertIsNone(revision.diff_structured)
        self.assertEqual(revision.diff_algorithm, '')
        self.assertEqual(revision.diff_stats, {})

    def test_later_revision_stores_escaped_diff_from_previous(self):
        create_revision(self.post, self.editor, change_type='major')
        self.post.content = 'First sentence changed.\n\n<script>alert(1)</script>'
        self.post.save(update_fields=['content'])

        revision = create_revision(self.post, self.editor, change_type='minor')

        self.assertIn('<table class="diff"', revision.diff_from_previous)
        self.assertIn('&lt;script&gt;', revision.diff_from_previous)
        self.assertNotIn('<script>', revision.diff_from_previous)

    def test_later_revision_stores_markdown_aware_structured_diff(self):
        create_revision(self.post, self.editor, change_type='major')
        self.post.content = (
            '# 标题\n\n第一句话已修改。Second sentence changed!\n\n'
            '```python\nprint("safe")\n```'
        )
        self.post.save(update_fields=['content'])

        revision = create_revision(self.post, self.editor, change_type='minor')

        self.assertEqual(revision.diff_algorithm, DIFF_ALGORITHM)
        self.assertEqual(revision.diff_structured['schema_version'], 1)
        self.assertEqual(revision.diff_structured['algorithm'], DIFF_ALGORITHM)
        self.assertEqual(revision.diff_structured['stats'], revision.diff_stats)
        self.assertGreater(len(revision.diff_structured['blocks']), 0)
        self.assertGreater(revision.diff_stats['inserted_chars'], 0)
        self.assertGreater(revision.diff_stats['deleted_chars'], 0)

    def test_structured_diff_renderer_escapes_snapshot_content(self):
        diff_data = build_structured_diff(
            'Safe sentence.',
            '<script>alert(1)</script>。',
            '1.0',
            '1.1',
        )

        rendered = str(render_structured_diff(diff_data))

        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('structured-diff', rendered)

    def test_structured_diff_renderer_supports_r4_modes(self):
        diff_data = build_structured_diff(
            'Old sentence.', 'New sentence!', '1.0', '2.0',
        )

        split = str(render_structured_diff(diff_data, mode='split'))
        inline = str(render_structured_diff(diff_data, mode='inline'))
        stats = str(render_structured_diff(diff_data, mode='stats'))

        self.assertIn('structured-diff-split', split)
        self.assertIn('structured-diff-old', split)
        self.assertIn('structured-diff-inline', inline)
        self.assertIn('<del', inline)
        self.assertIn('<ins', inline)
        self.assertIn('structured-diff-stats', stats)
        self.assertNotIn('Old sentence', stats)

    def test_diff_endpoint_prefers_structured_data_over_legacy_html(self):
        first = create_revision(self.post, self.editor, change_type='major')
        self.post.content = 'Second structured version.'
        self.post.save(update_fields=['content'])
        second = create_revision(self.post, self.editor, change_type='minor')
        second.diff_from_previous = '<p>LEGACY_ONLY_SENTINEL</p>'
        second.save(update_fields=['diff_from_previous'])

        response = self.client.get(
            reverse('blogs:revision_diff', kwargs={'slug': self.post.slug}),
            {'from': first.version, 'to': second.version},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'structured-diff')
        self.assertNotContains(response, 'LEGACY_ONLY_SENTINEL')

    def test_diff_endpoint_falls_back_to_legacy_html_for_old_revision(self):
        first = create_revision(self.post, self.editor, change_type='major')
        self.post.content = 'Second legacy version.'
        self.post.save(update_fields=['content'])
        second = create_revision(self.post, self.editor, change_type='minor')
        second.diff_structured = None
        second.diff_algorithm = ''
        second.diff_stats = {}
        second.diff_from_previous = '<p>LEGACY_FALLBACK_SENTINEL</p>'
        second.save(update_fields=[
            'diff_structured', 'diff_algorithm', 'diff_stats',
            'diff_from_previous',
        ])

        response = self.client.get(
            reverse('blogs:revision_diff', kwargs={'slug': self.post.slug}),
            {'from': first.version, 'to': second.version},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LEGACY_FALLBACK_SENTINEL')

    def test_backfill_diffs_adds_structured_data_without_replacing_legacy_html(self):
        create_revision(self.post, self.editor, change_type='major')
        self.post.content = 'A legacy revision waiting for structured data.'
        self.post.save(update_fields=['content'])
        revision = create_revision(self.post, self.editor, change_type='minor')
        legacy_html = revision.diff_from_previous
        revision.diff_structured = None
        revision.diff_algorithm = ''
        revision.diff_stats = {}
        revision.save(update_fields=[
            'diff_structured', 'diff_algorithm', 'diff_stats',
        ])

        call_command('backfill_diffs', stdout=StringIO())
        revision.refresh_from_db()

        self.assertEqual(revision.diff_from_previous, legacy_html)
        self.assertEqual(revision.diff_algorithm, DIFF_ALGORITHM)
        self.assertEqual(revision.diff_structured['schema_version'], 1)
        self.assertEqual(revision.diff_stats, revision.diff_structured['stats'])

    def test_diff_endpoint_accepts_any_forward_revision_pair(self):
        first = create_revision(self.post, self.editor, change_type='major')
        self.post.content = 'Second version.'
        self.post.save(update_fields=['content'])
        second = create_revision(self.post, self.editor, change_type='minor')
        self.post.content = 'Third version.'
        self.post.save(update_fields=['content'])
        third = create_revision(self.post, self.editor, change_type='minor')
        url = reverse('blogs:revision_diff', kwargs={'slug': self.post.slug})

        adjacent = self.client.get(
            url, {'from': second.version, 'to': third.version}
        )
        non_adjacent = self.client.get(
            url, {'from': first.version, 'to': third.version}
        )

        self.assertEqual(adjacent.status_code, 200)
        self.assertContains(adjacent, f'v{second.version}')
        self.assertContains(adjacent, f'v{third.version}')
        self.assertEqual(non_adjacent.status_code, 200)
        self.assertContains(non_adjacent, 'structured-diff-split')

    def test_diff_endpoint_supports_modes_and_rejects_invalid_direction(self):
        first = create_revision(self.post, self.editor, change_type='major')
        self.post.content = 'Second version for display modes.'
        self.post.save(update_fields=['content'])
        second = create_revision(self.post, self.editor, change_type='minor')
        url = reverse('blogs:revision_diff', kwargs={'slug': self.post.slug})

        inline = self.client.get(
            url,
            {'from': first.version, 'to': second.version, 'mode': 'inline'},
        )
        stats = self.client.get(
            url,
            {'from': first.version, 'to': second.version, 'mode': 'stats'},
        )
        reverse_order = self.client.get(
            url,
            {'from': second.version, 'to': first.version},
        )
        invalid_mode = self.client.get(
            url,
            {'from': first.version, 'to': second.version, 'mode': 'raw'},
        )

        self.assertEqual(inline.status_code, 200)
        self.assertContains(inline, 'structured-diff-inline')
        self.assertEqual(stats.status_code, 200)
        self.assertContains(stats, 'structured-diff-stats')
        self.assertEqual(reverse_order.status_code, 400)
        self.assertEqual(invalid_mode.status_code, 400)

    def test_post_detail_exposes_server_rendered_version_compare_form(self):
        first = create_revision(self.post, self.editor, change_type='major')
        self.post.content = 'Second version for the selector.'
        self.post.save(update_fields=['content'])
        second = create_revision(self.post, self.editor, change_type='minor')

        response = self.client.get(
            reverse('blogs:post_detail', kwargs={'slug': self.post.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'revision-compare-form')
        self.assertContains(response, f'value="{first.version}"')
        self.assertContains(response, f'value="{second.version}"')
        self.assertContains(response, 'name="mode"')

    def test_revision_body_rejects_malformed_version(self):
        response = self.client.get(
            reverse(
                'blogs:revision_body',
                kwargs={'slug': self.post.slug, 'version': 'not-a-version'},
            )
        )

        self.assertEqual(response.status_code, 400)

    def test_database_rejects_duplicate_version_for_same_post(self):
        create_revision(self.post, self.editor, change_type='major')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PostRevision.objects.create(
                    post=self.post,
                    major=1,
                    minor=0,
                    title=self.post.title,
                    desc=self.post.desc,
                    content=self.post.content,
                    slug=self.post.slug,
                    editor=self.editor,
                    change_type='major',
                )

    def test_revision_type_must_be_supported(self):
        with self.assertRaises(ValidationError):
            create_revision(self.post, self.editor, change_type='typo')

        self.assertFalse(self.post.revisions.exists())


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'post-list-category-tests',
    },
    'sessions': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'post-list-category-session-tests',
    },
})
class PostListCategoryContextTest(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = MyUser.objects.create_user(
            email='category-owner@example.com',
            username='category-owner',
            password='pass',
            is_active=True,
        )
        self.viewer = MyUser.objects.create_user(
            email='category-viewer@example.com',
            username='category-viewer',
            password='pass',
            is_active=True,
        )
        self.public_category = Category.objects.create(
            name='Beta',
            owner=self.owner,
        )
        self.deleted_category = Category.objects.create(
            name='Deleted',
            owner=self.owner,
            status=Category.STATUS_DELETE,
        )
        self.internal_category = Category.objects.create(
            name='Alpha',
            owner=self.owner,
        )
        self.empty_category = Category.objects.create(
            name='Empty',
            owner=self.owner,
        )
        internal_board = Board.objects.create(
            slug='internal-category',
            name='Internal category',
            category=self.internal_category,
        )
        BoardMembership.objects.create(
            board=internal_board,
            user=self.viewer,
            role=BoardMembership.Role.REVIEWER,
        )
        Post.objects.create(
            title='Public post',
            slug='public-category-post',
            content='body',
            category=self.public_category,
            owner=self.owner,
        )
        Post.objects.create(
            title='Deleted category post',
            slug='deleted-category-post',
            content='body',
            category=self.deleted_category,
            owner=self.owner,
        )
        Post.objects.create(
            title='Internal post',
            slug='internal-category-post',
            content='body',
            category=self.internal_category,
            owner=self.owner,
            visibility=Post.VISIBILITY_STAFF_ONLY,
        )

    @staticmethod
    def category_names(response):
        return [category.name for category in response.context['categories']]

    def test_anonymous_context_contains_only_normal_categories_with_visible_posts(self):
        response = self.client.get(reverse('blogs:post_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.category_names(response), ['Beta'])

    def test_authorized_context_includes_internal_category_in_stable_order(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('blogs:post_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.category_names(response), ['Alpha', 'Beta'])


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'post-stream-htmx-tests',
    },
    'sessions': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'post-stream-htmx-session-tests',
    },
})
class PostStreamHtmxTest(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = MyUser.objects.create_user(
            email='stream-owner@example.com',
            username='stream-owner',
            password='pass',
            is_active=True,
        )
        self.category = Category.objects.create(
            name='Coding',
            owner=self.owner,
        )
        self.other_category = Category.objects.create(
            name='Music',
            owner=self.owner,
        )
        self.matching_post = Post.objects.create(
            title='Rhizome needle',
            slug='rhizome-needle',
            desc='Searchable stream entry',
            content='body',
            category=self.category,
            owner=self.owner,
        )
        self.other_post = Post.objects.create(
            title='Other transmission',
            slug='other-transmission',
            content='body',
            category=self.other_category,
            owner=self.owner,
        )

    def test_category_full_page_uses_shared_post_stream(self):
        response = self.client.get(
            reverse('blogs:category_list', kwargs={'category_id': self.category.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/blog/cate_list.html')
        self.assertTemplateUsed(response, 'pages/blog/_post_browser.html')
        self.assertContains(response, 'id="post-browser"')
        self.assertContains(response, 'class="stream-node')
        self.assertContains(response, self.matching_post.title)
        self.assertNotContains(response, self.other_post.title)
        self.assertNotContains(response, 'class="post-card"')
        self.assertEqual(response.context['category'], self.category)
        self.assertEqual(list(response.context['post_list']), [self.matching_post])

    def test_htmx_category_returns_fragment_and_does_not_poison_full_page_cache(self):
        url = reverse(
            'blogs:category_list',
            kwargs={'category_id': self.category.pk},
        )

        full_response = self.client.get(url)
        fragment_response = self.client.get(url, HTTP_HX_REQUEST='true')
        cached_full_response = self.client.get(url)

        self.assertContains(full_response, '<!DOCTYPE html>')
        self.assertNotContains(fragment_response, '<!DOCTYPE html>')
        self.assertTemplateUsed(fragment_response, 'pages/blog/_post_browser.html')
        self.assertContains(fragment_response, 'hx-swap-oob="innerHTML"')
        self.assertContains(fragment_response, 'id="post-browser"')
        self.assertContains(fragment_response, 'aria-hidden="true"')
        self.assertContains(cached_full_response, '<!DOCTYPE html>')
        self.assertIn('HX-Request', fragment_response.headers.get('Vary', ''))

    def test_search_full_page_and_htmx_fragment_share_latest_stream(self):
        url = reverse('blogs:search')

        full_response = self.client.get(url, {'keyword': 'needle'})
        fragment_response = self.client.get(
            url,
            {'keyword': 'needle'},
            HTTP_HX_REQUEST='true',
        )

        for response in (full_response, fragment_response):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.matching_post.title)
            self.assertNotContains(response, self.other_post.title)
            self.assertContains(response, 'STREAM:')
            self.assertContains(response, 'SEARCH')
            self.assertNotContains(response, 'class="post-card"')

        self.assertTemplateUsed(full_response, 'pages/blog/search_result.html')
        self.assertTemplateUsed(fragment_response, 'pages/blog/_post_browser.html')
        self.assertContains(fragment_response, 'data-document-title="搜索：needle"')

    def test_deleted_category_url_returns_404(self):
        deleted_category = Category.objects.create(
            name='Deleted stream',
            owner=self.owner,
            status=Category.STATUS_DELETE,
        )

        response = self.client.get(
            reverse(
                'blogs:category_list',
                kwargs={'category_id': deleted_category.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_htmx_search_pagination_preserves_query_and_global_node_number(self):
        for index in range(10):
            Post.objects.create(
                title=f'Needle transmission {index}',
                slug=f'needle-transmission-{index}',
                content='body',
                category=self.category,
                owner=self.owner,
            )

        response = self.client.get(
            reverse('blogs:search'),
            {'keyword': 'needle', 'page': 2},
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-node-index="11"')
        self.assertContains(response, 'keyword=needle&amp;page=1')
        self.assertEqual(
            response.context['stream_pagination']['pages'][1]['url'],
            '/Blogs/search/?keyword=needle&page=2',
        )
        self.assertEqual(response.context['page_obj'].number, 2)


@override_settings(DEBUG=True)
class GeneratePostsCommandTest(TestCase):
    def setUp(self):
        self.superuser = MyUser.objects.create_superuser(
            email='generate-owner@example.com',
            username='generate-owner',
            password='pass',
        )
        self.valid_category = Category.objects.create(
            name='Valid',
            owner=self.superuser,
        )
        Board.objects.create(
            slug='valid-generate-board',
            name='Valid generate board',
            category=self.valid_category,
        )

    def run_command(self, **options):
        stdout = StringIO()
        call_command('generate_posts', stdout=stdout, **options)
        return stdout.getvalue()

    def test_clear_removes_only_posts_created_by_command(self):
        real_post = Post.objects.create(
            title='Real post',
            slug='real-post',
            content='body',
            category=self.valid_category,
            owner=self.superuser,
        )
        old_generated_post = Post.objects.create(
            title='Old generated post',
            slug=f'{GENERATED_SLUG_PREFIX}old',
            content='body',
            category=self.valid_category,
            owner=self.superuser,
        )

        self.run_command(count=2, clear=True)

        self.assertTrue(Post.objects.filter(pk=real_post.pk).exists())
        self.assertFalse(Post.objects.filter(pk=old_generated_post.pk).exists())
        self.assertEqual(
            Post.objects.filter(slug__startswith=GENERATED_SLUG_PREFIX).count(),
            2,
        )

    def test_generation_uses_only_normal_categories_with_one_active_board(self):
        deleted_category = Category.objects.create(
            name='Deleted',
            owner=self.superuser,
            status=Category.STATUS_DELETE,
        )
        Board.objects.create(
            slug='deleted-generate-board',
            name='Deleted generate board',
            category=deleted_category,
        )
        ambiguous_category = Category.objects.create(
            name='Ambiguous',
            owner=self.superuser,
        )
        Board.objects.create(
            slug='ambiguous-generate-board-a',
            name='Ambiguous generate board A',
            category=ambiguous_category,
        )
        Board.objects.create(
            slug='ambiguous-generate-board-b',
            name='Ambiguous generate board B',
            category=ambiguous_category,
        )
        inactive_category = Category.objects.create(
            name='Inactive',
            owner=self.superuser,
        )
        Board.objects.create(
            slug='inactive-generate-board',
            name='Inactive generate board',
            category=inactive_category,
            is_active=False,
        )

        self.run_command(count=3)

        generated_categories = set(
            Post.objects.filter(slug__startswith=GENERATED_SLUG_PREFIX)
            .values_list('category_id', flat=True)
        )
        self.assertEqual(generated_categories, {self.valid_category.pk})

    def test_failed_preconditions_do_not_clear_existing_generated_posts(self):
        Board.objects.filter(category=self.valid_category).update(is_active=False)
        generated_post = Post.objects.create(
            title='Generated post',
            slug=f'{GENERATED_SLUG_PREFIX}keep',
            content='body',
            category=self.valid_category,
            owner=self.superuser,
        )

        with self.assertRaises(CommandError):
            self.run_command(count=1, clear=True)

        self.assertTrue(Post.objects.filter(pk=generated_post.pk).exists())

    def test_negative_count_is_rejected_without_deleting_data(self):
        generated_post = Post.objects.create(
            title='Generated post',
            slug=f'{GENERATED_SLUG_PREFIX}negative',
            content='body',
            category=self.valid_category,
            owner=self.superuser,
        )

        with self.assertRaises(CommandError):
            self.run_command(count=-1, clear=True)

        self.assertTrue(Post.objects.filter(pk=generated_post.pk).exists())

    @override_settings(DEBUG=False)
    def test_command_is_rejected_outside_debug_without_deleting_data(self):
        generated_post = Post.objects.create(
            title='Generated post',
            slug=f'{GENERATED_SLUG_PREFIX}production',
            content='body',
            category=self.valid_category,
            owner=self.superuser,
        )

        with self.assertRaises(CommandError):
            self.run_command(count=1, clear=True)

        self.assertTrue(Post.objects.filter(pk=generated_post.pk).exists())
