"""Owner-managed collaboration; every change locks the same document as writes."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.agent_auth import _audit_agent_event
from .models import Document, DocumentCollaborator, DocumentAgentGrant
from .permissions import require_document, can_use_padif


@transaction.atomic
def set_collaboration(*, document_id, actor, username, action, role=None, enabled=False, note='', operations=None):
    document = Document.objects.select_for_update().get(pk=document_id)
    require_document(actor, document, owner=True)
    target = get_user_model().objects.filter(username=username).first()
    needs_capability = action == 'role' or (action == 'ai' and enabled)
    if target is None or (needs_capability and not can_use_padif(target)):
        raise ValidationError('找不到符合授权条件的用户。')
    if action == 'role':
        if target.pk == document.created_by_id:
            raise ValidationError('创建者身份不能通过协作角色修改。')
        if role not in DocumentCollaborator.Role.values:
            raise ValidationError('未知角色。')
        existing = DocumentCollaborator.objects.filter(document=document, user=target).first()
        changed = existing is None or existing.role != role or not existing.is_active
        DocumentCollaborator.objects.update_or_create(document=document, user=target,
            defaults={'role': role, 'is_active': True, 'granted_by': actor,
                      'revision': existing.revision + int(changed) if existing else 1})
        if changed:
            from django.db.models import F
            DocumentAgentGrant.objects.filter(document=document, user=target, is_enabled=True).update(is_enabled=False, allowed_operations=[], revoked_at=timezone.now(), revision=F('revision') + 1, updated_at=timezone.now())
            from .agent_requests import invalidate_article_requests
            invalidate_article_requests(document, target, 'role_changed')
    elif action == 'remove':
        if target.pk == document.created_by_id:
            raise ValidationError('不能移除文档创建者。')
        from django.db.models import F
        DocumentCollaborator.objects.filter(document=document, user=target, is_active=True).update(is_active=False, revision=F('revision') + 1, updated_at=timezone.now())
        DocumentAgentGrant.objects.filter(document=document, user=target, is_enabled=True).update(is_enabled=False, allowed_operations=[], revoked_at=timezone.now(), revision=F('revision') + 1, updated_at=timezone.now())
        from .agent_requests import invalidate_article_requests
        invalidate_article_requests(document, target, 'member_removed')
    elif action == 'ai':
        from .agent_requests import set_document_ai
        set_document_ai(document.pk, actor, target, enabled, note, operations=operations)
        return document
    else:
        raise ValidationError('未知授权操作。')
    _audit_agent_event(event_type='padif.collaboration.' + action, actor=actor,
        target_type='padif_document', target_id=document.pk,
        change={'user_id': target.pk, 'role': role if action == 'role' else None,
                'ai_enabled': enabled if action == 'ai' else None}, source='document_collaboration')
    return document
