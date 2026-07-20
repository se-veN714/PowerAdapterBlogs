from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import base64

from accounts.models import MyUser
from Blogs.models import Category, Post, Tag
from Blogs.serializers import PostDetailSerializer
from Blogs.revisions import create_revision
from Blogs.management.commands.generate_posts import GENERATED_SLUG_PREFIX
from boards.models import Board, BoardMembership


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

    def test_post_serializer_reads_many_to_many_tags(self):
        tag = Tag.objects.create(name='Django', owner=self.owner)
        self.post.tag.add(tag)
        self.assertEqual(PostDetailSerializer(self.post).data['tags'], ['Django'])


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
