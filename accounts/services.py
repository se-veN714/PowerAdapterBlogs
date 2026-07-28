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
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.utils.crypto import constant_time_compare, salted_hmac
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import AccountInvitation

logger = logging.getLogger(__name__)


@transaction.atomic
def set_account_active_state(*, actor, target, is_active: bool):
    """Enable or disable a regular account through the scoped review surface."""
    if not actor.is_active or not (
        actor.is_superuser or actor.has_perm("accounts.manage_user_accounts")
    ):
        raise PermissionDenied("当前账号没有用户审核权限。")
    if target.is_superuser or target.is_dashboard_user or target.is_staff:
        raise ValidationError("特权账号只能由超级用户在系统后台中管理。")
    if actor.pk == target.pk:
        raise ValidationError("不能在审核中心停用自己的账号。")
    if is_active and AccountInvitation.objects.filter(
        user=target,
        accepted_at__isnull=True,
    ).exists():
        raise ValidationError("该账号尚未完成邮箱邀请，不能绕过邀请流程直接启用。")
    if target.is_active == is_active:
        return target

    locked = type(target).objects.select_for_update().get(pk=target.pk)
    locked.is_active = is_active
    locked.save(update_fields=("is_active",))
    LogEntry.objects.log_action(
        user_id=actor.pk,
        content_type_id=ContentType.objects.get_for_model(locked).pk,
        object_id=str(locked.pk),
        object_repr=str(locked),
        action_flag=CHANGE,
        change_message=f"moderation_center account_active={is_active}",
    )
    return locked

PASSWORD_CODE_SENT = "sent"
PASSWORD_CODE_COOLDOWN = "cooldown"
PASSWORD_CODE_SEND_LIMIT = "send_limit"
PASSWORD_CODE_SEND_FAILED = "send_failed"
PASSWORD_CODE_INVALID = "invalid"
PASSWORD_CODE_EXPIRED = "expired"
PASSWORD_CODE_LOCKED = "locked"
PASSWORD_CODE_VERIFIED = "verified"
PASSWORD_EMAIL_VERIFIED_SESSION_KEY = "password_email_verified"
BOARD_ACCESS_EMAIL_VERIFIED_SESSION_KEY = "board_access_email_verified"
EMAIL_PURPOSE_PASSWORD_CHANGE = "password_change"
EMAIL_PURPOSE_BOARD_ACCESS = "board_access"

EMAIL_VERIFICATION_PURPOSES = {
    EMAIL_PURPOSE_PASSWORD_CHANGE: {
        "hmac_salt": "accounts.password-change-email",
        "subject": "PowerAdapter 修改密码验证码",
        "text_template": "emails/accounts/password_change_code.txt",
        "html_template": "emails/accounts/password_change_code.html",
        "session_key": PASSWORD_EMAIL_VERIFIED_SESSION_KEY,
    },
    EMAIL_PURPOSE_BOARD_ACCESS: {
        "hmac_salt": "accounts.board-access-email",
        "subject": "PowerAdapter 板块权限申请验证码",
        "text_template": "emails/accounts/board_access_code.txt",
        "html_template": "emails/accounts/board_access_code.html",
        "session_key": BOARD_ACCESS_EMAIL_VERIFIED_SESSION_KEY,
    },
}


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


def _email_code_identity(user_id, session_key, purpose):
    raw = f"{purpose}:{user_id}:{session_key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _email_code_key(user_id, session_key, purpose, suffix):
    identity = _email_code_identity(user_id, session_key, purpose)
    return f"account-email:{purpose}:{suffix}:{identity}"


def _email_user_key(user_id, suffix):
    digest = hashlib.sha256(str(user_id).encode("ascii")).hexdigest()
    return f"account-email:{suffix}:{digest}"


def _email_purpose_config(purpose):
    try:
        return EMAIL_VERIFICATION_PURPOSES[purpose]
    except KeyError as exc:
        raise ValueError("Unsupported email verification purpose") from exc


def _increment_cache_counter(key, timeout):
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return 1


def email_verification_code_pending(user_id, session_key, purpose):
    if not session_key:
        return False
    _email_purpose_config(purpose)
    return cache.get(_email_code_key(user_id, session_key, purpose, "code")) is not None


def _deadline_remaining_seconds(deadline):
    try:
        remaining = float(deadline) - timezone.now().timestamp()
    except (TypeError, ValueError):
        return 0
    return max(0, math.ceil(remaining))


def email_verification_resend_remaining_seconds(user_id):
    deadline = cache.get(_email_user_key(user_id, "cooldown"))
    return _deadline_remaining_seconds(deadline)


def email_verification_code_remaining_seconds(user_id, session_key, purpose):
    if not session_key:
        return 0
    _email_purpose_config(purpose)
    deadline = cache.get(_email_code_key(user_id, session_key, purpose, "expires"))
    return _deadline_remaining_seconds(deadline)


def issue_email_verification_code(user, session_key, purpose):
    """发送 purpose 隔离的短时验证码；冷却和小时上限按账号共享。"""
    config = _email_purpose_config(purpose)
    cooldown = settings.PASSWORD_EMAIL_SEND_COOLDOWN_SECONDS
    cooldown_key = _email_user_key(user.pk, "cooldown")
    cooldown_deadline = timezone.now().timestamp() + cooldown
    if not cache.add(cooldown_key, cooldown_deadline, timeout=cooldown):
        return PASSWORD_CODE_COOLDOWN

    send_window = settings.PASSWORD_EMAIL_SEND_WINDOW_SECONDS
    send_count = _increment_cache_counter(
        _email_user_key(user.pk, "send-count"),
        send_window,
    )
    if send_count > settings.PASSWORD_EMAIL_MAX_SENDS:
        return PASSWORD_CODE_SEND_LIMIT

    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = salted_hmac(
        config["hmac_salt"],
        f"{purpose}:{user.pk}:{session_key}:{code}",
    ).hexdigest()
    ttl = settings.PASSWORD_EMAIL_CODE_TTL_SECONDS
    cache.set(
        _email_code_key(user.pk, session_key, purpose, "code"),
        digest,
        timeout=ttl,
    )
    cache.set(
        _email_code_key(user.pk, session_key, purpose, "expires"),
        timezone.now().timestamp() + ttl,
        timeout=ttl,
    )
    cache.delete(_email_code_key(user.pk, session_key, purpose, "attempts"))

    context = {"user": user, "code": code, "ttl_minutes": max(1, ttl // 60)}
    message = EmailMultiAlternatives(
        subject=config["subject"],
        body=render_to_string(config["text_template"], context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(
        render_to_string(config["html_template"], context),
        "text/html",
    )
    try:
        message.send(fail_silently=False)
    except Exception:
        cache.delete_many(
            (
                _email_code_key(user.pk, session_key, purpose, "code"),
                _email_code_key(user.pk, session_key, purpose, "expires"),
            )
        )
        logger.exception("邮箱验证码发送失败: user_id=%s purpose=%s", user.pk, purpose)
        return PASSWORD_CODE_SEND_FAILED
    logger.info("邮箱验证码已发送: user_id=%s purpose=%s", user.pk, purpose)
    return PASSWORD_CODE_SENT


def verify_email_verification_code(user, session_key, purpose, code):
    """校验 purpose + 用户 + Session 绑定的验证码；不记录验证码明文。"""
    config = _email_purpose_config(purpose)
    code_key = _email_code_key(user.pk, session_key, purpose, "code")
    expected_digest = cache.get(code_key)
    if expected_digest is None:
        return PASSWORD_CODE_EXPIRED

    attempts_key = _email_code_key(user.pk, session_key, purpose, "attempts")
    attempts = _increment_cache_counter(
        attempts_key,
        settings.PASSWORD_EMAIL_CODE_TTL_SECONDS,
    )
    submitted_digest = salted_hmac(
        config["hmac_salt"],
        f"{purpose}:{user.pk}:{session_key}:{code}",
    ).hexdigest()
    if constant_time_compare(expected_digest, submitted_digest):
        cache.delete_many(
            (
                code_key,
                attempts_key,
                _email_code_key(user.pk, session_key, purpose, "expires"),
            )
        )
        return PASSWORD_CODE_VERIFIED
    if attempts >= settings.PASSWORD_EMAIL_MAX_ATTEMPTS:
        cache.delete_many(
            (
                code_key,
                _email_code_key(user.pk, session_key, purpose, "expires"),
            )
        )
        logger.warning(
            "邮箱验证码尝试次数耗尽: user_id=%s purpose=%s",
            user.pk,
            purpose,
        )
        return PASSWORD_CODE_LOCKED
    return PASSWORD_CODE_INVALID


def mark_email_verification_verified(request, purpose):
    config = _email_purpose_config(purpose)
    request.session[config["session_key"]] = {
        "user_id": request.user.pk,
        "purpose": purpose,
        "verified_at": timezone.now().timestamp(),
    }


def email_verification_is_verified(request, purpose):
    return email_verification_remaining_seconds(request, purpose) > 0


def email_verification_remaining_seconds(request, purpose):
    config = _email_purpose_config(purpose)
    verification = request.session.get(config["session_key"])
    if (
        not isinstance(verification, dict)
        or verification.get("user_id") != request.user.pk
        or verification.get("purpose", purpose) != purpose
    ):
        return 0
    try:
        age = timezone.now().timestamp() - float(verification["verified_at"])
    except (KeyError, TypeError, ValueError):
        return 0
    if age < 0 or age > settings.PASSWORD_EMAIL_VERIFIED_TTL_SECONDS:
        request.session.pop(config["session_key"], None)
        return 0
    return max(0, math.ceil(settings.PASSWORD_EMAIL_VERIFIED_TTL_SECONDS - age))


def clear_email_verification(request, purpose):
    config = _email_purpose_config(purpose)
    request.session.pop(config["session_key"], None)


# Password-change compatibility API. Existing callers and session migrations keep working.
def password_change_code_pending(user_id, session_key):
    return email_verification_code_pending(
        user_id, session_key, EMAIL_PURPOSE_PASSWORD_CHANGE
    )


def password_change_resend_remaining_seconds(user_id):
    return email_verification_resend_remaining_seconds(user_id)


def password_change_code_remaining_seconds(user_id, session_key):
    return email_verification_code_remaining_seconds(
        user_id, session_key, EMAIL_PURPOSE_PASSWORD_CHANGE
    )


def issue_password_change_email_code(user, session_key):
    return issue_email_verification_code(
        user, session_key, EMAIL_PURPOSE_PASSWORD_CHANGE
    )


def verify_password_change_email_code(user, session_key, code):
    return verify_email_verification_code(
        user, session_key, EMAIL_PURPOSE_PASSWORD_CHANGE, code
    )


def mark_password_email_verified(request):
    mark_email_verification_verified(request, EMAIL_PURPOSE_PASSWORD_CHANGE)


def password_email_is_verified(request):
    return email_verification_is_verified(request, EMAIL_PURPOSE_PASSWORD_CHANGE)


def password_email_verification_remaining_seconds(request):
    return email_verification_remaining_seconds(
        request, EMAIL_PURPOSE_PASSWORD_CHANGE
    )


def clear_password_email_verification(request):
    clear_email_verification(request, EMAIL_PURPOSE_PASSWORD_CHANGE)
