from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from pathlib import Path
from tempfile import TemporaryDirectory
import base64

from accounts.models import MyUser
from Blogs.models import Category, Post, Tag
from Blogs.serializers import PostDetailSerializer
from Blogs.revisions import create_revision


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
        self.post = Post.objects.create(
            title='Secure Post', slug='secure-post', content='first body',
            category=category, owner=self.owner,
        )

    def test_non_owner_editor_cannot_use_frontend_edit_view(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('blogs:post_edit', kwargs={'slug': self.post.slug}))
        self.assertEqual(response.status_code, 403)

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
