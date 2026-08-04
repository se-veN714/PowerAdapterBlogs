import logging
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import ClientCertificateBinding
from boards.models import (
    Board,
    BoardAccessRequest,
    BoardMembership,
    BoardMembershipEvent,
)
from boards.membership_step_up import (
    MANAGE_MEMBERSHIP_PERMISSION,
    consume_membership_step_up,
)
from boards.policies import can_manage_board_members

logger = logging.getLogger(__name__)

MANAGER_GRANTABLE_ROLES = {
    BoardMembership.Role.CONTRIBUTOR,
    BoardMembership.Role.EDITOR,
    BoardMembership.Role.REVIEWER,
}
MEMBERSHIP_ACTION_GRANT = "grant"
MEMBERSHIP_ACTION_CHANGE_ROLE = "change_role"
MEMBERSHIP_ACTION_DEACTIVATE = "deactivate"
MEMBERSHIP_ACTION_REACTIVATE = "reactivate"
MEMBERSHIP_ACTION_TRANSFER_MANAGER = "transfer_manager"
MEMBERSHIP_ACTION_BREAK_GLASS_DEACTIVATE = "break_glass_deactivate"


def _is_active_authenticated(user):
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
    )


def _validated_role(role):
    valid_roles = {value for value, _label in BoardMembership.Role.choices}
    if role not in valid_roles:
        raise ValidationError("未知的板块角色。")
    return role


def submit_board_access_request(*, applicant, board: Board, requested_role, reason=""):
    """Create one pending request without granting any Board capability."""
    if not _is_active_authenticated(applicant):
        raise PermissionDenied("账号未登录或已停用。")
    if not applicant.has_perm("boards.apply_board_access"):
        raise PermissionDenied("当前账号没有申请板块权限的资格。")
    if not board.is_active:
        raise ValidationError("该板块当前不可申请。")

    requested_role = _validated_role(requested_role)
    current = BoardMembership.objects.filter(board=board, user=applicant).first()
    if current and current.is_active and current.role == requested_role:
        raise ValidationError("你已经拥有该板块的相同角色。")

    try:
        with transaction.atomic():
            return BoardAccessRequest.objects.create(
                board=board,
                applicant=applicant,
                requested_role=requested_role,
                reason=reason.strip(),
            )
    except IntegrityError as exc:
        raise ValidationError("该板块已有一条待审核申请，请勿重复提交。") from exc


def can_review_board_access_request(*, actor, access_request):
    if not _is_active_authenticated(actor) or actor.pk == access_request.applicant_id:
        return False
    if actor.is_superuser:
        return True
    return (
        access_request.requested_role in MANAGER_GRANTABLE_ROLES
        and can_manage_board_members(actor, access_request.board)
    )


def _audit_decision(access_request_id):
    """Best-effort Mongo audit after the relational transaction commits."""
    try:
        from security.mongo_client import MongoLogger

        access_request = BoardAccessRequest.objects.select_related(
            "board", "applicant", "reviewed_by"
        ).get(pk=access_request_id)
        MongoLogger().insert_log(
            action="board_access_decision",
            data={
                "request_id": access_request.pk,
                "board_id": access_request.board_id,
                "board": access_request.board.slug,
                "applicant_id": access_request.applicant_id,
                "applicant": access_request.applicant.username,
                "actor_id": access_request.reviewed_by_id,
                "actor": access_request.reviewed_by.username,
                "previous_role": access_request.previous_role or None,
                "requested_role": access_request.requested_role,
                "result": access_request.status,
            },
        )
    except Exception:
        logger.warning(
            "Board access audit log failed for request_id=%s",
            access_request_id,
            exc_info=True,
        )


def _audit_membership_event(event_id):
    """Best-effort HMAC mirror after the relational event has committed."""
    try:
        from security.mongo_client import MongoLogger

        event = BoardMembershipEvent.objects.select_related("access_request").get(
            pk=event_id
        )
        MongoLogger().insert_log(
            action="board_membership_event",
            data={
                "event_id": event.pk,
                "event_type": event.event_type,
                "source": event.source,
                "membership_id": event.membership_id,
                "board_id": event.board_id_snapshot,
                "board": event.board_slug_snapshot,
                "user_id": event.user_id_snapshot,
                "user": event.username_snapshot,
                "actor_id": event.actor_id_snapshot,
                "actor": event.actor_username_snapshot,
                "previous_role": event.previous_role or None,
                "new_role": event.new_role or None,
                "previous_is_active": event.previous_is_active,
                "new_is_active": event.new_is_active,
                "access_request_id": event.access_request_id,
            },
        )
    except Exception:
        logger.warning(
            "Board membership event audit failed for event_id=%s",
            event_id,
            exc_info=True,
        )


def _transition_event_type(*, membership, target_role, target_is_active):
    if membership is None:
        if not target_is_active:
            raise ValidationError("不存在的板块成员关系不能直接停用。")
        return BoardMembershipEvent.EventType.GRANTED
    if not membership.is_active and target_is_active:
        return BoardMembershipEvent.EventType.REACTIVATED
    if membership.is_active and not target_is_active:
        return BoardMembershipEvent.EventType.DEACTIVATED
    if membership.role != target_role:
        return BoardMembershipEvent.EventType.ROLE_CHANGED
    raise ValidationError("板块成员关系没有发生变化。")


def _assert_manager_continuity(*, membership, target_role, target_is_active, source):
    removes_manager = bool(
        membership is not None
        and membership.is_active
        and membership.role == BoardMembership.Role.MANAGER
        and (
            not target_is_active
            or target_role != BoardMembership.Role.MANAGER
        )
    )
    if not removes_manager or source == BoardMembershipEvent.Source.SUPER_ADMIN:
        return
    active_manager_ids = list(
        BoardMembership.objects.select_for_update()
        .filter(
            board_id=membership.board_id,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
        )
        .values_list("pk", flat=True)
    )
    if len(active_manager_ids) <= 1:
        raise ValidationError(
            "不能移除最后一名 Manager，请先使用 Manager 交接。"
        )


def _transition_board_membership(
    *,
    board,
    user,
    actor,
    target_role,
    target_is_active,
    source,
    reason="",
    access_request=None,
    membership=None,
    event_type_override=None,
):
    """Apply one locked Membership transition and append its relational event.

    The caller must already be inside ``transaction.atomic()``. Authorization
    remains the responsibility of the public workflow service; this helper
    centralizes state, pending-request and audit invariants only.
    """
    target_role = _validated_role(target_role)
    if target_is_active and (not board.is_active or not user.is_active):
        raise ValidationError("板块或目标用户已停用，不能授予或恢复权限。")
    if user.is_superuser:
        raise ValidationError("superuser 通过全局应急路径访问板块，不建立 Membership。")

    pending_requests = BoardAccessRequest.objects.select_for_update().filter(
        board_id=board.pk,
        applicant_id=user.pk,
        status=BoardAccessRequest.Status.PENDING,
    )
    if access_request is not None:
        pending_requests = pending_requests.exclude(pk=access_request.pk)
    if list(pending_requests.values_list("pk", flat=True)):
        raise ValidationError("该用户在此板块仍有待审核申请，请先处理申请。")

    if membership is None:
        membership = (
            BoardMembership.objects.select_for_update()
            .filter(board_id=board.pk, user_id=user.pk)
            .first()
        )

    _assert_manager_continuity(
        membership=membership,
        target_role=target_role,
        target_is_active=target_is_active,
        source=source,
    )

    previous_role = membership.role if membership else ""
    previous_is_active = membership.is_active if membership else None
    event_type = event_type_override or _transition_event_type(
        membership=membership,
        target_role=target_role,
        target_is_active=target_is_active,
    )

    if membership is None:
        membership = BoardMembership.objects.create(
            board=board,
            user=user,
            role=target_role,
            is_active=target_is_active,
            created_by=actor,
        )
    else:
        membership.role = target_role
        membership.is_active = target_is_active
        membership.updated_at = timezone.now()
        membership.save(update_fields=["role", "is_active", "updated_at"])

    event = BoardMembershipEvent.objects.create(
        membership=membership,
        board=board,
        user=user,
        actor=actor,
        access_request=access_request,
        event_type=event_type,
        source=source,
        previous_role=previous_role,
        new_role=target_role,
        previous_is_active=previous_is_active,
        new_is_active=target_is_active,
        reason=reason.strip(),
        board_id_snapshot=board.pk,
        board_slug_snapshot=board.slug,
        user_id_snapshot=user.pk,
        username_snapshot=user.username,
        actor_id_snapshot=getattr(actor, "pk", None),
        actor_username_snapshot=getattr(actor, "username", ""),
    )
    return membership, event


def _required_reason(reason):
    value = str(reason or "").strip()
    if not value:
        raise ValidationError("请填写本次成员权限变更原因。")
    return value


def _require_dashboard_membership_actor(actor):
    if not _is_active_authenticated(actor):
        raise PermissionDenied("账号未登录或已停用。")
    if not (actor.is_dashboard_user or actor.is_superuser):
        raise PermissionDenied("当前账号不能进入站长工作台。")
    if not actor.has_perm(MANAGE_MEMBERSHIP_PERMISSION):
        raise PermissionDenied("当前账号没有全站板块成员管理权限。")


def membership_step_up_target(
    *,
    action,
    membership_id=None,
    board_id=None,
    user_id=None,
    extra="",
):
    if membership_id is not None:
        base = f"membership:{int(membership_id)}"
    else:
        base = f"board:{int(board_id)}:user:{int(user_id)}"
    return f"{action}:{base}:{extra}"


def _consume_dashboard_step_up(*, request, capability, actor, action, target):
    _require_dashboard_membership_actor(actor)
    consume_membership_step_up(
        request=request,
        capability=capability,
        actor=actor,
        action=action,
        target=target,
    )


def _schedule_membership_event_audit(event):
    transaction.on_commit(
        lambda event_id=event.pk: _audit_membership_event(event_id)
    )


def require_membership_break_glass_context(*, request, actor):
    """Require the complete mTLS + password + TOTP super-admin context."""
    from accounts.authn.mfa_session import privileged_session_is_valid

    if not (
        settings.MFA_ENFORCEMENT_ENABLED
        and settings.MTLS_ENFORCEMENT_ENABLED
    ):
        raise PermissionDenied("Membership break-glass 仅在 MFA 与 mTLS 均强制时可用。")
    if not _is_active_authenticated(actor) or not actor.is_superuser:
        raise PermissionDenied("只有 active superuser 可以执行 break-glass。")
    binding = getattr(request, "client_certificate_binding", None)
    if (
        binding is None
        or binding.user_id != actor.pk
        or binding.status != ClientCertificateBinding.Status.ACTIVE
        or binding.expires_at <= timezone.now()
    ):
        raise PermissionDenied("当前请求没有有效且匹配账号的客户端证书绑定。")
    if not privileged_session_is_valid(request, require_certificate=True):
        raise PermissionDenied("当前全验证 privileged Session 无效。")
    return binding


def membership_break_glass_confirmation(membership):
    return f"DEACTIVATE {membership.board.slug} {membership.user.username}"


def membership_break_glass_target(*, membership, binding):
    return membership_step_up_target(
        action=MEMBERSHIP_ACTION_BREAK_GLASS_DEACTIVATE,
        membership_id=membership.pk,
        extra=f"certificate:{binding.pk}:{binding.auth_version}",
    )


def _reject_pending_membership_request(*, board_id, user_id):
    if (
        BoardAccessRequest.objects.select_for_update()
        .filter(
            board_id=board_id,
            applicant_id=user_id,
            status=BoardAccessRequest.Status.PENDING,
        )
        .exists()
    ):
        raise ValidationError("该用户仍有待审核的板块权限申请，请先完成审核。")


def grant_board_membership(
    *,
    request,
    actor,
    board,
    user,
    role,
    reason,
    capability,
):
    """Directly grant one Membership from the verified Dashboard workflow."""
    reason = _required_reason(reason)
    with transaction.atomic():
        locked_board = Board.objects.select_for_update().get(pk=board.pk)
        user_model = get_user_model()
        locked_user = user_model.objects.select_for_update().get(pk=user.pk)
        _reject_pending_membership_request(
            board_id=locked_board.pk,
            user_id=locked_user.pk,
        )
        if BoardMembership.objects.select_for_update().filter(
            board_id=locked_board.pk,
            user_id=locked_user.pk,
        ).exists():
            raise ValidationError("该用户已有板块成员记录，请使用调整或恢复操作。")
        target = membership_step_up_target(
            action=MEMBERSHIP_ACTION_GRANT,
            board_id=locked_board.pk,
            user_id=locked_user.pk,
        )
        _consume_dashboard_step_up(
            request=request,
            capability=capability,
            actor=actor,
            action=MEMBERSHIP_ACTION_GRANT,
            target=target,
        )
        membership, event = _transition_board_membership(
            board=locked_board,
            user=locked_user,
            actor=actor,
            target_role=role,
            target_is_active=True,
            source=BoardMembershipEvent.Source.DASHBOARD,
            reason=reason,
        )
        _schedule_membership_event_audit(event)
        return membership


def change_board_membership_role(
    *, request, actor, membership, role, reason, capability
):
    reason = _required_reason(reason)
    membership_id = getattr(membership, "pk", membership)
    with transaction.atomic():
        locked = (
            BoardMembership.objects.select_for_update()
            .select_related("board", "user")
            .get(pk=membership_id)
        )
        if not locked.is_active:
            raise ValidationError("停用的成员关系必须使用恢复操作。")
        _reject_pending_membership_request(
            board_id=locked.board_id,
            user_id=locked.user_id,
        )
        if locked.role == role:
            raise ValidationError("板块成员角色没有发生变化。")
        _assert_manager_continuity(
            membership=locked,
            target_role=role,
            target_is_active=True,
            source=BoardMembershipEvent.Source.DASHBOARD,
        )
        target = membership_step_up_target(
            action=MEMBERSHIP_ACTION_CHANGE_ROLE,
            membership_id=locked.pk,
        )
        _consume_dashboard_step_up(
            request=request,
            capability=capability,
            actor=actor,
            action=MEMBERSHIP_ACTION_CHANGE_ROLE,
            target=target,
        )
        locked, event = _transition_board_membership(
            board=locked.board,
            user=locked.user,
            actor=actor,
            target_role=role,
            target_is_active=True,
            source=BoardMembershipEvent.Source.DASHBOARD,
            reason=reason,
            membership=locked,
        )
        _schedule_membership_event_audit(event)
        return locked


def deactivate_board_membership(
    *, request, actor, membership, reason, capability
):
    reason = _required_reason(reason)
    membership_id = getattr(membership, "pk", membership)
    with transaction.atomic():
        locked = (
            BoardMembership.objects.select_for_update()
            .select_related("board", "user")
            .get(pk=membership_id)
        )
        if not locked.is_active:
            raise ValidationError("当前成员关系已经停用。")
        _reject_pending_membership_request(
            board_id=locked.board_id,
            user_id=locked.user_id,
        )
        _assert_manager_continuity(
            membership=locked,
            target_role=locked.role,
            target_is_active=False,
            source=BoardMembershipEvent.Source.DASHBOARD,
        )
        target = membership_step_up_target(
            action=MEMBERSHIP_ACTION_DEACTIVATE,
            membership_id=locked.pk,
        )
        _consume_dashboard_step_up(
            request=request,
            capability=capability,
            actor=actor,
            action=MEMBERSHIP_ACTION_DEACTIVATE,
            target=target,
        )
        locked, event = _transition_board_membership(
            board=locked.board,
            user=locked.user,
            actor=actor,
            target_role=locked.role,
            target_is_active=False,
            source=BoardMembershipEvent.Source.DASHBOARD,
            reason=reason,
            membership=locked,
        )
        _schedule_membership_event_audit(event)
        return locked


def reactivate_board_membership(
    *, request, actor, membership, role, reason, capability
):
    reason = _required_reason(reason)
    membership_id = getattr(membership, "pk", membership)
    with transaction.atomic():
        locked = (
            BoardMembership.objects.select_for_update()
            .select_related("board", "user")
            .get(pk=membership_id)
        )
        if locked.is_active:
            raise ValidationError("当前成员关系仍处于启用状态。")
        _reject_pending_membership_request(
            board_id=locked.board_id,
            user_id=locked.user_id,
        )
        target = membership_step_up_target(
            action=MEMBERSHIP_ACTION_REACTIVATE,
            membership_id=locked.pk,
        )
        _consume_dashboard_step_up(
            request=request,
            capability=capability,
            actor=actor,
            action=MEMBERSHIP_ACTION_REACTIVATE,
            target=target,
        )
        locked, event = _transition_board_membership(
            board=locked.board,
            user=locked.user,
            actor=actor,
            target_role=role,
            target_is_active=True,
            source=BoardMembershipEvent.Source.DASHBOARD,
            reason=reason,
            membership=locked,
        )
        _schedule_membership_event_audit(event)
        return locked


def transfer_board_manager(
    *,
    request,
    actor,
    membership,
    target_user,
    old_disposition,
    reason,
    capability,
):
    """Promote the replacement before demoting/deactivating the old Manager."""
    reason = _required_reason(reason)
    allowed_dispositions = {
        "deactivate",
        BoardMembership.Role.CONTRIBUTOR,
        BoardMembership.Role.EDITOR,
        BoardMembership.Role.REVIEWER,
    }
    if old_disposition not in allowed_dispositions:
        raise ValidationError("未知的 Manager 交接后状态。")
    membership_id = getattr(membership, "pk", membership)
    with transaction.atomic():
        old = (
            BoardMembership.objects.select_for_update()
            .select_related("board", "user")
            .get(pk=membership_id)
        )
        if not old.is_active or old.role != BoardMembership.Role.MANAGER:
            raise ValidationError("只有有效 Manager 可以执行交接。")
        user_model = get_user_model()
        replacement_user = user_model.objects.select_for_update().get(
            pk=target_user.pk
        )
        _reject_pending_membership_request(
            board_id=old.board_id,
            user_id=old.user_id,
        )
        _reject_pending_membership_request(
            board_id=old.board_id,
            user_id=replacement_user.pk,
        )
        if replacement_user.pk == old.user_id:
            raise ValidationError("Manager 不能交接给自己。")
        replacement = (
            BoardMembership.objects.select_for_update()
            .filter(board_id=old.board_id, user_id=replacement_user.pk)
            .first()
        )
        if (
            replacement is not None
            and replacement.is_active
            and replacement.role == BoardMembership.Role.MANAGER
        ):
            raise ValidationError("目标用户已是有效 Manager，可直接停用原 Manager。")
        target = membership_step_up_target(
            action=MEMBERSHIP_ACTION_TRANSFER_MANAGER,
            membership_id=old.pk,
            extra=f"to:{replacement_user.pk}:{old_disposition}",
        )
        _consume_dashboard_step_up(
            request=request,
            capability=capability,
            actor=actor,
            action=MEMBERSHIP_ACTION_TRANSFER_MANAGER,
            target=target,
        )
        replacement, replacement_event = _transition_board_membership(
            board=old.board,
            user=replacement_user,
            actor=actor,
            target_role=BoardMembership.Role.MANAGER,
            target_is_active=True,
            source=BoardMembershipEvent.Source.DASHBOARD,
            reason=reason,
            membership=replacement,
            event_type_override=BoardMembershipEvent.EventType.MANAGER_TRANSFERRED,
        )
        old_role = old.role if old_disposition == "deactivate" else old_disposition
        old, old_event = _transition_board_membership(
            board=old.board,
            user=old.user,
            actor=actor,
            target_role=old_role,
            target_is_active=old_disposition != "deactivate",
            source=BoardMembershipEvent.Source.DASHBOARD,
            reason=reason,
            membership=old,
            event_type_override=BoardMembershipEvent.EventType.MANAGER_TRANSFERRED,
        )
        _schedule_membership_event_audit(replacement_event)
        _schedule_membership_event_audit(old_event)
        return replacement, old


def break_glass_deactivate_last_manager(
    *,
    request,
    actor,
    membership,
    reason,
    confirmation,
    capability,
):
    """Deactivate the final Manager only under the fully verified SU path."""
    reason = _required_reason(reason)
    membership_id = getattr(membership, "pk", membership)
    with transaction.atomic():
        binding = require_membership_break_glass_context(
            request=request,
            actor=actor,
        )
        binding = ClientCertificateBinding.objects.select_for_update().get(
            pk=binding.pk,
            user=actor,
            status=ClientCertificateBinding.Status.ACTIVE,
            expires_at__gt=timezone.now(),
        )
        locked = (
            BoardMembership.objects.select_for_update()
            .select_related("board", "user")
            .get(pk=membership_id)
        )
        expected_confirmation = membership_break_glass_confirmation(locked)
        if not secrets.compare_digest(str(confirmation), expected_confirmation):
            raise ValidationError("确认短语不匹配。")
        if not locked.is_active or locked.role != BoardMembership.Role.MANAGER:
            raise ValidationError("只有当前有效 Manager 可以执行该应急停用。")
        _reject_pending_membership_request(
            board_id=locked.board_id,
            user_id=locked.user_id,
        )
        active_manager_ids = list(
            BoardMembership.objects.select_for_update()
            .filter(
                board_id=locked.board_id,
                role=BoardMembership.Role.MANAGER,
                is_active=True,
            )
            .values_list("pk", flat=True)
        )
        if len(active_manager_ids) != 1 or locked.pk not in active_manager_ids:
            raise ValidationError(
                "该 Board 仍有其他 Manager，请使用 Dashboard 正常停用或交接。"
            )
        target = membership_break_glass_target(
            membership=locked,
            binding=binding,
        )
        consume_membership_step_up(
            request=request,
            capability=capability,
            actor=actor,
            action=MEMBERSHIP_ACTION_BREAK_GLASS_DEACTIVATE,
            target=target,
        )
        locked, event = _transition_board_membership(
            board=locked.board,
            user=locked.user,
            actor=actor,
            target_role=locked.role,
            target_is_active=False,
            source=BoardMembershipEvent.Source.SUPER_ADMIN,
            reason=reason,
            membership=locked,
        )
        _schedule_membership_event_audit(event)
        return locked


def decide_board_access_request(*, access_request, actor, approve, note=""):
    """Approve/reject under row locks; approved requests update Membership atomically."""
    request_id = getattr(access_request, "pk", access_request)
    with transaction.atomic():
        locked = (
            BoardAccessRequest.objects.select_for_update()
            .select_related("board", "applicant")
            .get(pk=request_id)
        )
        if locked.status != BoardAccessRequest.Status.PENDING:
            raise ValidationError("该申请已经处理，不能重复审核。")
        if not can_review_board_access_request(actor=actor, access_request=locked):
            raise PermissionDenied("你不能审核这条板块权限申请。")
        membership = (
            BoardMembership.objects.select_for_update()
            .filter(board=locked.board, user=locked.applicant)
            .first()
        )
        if (
            not actor.is_superuser
            and membership is not None
            and (
                not membership.is_active
                or membership.role == BoardMembership.Role.MANAGER
            )
        ):
            raise PermissionDenied(
                "停用成员的权限恢复或 Manager 角色变更只能由 superuser 审核。"
            )
        locked.previous_role = membership.role if membership else ""

        if approve:
            _membership, event = _transition_board_membership(
                board=locked.board,
                user=locked.applicant,
                actor=actor,
                target_role=locked.requested_role,
                target_is_active=True,
                source=BoardMembershipEvent.Source.ACCESS_REQUEST,
                reason=note.strip() or locked.reason,
                access_request=locked,
                membership=membership,
            )
            locked.status = BoardAccessRequest.Status.APPROVED
        else:
            locked.status = BoardAccessRequest.Status.REJECTED

        locked.reviewed_by = actor
        locked.reviewed_at = timezone.now()
        locked.decision_note = note.strip()
        locked.save(
            update_fields=[
                "status",
                "previous_role",
                "reviewed_by",
                "reviewed_at",
                "decision_note",
            ]
        )
        transaction.on_commit(lambda: _audit_decision(locked.pk))
        if approve:
            transaction.on_commit(
                lambda event_id=event.pk: _audit_membership_event(event_id)
            )
        return locked


def approve_board_access_request(*, access_request, actor, note=""):
    return decide_board_access_request(
        access_request=access_request,
        actor=actor,
        approve=True,
        note=note,
    )


def reject_board_access_request(*, access_request, actor, note=""):
    return decide_board_access_request(
        access_request=access_request,
        actor=actor,
        approve=False,
        note=note,
    )


def withdraw_board_membership(*, membership, actor):
    """Deactivate one's own non-manager Membership without deleting history."""
    if not _is_active_authenticated(actor):
        raise PermissionDenied("账号未登录或已停用。")
    membership_id = getattr(membership, "pk", membership)
    with transaction.atomic():
        locked = (
            BoardMembership.objects.select_for_update()
            .select_related("board", "user")
            .get(pk=membership_id)
        )
        if locked.user_id != actor.pk:
            raise PermissionDenied("只能退出自己的板块权限。")
        if not locked.is_active:
            raise ValidationError("该板块权限已经停用。")
        if locked.role == BoardMembership.Role.MANAGER:
            raise PermissionDenied("Manager 不能自助退出，请由站长管理入口处理。")
        locked, event = _transition_board_membership(
            board=locked.board,
            user=locked.user,
            actor=actor,
            target_role=locked.role,
            target_is_active=False,
            source=BoardMembershipEvent.Source.SELF_SERVICE,
            reason="成员通过短时邮箱验证主动退出板块。",
            membership=locked,
        )
        transaction.on_commit(
            lambda event_id=event.pk: _audit_membership_event(event_id)
        )
        return locked
