"""账号邀请与邮件发送服务。"""

import hashlib
import logging
import secrets
from datetime import timedelta
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import AccountInvitation

logger = logging.getLogger(__name__)


def invitation_token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_account_invitation_email(invitation_id, token):
    invitation = AccountInvitation.objects.select_related("user").get(pk=invitation_id)
    activation_path = reverse("accounts:accept-invitation", kwargs={"token": token})
    activation_url = urljoin(settings.PUBLIC_SITE_URL.rstrip("/") + "/", activation_path.lstrip("/"))
    context = {
        "user": invitation.user,
        "activation_url": activation_url,
        "expires_at": invitation.expires_at,
    }
    subject = "PowerAdapter 账号邀请"
    text_body = render_to_string("emails/accounts/account_invitation.txt", context)
    html_body = render_to_string("emails/accounts/account_invitation.html", context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[invitation.user.email],
    )
    message.attach_alternative(html_body, "text/html")
    try:
        sent = message.send(fail_silently=False)
    except Exception:
        logger.exception("账号邀请邮件发送失败: user_id=%s", invitation.user_id)
        return
    if sent:
        AccountInvitation.objects.filter(pk=invitation.pk).update(sent_at=timezone.now())
        logger.info("账号邀请邮件已发送: user_id=%s", invitation.user_id)


def issue_account_invitation(user, *, created_by=None):
    """创建或替换一次性邀请，并在当前事务成功提交后发送邮件。"""
    if user.is_active:
        raise ValueError("只能为未激活账号发送邀请")

    token = secrets.token_urlsafe(32)
    lifetime = timedelta(seconds=settings.ACCOUNT_INVITATION_TTL_SECONDS)
    invitation, _ = AccountInvitation.objects.update_or_create(
        user=user,
        defaults={
            "created_by": created_by,
            "token_digest": invitation_token_digest(token),
            "expires_at": timezone.now() + lifetime,
            "sent_at": None,
            "accepted_at": None,
        },
    )
    transaction.on_commit(
        lambda: _send_account_invitation_email(invitation.pk, token),
        robust=True,
    )
    return invitation, token


def accept_account_invitation(token, password, *, expected_invitation_id):
    """原子消费邀请、设置密码、激活账号并加入基础验证组。"""
    digest = invitation_token_digest(token)
    now = timezone.now()
    with transaction.atomic():
        invitation = (
            AccountInvitation.objects.select_for_update()
            .select_related("user")
            .filter(token_digest=digest)
            .first()
        )
        if (
            invitation is None
            or invitation.pk != expected_invitation_id
            or invitation.accepted_at is not None
            or invitation.expires_at <= now
            or invitation.user.is_active
        ):
            return None

        user = invitation.user
        user.set_password(password)
        user.is_active = True
        user.save(update_fields=("password", "is_active"))
        verified_group, _ = Group.objects.get_or_create(
            name=settings.ACCOUNT_VERIFIED_GROUP_NAME
        )
        user.groups.add(verified_group)
        invitation.accepted_at = now
        invitation.save(update_fields=("accepted_at",))
        logger.info("账号邀请已接受: user_id=%s", user.pk)
        return user
