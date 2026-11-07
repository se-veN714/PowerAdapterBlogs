"""PAdif module eligibility; historical requests never stand in for current grants."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.agent_auth import _audit_agent_event
from padif.permissions import can_use_padif
from .models import AgentAccessRequest, AgentQualification, Connection


def require_module(module_key):
    if module_key != 'padif':
        raise ValidationError('尚未支持该板块的 Agent。')


def lock_identity(user_id):
    # Token issuance and module decisions share this lock. They acquire it
    # before connections/documents, so revocation cannot miss a concurrent issue.
    # NO KEY UPDATE still serializes decisions/issuance, while allowing FK
    # inserts from a document transaction that may already hold its document.
    return get_user_model().objects.select_for_update(no_key=True).get(pk=user_id)


def can_use_agent(user, module_key='padif'):
    return bool(module_key == 'padif' and can_use_padif(user) and (user.is_superuser or
        AgentQualification.objects.filter(user=user, module_key=module_key, is_active=True).exists()))


def qualification_revision(user):
    if not can_use_agent(user):
        return None
    return AgentQualification.objects.filter(user=user, module_key='padif', is_active=True).values_list('revision', flat=True).first() or 0


def can_review_agents(user, module_key='padif'):
    return bool(module_key == 'padif' and user.is_authenticated and user.is_active and
        (user.is_superuser or (getattr(user, 'is_dashboard_user', False) and user.has_perm('agent_mcp.review_agent_access'))))


def _audit(event, actor, target, change):
    _audit_agent_event(event_type=event, actor=actor, target_type='agent_access', target_id=target,
        change={'module_key': 'padif', **change}, source='agent_access_review')


def validate_note(note):
    if not isinstance(note, str) or not note.strip() or len(note) > 2000:
        raise ValidationError('请填写 1–2000 字的说明。')
    return note.strip()


def finish_request(item, status, actor=None, note='', reason=''):
    if item.status != 'pending':
        raise ValidationError('申请已处理，不能重复操作。')
    item.status, item.closed_at, item.closed_by = status, timezone.now(), actor
    item.invalidated_reason = reason
    if status in {'approved', 'rejected'}:
        item.reviewed_by, item.reviewed_at, item.decision_note = actor, item.closed_at, note
    item.save()
    _audit_agent_event(event_type='agent.request.' + status, actor=actor,
        target_type=item._meta.label_lower, target_id=item.pk,
        change={'module_key': item.module_key, 'status': status, 'reason_code': reason}, source='agent_access_review')
    return item


def invalidate_pending(query, reason):
    for item in query.select_for_update().filter(status='pending').order_by('pk'):
        finish_request(item, 'invalidated', reason=reason)


@transaction.atomic
def submit_agent_request(user, reason='', module_key='padif'):
    require_module(module_key)
    user = lock_identity(user.pk)
    if not can_use_padif(user):
        raise PermissionDenied('请先获得 PAdif 使用权限。')
    if can_use_agent(user, module_key):
        raise ValidationError('当前账号已开通 PAdif Agent，无需重复申请。')
    # Module selection is the application. Preserve optional historical purpose
    # text, without inventing it or requiring free text for a supported module.
    if not isinstance(reason, str) or len(reason) > 2000:
        raise ValidationError('申请说明不能超过 2000 字。')
    reason = reason.strip()
    try:
        with transaction.atomic():
            item = AgentAccessRequest.objects.create(applicant=user, module_key=module_key, reason=reason)
            _audit('agent.access.requested', user, item.pk, {'status': 'pending'})
            return item
    except IntegrityError as error:
        raise ValidationError('已有待审核申请，请勿重复提交。') from error


@transaction.atomic
def decide_agent_request(request_id, actor, approve, note):
    initial = get_object_or_404(AgentAccessRequest, pk=request_id, module_key='padif')
    applicant = lock_identity(initial.applicant_id)
    list(AgentQualification.objects.select_for_update().filter(user=applicant, module_key='padif'))
    item = AgentAccessRequest.objects.select_for_update().get(pk=request_id)
    if not can_review_agents(actor, item.module_key) or actor.pk == item.applicant_id:
        raise PermissionDenied('不能审核这条 PAdif Agent 申请。')
    if item.status != 'pending':
        raise ValidationError('申请已处理，不能重复审核。')
    note = validate_note(note)
    if not can_use_padif(applicant):
        return finish_request(item, 'invalidated', reason='padif_access_lost')
    if approve:
        grant, created = AgentQualification.objects.select_for_update().get_or_create(user=applicant, module_key=item.module_key)
        if not grant.is_active:
            grant.is_active, grant.revoked_at = True, None
            if not created:
                grant.revision += 1
        grant.management_note, grant.managed_by = note, actor
        grant.save()
    finish_request(item, 'approved' if approve else 'rejected', actor, note)
    _audit('agent.access.decided', actor, item.pk, {'status': item.status, 'applicant_id': item.applicant_id})
    return item


@transaction.atomic
def revoke_agent_qualification(user_id, actor, note, module_key='padif', *, expected_revision=None):
    require_module(module_key)
    if not can_review_agents(actor, module_key) or actor.pk == user_id:
        raise PermissionDenied('不能撤销此账号的 PAdif Agent 资格。')
    note = validate_note(note)
    target = lock_identity(user_id)
    if target.is_superuser:
        raise ValidationError('超级管理员使用系统内置资格，不能在此撤销。')
    connections = list(Connection.objects.select_for_update().filter(user_id=user_id,
        module_key=module_key, revoked_at__isnull=True).order_by('pk'))
    from padif.models import Document, DocumentAgentGrant, DocumentAgentRequest
    ids = Document.objects.filter(Q(created_by_id=user_id) | Q(collaborators__user_id=user_id) |
        Q(agent_grants__user_id=user_id) | Q(agent_requests__applicant_id=user_id)).values('pk')
    list(Document.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    grant = AgentQualification.objects.select_for_update().filter(user_id=user_id, module_key=module_key, is_active=True).first()
    if grant is None:
        raise ValidationError('此账号没有有效的 PAdif Agent 资格。')
    if expected_revision is not None:
        _check_qualification_revision(grant, expected_revision)
    grant.management_note, grant.managed_by = note, actor
    grant.is_active, grant.revoked_at = False, timezone.now()
    grant.revision += 1
    grant.save()
    for ai in DocumentAgentGrant.objects.select_for_update().filter(user_id=user_id, is_enabled=True):
        ai.is_enabled, ai.revoked_at = False, grant.revoked_at
        ai.allowed_operations = []
        ai.revision += 1
        ai.save()
    invalidate_pending(DocumentAgentRequest.objects.filter(applicant_id=user_id, module_key=module_key), 'module_revoked')
    from .oauth import revoke_connection
    from accounts.agent_auth import revoke_agent_access_tokens
    from accounts.models import AgentAccessToken, AgentDeviceAuthorization
    for connection in connections:
        revoke_connection(connection, actor, 'agent.mcp.qualification_revoked')
    padif_scope = Q(scopes__contains=['padif:read']) | Q(scopes__contains=['padif:annotate']) | Q(scopes__contains=['padif:version'])
    revoke_agent_access_tokens(token_ids=AgentAccessToken.objects.filter(padif_scope, user_id=user_id).values_list('pk', flat=True),
        actor=actor, source='agent_access_review', reason='qualification_revoked')
    AgentDeviceAuthorization.objects.filter(padif_scope, user_id=user_id, status='approved').update(status='denied', denied_at=timezone.now())
    _audit('agent.access.revoked', actor, user_id, {'status': 'revoked', 'reason': note})


@transaction.atomic
def withdraw_agent_request(request_id, actor):
    lock_identity(actor.pk)
    item = get_object_or_404(AgentAccessRequest.objects.select_for_update(), pk=request_id, applicant=actor, module_key='padif')
    return finish_request(item, 'withdrawn', actor)


def _management_target(user_id, actor, module_key):
    require_module(module_key)
    if not can_review_agents(actor, module_key) or actor.pk == user_id:
        raise PermissionDenied('不能管理此账号的 PAdif Agent 资格。')
    target = get_object_or_404(get_user_model().objects.select_for_update(no_key=True), pk=user_id)
    if target.is_superuser:
        raise ValidationError('超级管理员使用系统内置资格，不能在此修改。')
    return target


def _check_qualification_revision(grant, expected_revision):
    if type(expected_revision) is not int or expected_revision != (grant.revision if grant else 0):
        raise ValidationError('资格状态已变化，请刷新后重试。')


@transaction.atomic
def grant_agent_qualification(user_id, actor, note, *, expected_revision, module_key='padif'):
    target = _management_target(user_id, actor, module_key)
    note = validate_note(note)
    if not can_use_padif(target):
        raise ValidationError('该账号未启用或没有 PAdif 使用能力，请先在账号权限管理中处理。')
    grant = AgentQualification.objects.select_for_update().filter(user=target, module_key=module_key).first()
    _check_qualification_revision(grant, expected_revision)
    if grant and grant.is_active:
        raise ValidationError('该账号已开通，请使用修改说明或撤销操作。')
    pending = AgentAccessRequest.objects.select_for_update().filter(applicant=target, module_key=module_key, status='pending').first()
    if pending:
        decide_agent_request(pending.pk, actor, True, note)
        grant = AgentQualification.objects.get(user=target, module_key=module_key)
    elif grant:
        grant.is_active, grant.revoked_at = True, None
        grant.revision += 1
    else:
        grant = AgentQualification(user=target, module_key=module_key, is_active=True)
    grant.management_note, grant.managed_by = note, actor
    grant.save()
    _audit('agent.access.granted', actor, target.pk, {'user_id': target.pk, 'revision': grant.revision,
        'source': 'request' if pending else 'dashboard_direct', 'request_id': pending.pk if pending else None, 'reason': note})
    return grant


@transaction.atomic
def update_agent_qualification(user_id, actor, note, *, expected_revision, module_key='padif'):
    target = _management_target(user_id, actor, module_key)
    note = validate_note(note)
    grant = get_object_or_404(AgentQualification.objects.select_for_update(), user=target, module_key=module_key)
    _check_qualification_revision(grant, expected_revision)
    if grant.management_note == note:
        return grant
    previous = grant.management_note
    grant.management_note, grant.managed_by = note, actor
    grant.save(update_fields=['management_note', 'managed_by', 'updated_at'])
    # Editing metadata must not change the eligibility cycle or invalidate article approvals.
    _audit('agent.access.updated', actor, target.pk, {'user_id': target.pk, 'revision': grant.revision,
        'previous_note': previous, 'reason': note})
    return grant
