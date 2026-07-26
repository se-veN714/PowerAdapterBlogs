import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from boards.models import Board, BoardAccessRequest, BoardMembership
from boards.policies import can_manage_board_members

logger = logging.getLogger(__name__)

MANAGER_GRANTABLE_ROLES = {
    BoardMembership.Role.CONTRIBUTOR,
    BoardMembership.Role.EDITOR,
    BoardMembership.Role.REVIEWER,
}


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
        if approve and (not locked.board.is_active or not locked.applicant.is_active):
            raise ValidationError("板块或申请人已停用，不能批准该申请。")

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
            if membership is None:
                BoardMembership.objects.create(
                    board=locked.board,
                    user=locked.applicant,
                    role=locked.requested_role,
                    is_active=True,
                    created_by=actor,
                )
            else:
                membership.role = locked.requested_role
                membership.is_active = True
                membership.save(update_fields=["role", "is_active"])
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
