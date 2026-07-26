"""账号邀请与邮件发送服务。"""

import hashlib
import logging
import math
import secrets
from datetime import timedelta
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils.crypto import constant_time_compare, salted_hmac
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import AccountInvitation

logger = logging.getLogger(__name__)

PASSWORD_CODE_SENT = "sent"
PASSWORD_CODE_COOLDOWN = "cooldown"
PASSWORD_CODE_SEND_LIMIT = "send_limit"
PASSWORD_CODE_SEND_FAILED = "send_failed"
PASSWORD_CODE_INVALID = "invalid"
PASSWORD_CODE_EXPIRED = "expired"
PASSWORD_CODE_LOCKED = "locked"
PASSWORD_CODE_VERIFIED = "verified"
PASSWORD_EMAIL_VERIFIED_SESSION_KEY = "password_email_verified"


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


def _password_code_identity(user_id, session_key):
    raw = f"{user_id}:{session_key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _password_code_key(user_id, session_key, suffix):
    return f"password-email:{suffix}:{_password_code_identity(user_id, session_key)}"


def _password_user_key(user_id, suffix):
    digest = hashlib.sha256(str(user_id).encode("ascii")).hexdigest()
    return f"password-email:{suffix}:{digest}"


def _increment_cache_counter(key, timeout):
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return 1


def password_change_code_pending(user_id, session_key):
    if not session_key:
        return False
    return cache.get(_password_code_key(user_id, session_key, "code")) is not None


def _deadline_remaining_seconds(deadline):
    try:
        remaining = float(deadline) - timezone.now().timestamp()
    except (TypeError, ValueError):
        return 0
    return max(0, math.ceil(remaining))


def password_change_resend_remaining_seconds(user_id):
    deadline = cache.get(_password_user_key(user_id, "cooldown"))
    return _deadline_remaining_seconds(deadline)


def password_change_code_remaining_seconds(user_id, session_key):
    if not session_key:
        return 0
    deadline = cache.get(_password_code_key(user_id, session_key, "expires"))
    return _deadline_remaining_seconds(deadline)


def issue_password_change_email_code(user, session_key):
    """向当前账号邮箱发送短时验证码，并限制冷却与发送次数。"""
    cooldown = settings.PASSWORD_EMAIL_SEND_COOLDOWN_SECONDS
    cooldown_key = _password_user_key(user.pk, "cooldown")
    cooldown_deadline = timezone.now().timestamp() + cooldown
    if not cache.add(cooldown_key, cooldown_deadline, timeout=cooldown):
        return PASSWORD_CODE_COOLDOWN

    send_window = settings.PASSWORD_EMAIL_SEND_WINDOW_SECONDS
    send_count = _increment_cache_counter(
        _password_user_key(user.pk, "send-count"),
        send_window,
    )
    if send_count > settings.PASSWORD_EMAIL_MAX_SENDS:
        return PASSWORD_CODE_SEND_LIMIT

    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = salted_hmac(
        "accounts.password-change-email",
        f"{user.pk}:{session_key}:{code}",
    ).hexdigest()
    ttl = settings.PASSWORD_EMAIL_CODE_TTL_SECONDS
    cache.set(_password_code_key(user.pk, session_key, "code"), digest, timeout=ttl)
    cache.set(
        _password_code_key(user.pk, session_key, "expires"),
        timezone.now().timestamp() + ttl,
        timeout=ttl,
    )
    cache.delete(_password_code_key(user.pk, session_key, "attempts"))

    context = {"user": user, "code": code, "ttl_minutes": max(1, ttl // 60)}
    message = EmailMultiAlternatives(
        subject="PowerAdapter 修改密码验证码",
        body=render_to_string("emails/accounts/password_change_code.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(
        render_to_string("emails/accounts/password_change_code.html", context),
        "text/html",
    )
    try:
        message.send(fail_silently=False)
    except Exception:
        cache.delete_many(
            (
                _password_code_key(user.pk, session_key, "code"),
                _password_code_key(user.pk, session_key, "expires"),
            )
        )
        logger.exception("修改密码验证码发送失败: user_id=%s", user.pk)
        return PASSWORD_CODE_SEND_FAILED
    logger.info("修改密码验证码已发送: user_id=%s", user.pk)
    return PASSWORD_CODE_SENT


def verify_password_change_email_code(user, session_key, code):
    """校验当前 Session 的验证码；永不记录或返回验证码明文。"""
    code_key = _password_code_key(user.pk, session_key, "code")
    expected_digest = cache.get(code_key)
    if expected_digest is None:
        return PASSWORD_CODE_EXPIRED

    attempts_key = _password_code_key(user.pk, session_key, "attempts")
    attempts = _increment_cache_counter(
        attempts_key,
        settings.PASSWORD_EMAIL_CODE_TTL_SECONDS,
    )
    submitted_digest = salted_hmac(
        "accounts.password-change-email",
        f"{user.pk}:{session_key}:{code}",
    ).hexdigest()
    if constant_time_compare(expected_digest, submitted_digest):
        cache.delete_many(
            (
                code_key,
                attempts_key,
                _password_code_key(user.pk, session_key, "expires"),
            )
        )
        return PASSWORD_CODE_VERIFIED
    if attempts >= settings.PASSWORD_EMAIL_MAX_ATTEMPTS:
        cache.delete_many(
            (
                code_key,
                _password_code_key(user.pk, session_key, "expires"),
            )
        )
        logger.warning("修改密码验证码尝试次数耗尽: user_id=%s", user.pk)
        return PASSWORD_CODE_LOCKED
    return PASSWORD_CODE_INVALID


def mark_password_email_verified(request):
    request.session[PASSWORD_EMAIL_VERIFIED_SESSION_KEY] = {
        "user_id": request.user.pk,
        "verified_at": timezone.now().timestamp(),
    }


def password_email_is_verified(request):
    return password_email_verification_remaining_seconds(request) > 0


def password_email_verification_remaining_seconds(request):
    verification = request.session.get(PASSWORD_EMAIL_VERIFIED_SESSION_KEY)
    if not isinstance(verification, dict) or verification.get("user_id") != request.user.pk:
        return 0
    try:
        age = timezone.now().timestamp() - float(verification["verified_at"])
    except (KeyError, TypeError, ValueError):
        return 0
    if age < 0 or age > settings.PASSWORD_EMAIL_VERIFIED_TTL_SECONDS:
        request.session.pop(PASSWORD_EMAIL_VERIFIED_SESSION_KEY, None)
        return 0
    return max(0, math.ceil(settings.PASSWORD_EMAIL_VERIFIED_TTL_SECONDS - age))


def clear_password_email_verification(request):
    request.session.pop(PASSWORD_EMAIL_VERIFIED_SESSION_KEY, None)
