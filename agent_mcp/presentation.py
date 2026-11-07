"""Read-only portal state: never expose document metadata through request history."""
from django.db.models import Q
from padif.models import DocumentAgentGrant, DocumentAgentRequest
from padif.permissions import can_use_padif, visible_documents, document_role
from .access import can_use_agent
from padif.agent_operations import OPERATIONS, LABELS, READ, operation_summary
from .models import AgentQualification, AgentAccessRequest


def portal_context(user):
    qualified = can_use_agent(user)
    qualification = AgentQualification.objects.filter(user=user, module_key='padif').first()
    current = '已开通' if qualified else '已撤销' if qualification and qualification.revoked_at else '未开通'
    if qualification and qualification.is_active and not can_use_padif(user):
        current = '当前不可用：账号或 PAdif 使用权限不满足'
    documents = list(visible_documents(user).order_by('-updated_at', '-pk'))
    documents_by_id = {doc.pk: doc for doc in documents}
    grants = {item.document_id: item for item in DocumentAgentGrant.objects.filter(user=user, document_id__in=documents_by_id)}
    pending = {item.document_id: item for item in DocumentAgentRequest.objects.filter(applicant=user, status='pending', document_id__in=documents_by_id)}
    for doc in documents:
        doc.access_role = {'owner': '创建者', 'viewer': '访客 · 只读', 'collaborator': '协作者'}[document_role(user, doc)]
        grant = grants.get(doc.pk)
        doc.ai_operations = grant.allowed_operations if grant and grant.is_enabled else []
        doc.ai_enabled = bool(qualified and READ in doc.ai_operations)
        doc.ai_revision = grant.revision if grant else 0
        doc.ai_role = document_role(user, doc)
        doc.ai_can_write = doc.ai_role in {'owner', 'collaborator'}
        doc.ai_operation_values = ','.join(doc.ai_operations)
        doc.ai_operation_options = [{'key': key, 'label': LABELS[key], 'allowed': key in doc.ai_operations} for key in OPERATIONS]
        doc.ai_status = '已授权' if doc.ai_enabled else '已撤销' if grant and grant.revoked_at else '未授权'
        doc.pending_request = pending.get(doc.pk)
        doc.pending_operations_summary = operation_summary(doc.pending_request.requested_operations) if doc.pending_request else ''
        doc.can_request_ai = qualified and not doc.ai_operations and not doc.pending_request
    history = list(DocumentAgentRequest.objects.filter(applicant=user).select_related('reviewed_by', 'closed_by')[:40])
    for item in history:
        item.visible_title = documents_by_id[item.document_id].title if item.document_id in documents_by_id else None
        item.operations_summary = operation_summary(item.requested_operations)
    return {'agent_qualified': qualified, 'module_status': current,
        'agent_requests': AgentAccessRequest.objects.filter(applicant=user, module_key='padif').select_related('reviewed_by', 'closed_by')[:20],
        'agent_pending': AgentAccessRequest.objects.filter(applicant=user, module_key='padif', status='pending').exists(),
        'agent_documents': documents, 'article_requests': history,
        'agent_article_count': sum(doc.ai_enabled for doc in documents),
        'agent_pending_article_count': len(pending),
        'agent_requestable_count': sum(doc.can_request_ai for doc in documents)}


def consent_context(user):
    """Describe article coverage, separately from the client's requested scopes."""
    documents = visible_documents(user, agent=True)
    total = documents.count()
    writable = DocumentAgentGrant.objects.filter(user=user, document__in=documents, is_enabled=True).filter(Q(allowed_operations__contains=['padif:annotate']) | Q(allowed_operations__contains=['padif:version'])).count()
    shown = list(documents.order_by('-updated_at', '-pk')[:8])
    for document in shown:
        document.operations_summary = operation_summary(document.agent_grants.get(user=user).allowed_operations)
        document.access_role = {'owner': '创建者', 'viewer': '访客 · 只读', 'collaborator': '协作者'}[document_role(user, document)]
    return {'consent_documents': shown, 'consent_article_count': total,
        'consent_more_count': max(total - len(shown), 0), 'consent_writable_count': writable,
        'consent_pending_count': DocumentAgentRequest.objects.filter(applicant=user, status='pending',
            document__in=visible_documents(user)).count()}
