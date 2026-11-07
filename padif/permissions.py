from typing import Protocol
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.db.models import Q


class PadifUser(Protocol):
    is_authenticated: bool
    is_active: bool
    is_superuser: bool

    def has_perm(self, perm: str) -> bool: ...


def can_use_padif(user: PadifUser) -> bool:
    """Keep authentication and global PAdif capability separate."""
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.is_superuser or user.has_perm("padif.use_padif"))
    )


def visible_documents(user, *, agent=False):
    from .models import Document
    if not can_use_padif(user):
        return Document.objects.none()
    query = Document.objects.filter(Q(created_by_id=user.pk) | Q(collaborators__user_id=user.pk, collaborators__is_active=True)).distinct()
    if agent:
        from agent_mcp.access import can_use_agent
        if not can_use_agent(user):
            return Document.objects.none()
        query = query.filter(agent_grants__user_id=user.pk, agent_grants__is_enabled=True, agent_grants__allowed_operations__contains=['padif:read'])
    return query


def document_role(user, document):
    if not can_use_padif(user):
        return None
    return human_document_role(user, document)


def human_document_role(user, document):
    if document.created_by_id == user.pk:
        return 'owner'
    return document.collaborators.filter(user_id=user.pk, is_active=True).values_list('role', flat=True).first()


def require_document(user, document, *, write=False, owner=False, agent=False, operation=None):
    role = document_role(user, document)
    if role is None:
        raise Http404('文档不存在。')
    if agent:
        from .agent_operations import READ, role_operations
        operation = operation or READ
        allowed = document.agent_grants.filter(user_id=user.pk, is_enabled=True).values_list('allowed_operations', flat=True).first() or []
        if READ not in allowed or operation not in allowed or operation not in role_operations(role):
            raise PermissionDenied('本文未授予该 Agent 所需的操作权限。')
    if agent:
        from agent_mcp.access import can_use_agent
        if not can_use_agent(user):
            raise PermissionDenied('Agent 资格未开通。')
    if owner and role != 'owner':
        raise PermissionDenied('仅文档创建者可以执行此操作。')
    if write and role not in {'owner', 'collaborator'}:
        raise PermissionDenied('本文为只读访问。')
    return role


def action_document_id(values):
    """Resolve indirect IDs without exposing body/metadata to callers."""
    from .models import Version, Annotation
    if 'document_id' in values:
        return values['document_id']
    if 'version_id' in values:
        return Version.objects.filter(pk=values['version_id']).values_list('document_id', flat=True).first()
    if 'annotation_id' in values:
        return Annotation.objects.filter(pk=values['annotation_id']).values_list('version__document_id', flat=True).first()
    return None


def agent_permission_payload(user, document, scopes):
    from .agent_operations import OPERATIONS, role_operations
    from agent_mcp.access import can_use_agent
    role = document_role(user, document)
    allowed = document.agent_grants.filter(user=user, is_enabled=True).values_list('allowed_operations', flat=True).first() or []
    effective = [key for key in OPERATIONS if key in allowed and key in scopes and key in role_operations(role)] if can_use_agent(user) else []
    return {'role': role, 'ai_enabled': bool(allowed), 'can_write': role in {'owner', 'collaborator'},
        'allowed_operations': allowed, 'effective_operations': effective,
        'can_annotate': 'padif:annotate' in effective, 'can_commit_version': 'padif:version' in effective}
