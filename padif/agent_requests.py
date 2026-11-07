"""Article AI+ requests and grants, always subordinate to human document access."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.agent_auth import _audit_agent_event
from agent_mcp.access import qualification_revision, validate_note, finish_request, invalidate_pending
from agent_mcp.models import AgentQualification
from .models import Document, DocumentCollaborator, DocumentAgentGrant, DocumentAgentRequest
from .permissions import require_document, document_role
from .agent_operations import READ, normalize_operations, role_operations


def role_snapshot(user, document):
    role = document_role(user, document)
    if role == 'owner':
        return role, 0
    revision = DocumentCollaborator.objects.filter(document=document, user=user, is_active=True).values_list('revision', flat=True).first()
    return role, revision


def lock_qualification(user):
    list(AgentQualification.objects.select_for_update().filter(user=user, module_key='padif'))
    return qualification_revision(user)


def request_is_current(item, user, document):
    grant = DocumentAgentGrant.objects.filter(document=document, user=user).first()
    return (document is not None and (item.role, item.role_revision) == role_snapshot(user, document)
        and qualification_revision(user) == item.qualification_revision
        and item.base_grant_revision == (grant.revision if grant else 0)
        and item.basis_operations == (grant.allowed_operations if grant else []))


def _audit(action, actor, document, user, **change):
    _audit_agent_event(event_type='padif.ai.' + action, actor=actor, target_type='padif_document', target_id=document.pk,
        change={'module_key': 'padif', 'user_id': user.pk, **change}, source='document_collaboration')


def enable_grant(document, user, actor, *, item=None, operations=None, note=''):
    target = normalize_operations(item.requested_operations if item else (operations if operations is not None else role_operations(document_role(user, document))), document_role(user, document))
    grant, created = DocumentAgentGrant.objects.select_for_update().get_or_create(document=document, user=user, defaults={'granted_by': actor})
    if grant.allowed_operations == target and grant.is_enabled == bool(target):
        return grant
    before = grant.allowed_operations
    grant.allowed_operations, grant.is_enabled = target, bool(target)
    grant.revoked_at, grant.granted_by = None if target else timezone.now(), actor
    grant.source, grant.source_request = ('request', item) if item else ('direct', None)
    grant.operations_source = 'explicit'
    if not created:
        grant.revision += 1
    grant.save()
    _audit('enabled', actor, document, user, source=grant.source, request_id=item.pk if item else None,
        revision=grant.revision, before_operations=before, allowed_operations=target, reason=note)
    return grant


def disable_grant(document, user, actor, note):
    note = validate_note(note)
    invalidate_article_requests(document, user, 'article_grant_revoked')
    grant = DocumentAgentGrant.objects.select_for_update().filter(document=document, user=user).first()
    if grant is None or not grant.is_enabled:
        return grant
    before = grant.allowed_operations
    grant.allowed_operations = []
    grant.is_enabled, grant.revoked_at = False, timezone.now()
    grant.revision += 1
    grant.save()
    _audit('revoked', actor, document, user, reason=note, revision=grant.revision, before_operations=before, allowed_operations=[])
    return grant


@transaction.atomic
def adjust_document_operations(document_id, actor, operations, revision, note):
    document = get_object_or_404(Document.objects.select_for_update(), pk=document_id)
    # Removing one's own access is allowed even if module capability is unavailable.
    from .permissions import human_document_role
    role = human_document_role(actor, document)
    if role is None or not actor.is_active:
        raise Http404
    user = get_user_model().objects.get(pk=actor.pk)
    epoch = lock_qualification(user)
    target = normalize_operations(operations, role)
    grant = DocumentAgentGrant.objects.select_for_update().filter(document=document, user=user).first()
    current = grant.allowed_operations if grant else []
    if type(revision) is not int or revision != (grant.revision if grant else 0):
        raise ValidationError('授权已变化，请刷新后重试。')
    if target == current:
        return None
    note = validate_note(note)
    increasing = bool(set(target) - set(current))
    pending = DocumentAgentRequest.objects.select_for_update().filter(document=document, applicant=user, status='pending')
    if increasing:
        require_document(user, document)
        if epoch is None:
            raise PermissionDenied('请先开通 PAdif 板块 Agent 资格。')
        if pending.exists():
            raise ValidationError('已有待审申请，请先撤回再申请新增操作。')
    reduced = [op for op in current if op in target]
    if reduced != current:
        invalidate_article_requests(document, user, 'article_operations_reduced')
        before = list(current)
        grant.allowed_operations, grant.is_enabled = reduced, bool(reduced)
        grant.revoked_at = None if reduced else timezone.now()
        grant.revision += 1
        grant.operations_source = 'explicit'
        grant.save()
        _audit('reduced', actor, document, user, reason=note, before_operations=before,
            allowed_operations=reduced, revision=grant.revision)
    if not increasing:
        return None
    role, role_revision = role_snapshot(user, document)
    item = DocumentAgentRequest.objects.create(document=document, applicant=user, reason=note,
        role=role, role_revision=role_revision, qualification_revision=epoch,
        request_kind='increase' if current else 'initial', requested_operations=target,
        basis_operations=reduced, base_grant_revision=grant.revision if grant else 0)
    _audit('requested', actor, document, user, request_id=item.pk, requested_operations=target,
        basis_operations=reduced, base_grant_revision=item.base_grant_revision)
    return item


@transaction.atomic
def submit_document_requests(user, document_ids, reason, operations=None):
    reason = validate_note(reason)
    if not isinstance(document_ids, (list, tuple)) or not document_ids or len(document_ids) > 100 or any(type(pk) is not int or pk < 1 for pk in document_ids):
        raise ValidationError('请选择 1–100 篇有效文章。')
    user = get_user_model().objects.get(pk=user.pk)
    ids = sorted(set(document_ids))
    documents = list(Document.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    if len(documents) != len(ids):
        raise Http404
    # Verify the complete batch before writing any request.
    for document in documents:
        require_document(user, document)
    epoch = lock_qualification(user)
    if epoch is None:
        raise PermissionDenied('请先开通 PAdif 板块 Agent 资格。')
    for document in documents:
        if DocumentAgentGrant.objects.filter(document=document, user=user, is_enabled=True).exists() or DocumentAgentRequest.objects.filter(document=document, applicant=user, status='pending').exists():
            raise ValidationError('所选文章已有待审核申请或有效 AI+，请移除这些项目后重试。')
    targets = {document.pk: normalize_operations(operations.get(document.pk, [READ]) if isinstance(operations, dict) else operations if operations is not None else [READ], document_role(user, document)) for document in documents}
    if any(not target for target in targets.values()):
        raise ValidationError('首次申请请选择至少阅读权限。')
    result = []
    for document in documents:
        role, revision = role_snapshot(user, document)
        item = DocumentAgentRequest.objects.create(document=document, applicant=user, reason=reason,
            role=role, role_revision=revision, qualification_revision=epoch,
            requested_operations=targets[document.pk], basis_operations=[],
            base_grant_revision=DocumentAgentGrant.objects.filter(document=document, user=user).values_list('revision', flat=True).first() or 0)
        _audit('requested', user, document, user, request_id=item.pk, requested_operations=item.requested_operations, basis_operations=[], base_grant_revision=item.base_grant_revision)
        result.append(item)
    return result


@transaction.atomic
def decide_document_request(request_id, actor, approve, note):
    initial = get_object_or_404(DocumentAgentRequest, pk=request_id)
    document = get_object_or_404(Document.objects.select_for_update(), pk=initial.document_id)
    require_document(actor, document, owner=True)
    user = get_user_model().objects.get(pk=initial.applicant_id)
    lock_qualification(user)
    item = DocumentAgentRequest.objects.select_for_update().get(pk=request_id)
    if item.status != 'pending':
        raise ValidationError('申请已处理，不能重复操作。')
    note = validate_note(note)
    if not request_is_current(item, user, document):
        return finish_request(item, 'invalidated', reason='article_precondition_changed')
    finish_request(item, 'approved' if approve else 'rejected', actor, note)
    if approve:
        enable_grant(document, user, actor, item=item, note=note)
    return item


@transaction.atomic
def withdraw_document_request(request_id, actor):
    initial = get_object_or_404(DocumentAgentRequest, pk=request_id, applicant=actor)
    if initial.document_id:
        Document.objects.select_for_update().get(pk=initial.document_id)
    item = DocumentAgentRequest.objects.select_for_update().get(pk=request_id)
    return finish_request(item, 'withdrawn', actor)


@transaction.atomic
def set_document_ai(document_id, actor, user, enabled, note='', operations=None):
    document = get_object_or_404(Document.objects.select_for_update(), pk=document_id)
    require_document(actor, document, owner=True)
    if type(enabled) is not bool:
        raise ValidationError('无效的 AI+ 状态。')
    if not enabled:
        return disable_grant(document, user, actor, note)
    require_document(user, document)
    if lock_qualification(user) is None:
        raise ValidationError('该账号尚未通过 PAdif Agent 开通审核。')
    target = normalize_operations(operations if operations is not None else role_operations(document_role(user, document)), document_role(user, document))
    if not target:
        raise ValidationError('启用 AI+ 至少需要阅读权限。')
    pending = DocumentAgentRequest.objects.select_for_update().filter(document=document, applicant=user, status='pending').first()
    if pending:
        note = validate_note(note)
        if not request_is_current(pending, user, document):
            finish_request(pending, 'invalidated', reason='article_precondition_changed')
            return None  # No silent new direct grant after a stale request.
        if target != pending.requested_operations:
            raise ValidationError('目标与待审申请不同，请先明确处理旧申请。')
        finish_request(pending, 'approved', actor, note)
    else:
        validate_note(note)
    return enable_grant(document, user, actor, item=pending, operations=target, note=note)


@transaction.atomic
def relinquish_document_ai(document_id, actor, note):
    document = get_object_or_404(Document.objects.select_for_update(), pk=document_id)
    require_document(actor, document)
    return disable_grant(document, actor, actor, note)


def invalidate_article_requests(document, user, reason):
    invalidate_pending(DocumentAgentRequest.objects.filter(document=document, applicant=user), reason)
