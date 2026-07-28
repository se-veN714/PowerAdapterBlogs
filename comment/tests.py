from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from unittest.mock import patch

from accounts.models import MyUser
from Blogs.models import Category, Post
from comment.models import Comment
from security.services import moderate_comment


@override_settings(
    CACHES={
        'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
        'sessions': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    },
    COMMENT_RATE_LIMIT=2,
    COMMENT_RATE_WINDOW=60,
)
class CommentSafetyTest(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = MyUser.objects.create_user(
            email='owner@example.com', username='owner', password='pass', is_active=True
        )
        self.other = MyUser.objects.create_user(
            email='other@example.com', username='other', password='pass', is_active=True
        )
        category = Category.objects.create(name='Test', owner=self.owner)
        self.post = Post.objects.create(
            title='Post', slug='post', content='body', category=category, owner=self.owner
        )
        self.submit_url = f'/Blogs/post/{self.post.slug}/comment/'

    def test_comment_submission_is_rate_limited(self):
        self.client.force_login(self.owner)
        payload = {'content': '这是足够长的评论内容'}
        self.assertEqual(self.client.post(self.submit_url, payload).status_code, 200)
        self.assertEqual(self.client.post(self.submit_url, payload).status_code, 200)
        response = self.client.post(self.submit_url, payload)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['Retry-After'], '60')

    def test_comment_identity_comes_from_authenticated_account(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            self.submit_url,
            {
                'nickname': 'forged-anonymous-name',
                'content': '这是由登录账号提交的评论内容',
            },
        )

        self.assertEqual(response.status_code, 200)
        comment = Comment.objects.get(post=self.post)
        self.assertEqual(comment.user, self.owner)
        self.assertEqual(comment.nickname, self.owner.username)
        self.assertContains(response, self.owner.username)
        self.assertNotContains(response, 'forged-anonymous-name')

    def test_only_owner_can_soft_delete_comment(self):
        comment = Comment.objects.create(
            post=self.post, user=self.owner, nickname='Owner', content='这是足够长的评论内容',
            status=Comment.Status.PUBLISHED,
        )
        delete_url = f'/Blogs/comment/{comment.pk}/delete/'
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(delete_url).status_code, 403)

        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(delete_url).status_code, 200)
        comment.refresh_from_db()
        self.assertEqual(comment.status, Comment.Status.DELETED)

    @patch('security.services.MongoLogger')
    def test_moderation_updates_status_and_writes_hmac_audit_event(self, mongo_cls):
        comment = Comment.objects.create(
            post=self.post, user=self.owner, nickname='Owner', content='这是足够长的评论内容'
        )
        request = RequestFactory().post('/dashboard/comment/')
        request.user = self.owner
        request.client_ip = '127.0.0.1'

        moderate_comment(
            comment=comment,
            new_status=Comment.Status.PUBLISHED,
            request=request,
            reason='test',
        )

        comment.refresh_from_db()
        self.assertEqual(comment.status, Comment.Status.PUBLISHED)
        mongo_cls.return_value.insert_log.assert_called_once()
