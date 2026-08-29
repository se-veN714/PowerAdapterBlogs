from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.utils import timezone

from accounts.models import MyUser
from Blogs.models import Category, Post
from comment.models import Comment
from security.models import AuditOutbox
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
        self.verifier = MyUser.objects.create_superuser(
            email="verifier@example.com",
            username="verifier",
            password="pass",
        )
        self.owner = MyUser.objects.create_user(
            email='owner@example.com',
            username='owner',
            password='pass',
            is_active=True,
            identity_verification_method=MyUser.IdentityVerificationMethod.MOBILE_PHONE,
            identity_verified_at=timezone.now(),
            identity_verified_by=self.verifier,
        )
        self.other = MyUser.objects.create_user(
            email='other@example.com',
            username='other',
            password='pass',
            is_active=True,
            identity_verification_method=MyUser.IdentityVerificationMethod.MOBILE_PHONE,
            identity_verified_at=timezone.now(),
            identity_verified_by=self.verifier,
        )
        category = Category.objects.create(name='Test', owner=self.owner)
        self.post = Post.objects.create(
            title='Post', slug='post', content='body', category=category, owner=self.owner
        )
        self.submit_url = f'/Blogs/post/{self.post.slug}/comment/'

    def test_unverified_account_cannot_submit_comment(self):
        self.owner.identity_verification_method = ""
        self.owner.identity_verified_at = None
        self.owner.save(
            update_fields=("identity_verification_method", "identity_verified_at")
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            self.submit_url,
            {"content": "这是未完成真实身份核验的评论内容"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("真实身份核验", response.json()["message"])
        self.assertFalse(Comment.objects.exists())

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
        audit_event = AuditOutbox.objects.get(event_type="comment.created")
        self.assertEqual(audit_event.event["target"]["id"], str(comment.pk))
        self.assertNotIn("content", audit_event.event["change"]["after"])
        self.assertNotIn("source_ip", audit_event.event["context"])
        self.assertNotIn("client_fingerprint", audit_event.event["context"])

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
        self.assertTrue(
            AuditOutbox.objects.filter(
                event_type="comment.deleted",
                event__target__id=str(comment.pk),
            ).exists()
        )

    def test_moderation_updates_status_and_enqueues_audit_event(self):
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
        audit_event = AuditOutbox.objects.get(event_type="comment.moderated")
        self.assertEqual(audit_event.event["target"]["id"], str(comment.pk))
        self.assertEqual(
            audit_event.event["change"]["after"]["status"],
            Comment.Status.PUBLISHED,
        )
