from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from .collaboration import set_collaboration
from .permissions import visible_documents, require_document
from .views import padif_access_required
from .agent_requests import decide_document_request
from .access_presentation import article_access_state


def _account_choices(owner, query):
    permission = Permission.objects.get(content_type__app_label='padif', codename='use_padif')
    users = get_user_model().objects.filter(is_active=True).exclude(pk=owner.pk).filter(
        Q(is_superuser=True) | Q(user_permissions=permission) | Q(groups__permissions=permission)).distinct()
    if query:
        match = Q(username__icontains=query)
        identifier = query.removeprefix('#')
        if identifier.isascii() and identifier.isdecimal() and len(identifier) < 19:
            match |= Q(pk=int(identifier))
        users = users.filter(match)
    return list(users.order_by('username', 'pk').values('id', 'username')[:20])


@padif_access_required
@never_cache
def collaboration(request, document_id):
    document = get_object_or_404(visible_documents(request.user), pk=document_id)
    require_document(request.user, document, owner=True)
    if request.method == 'GET' and request.GET.get('accounts') == '1':
        response = JsonResponse({'accounts': _account_choices(request.user, request.GET.get('q', '').strip()[:150])})
        response['Cache-Control'] = 'private, no-store'
        return response
    if request.method == 'POST':
        try:
            action = request.POST.get('action')
            if action in {'approve-ai', 'reject-ai'}:
                request_id = request.POST.get('request_id', '')
                if not request_id.isdigit():
                    raise ValidationError('无效的申请编号。')
                item = get_object_or_404(document.agent_requests, pk=request_id)
                item = decide_document_request(item.pk, request.user, action == 'approve-ai', request.POST.get('note', ''))
                if item.status == 'invalidated':
                    messages.warning(request, '申请前置权限已变化，该申请已失效。')
            else:
                set_collaboration(document_id=document.pk, actor=request.user, username=request.POST.get('username', ''),
                    action=action, role=request.POST.get('role'), enabled=request.POST.get('enabled') == 'on', note=request.POST.get('note', ''), operations=request.POST.getlist('operations') if request.POST.get('operations_form') == '1' else None)
        except ValidationError as error:
            messages.error(request, '; '.join(error.messages))
        else:
            messages.success(request, '协作授权已更新。')
        return redirect('padif:collaboration', document_id=document.pk)
    from .agent_operations import OPERATIONS, LABELS, operation_summary, role_operations
    grants = {grant.user_id: grant for grant in document.agent_grants.all()}
    members = [{'user': document.created_by, 'role': 'owner', 'label': '创建者', 'ai_enabled': bool(grants.get(document.created_by_id) and grants[document.created_by_id].is_enabled)}]
    for item in document.collaborators.filter(is_active=True).select_related('user'):
        members.append({'user': item.user, 'role': item.role, 'label': item.get_role_display(), 'ai_enabled': bool(grants.get(item.user_id) and grants[item.user_id].is_enabled)})
    for member in members:
        grant = grants.get(member['user'].pk)
        allowed = grant.allowed_operations if grant and grant.is_enabled else ['padif:read']
        member['operation_options'] = [{'key': key, 'label': LABELS[key], 'checked': key in allowed, 'disabled': key not in role_operations(member['role'])} for key in OPERATIONS]
    ai_requests = list(document.agent_requests.select_related('applicant', 'reviewed_by')[:40])
    for item in ai_requests:
        item.operations_summary = operation_summary(item.requested_operations)
        item.basis_summary = operation_summary(item.basis_operations)
    pending = {item.applicant_id: item for item in document.agent_requests.filter(status='pending').select_related('applicant')}
    for member in members:
        member['access'] = article_access_state(member['user'], member['role'], grants.get(member['user'].pk), pending.get(member['user'].pk))
    pending_reviews = list(document.agent_requests.filter(status='pending').select_related('applicant')[:40])
    for item in pending_reviews:
        item.operations_summary = operation_summary(item.requested_operations)
        item.basis_summary = operation_summary(item.basis_operations)
    return render(request, 'padif/collaboration.html', {'document': document, 'members': members,
        'ai_requests': ai_requests, 'pending_ai_requests': pending_reviews,
        'account_choices': _account_choices(request.user, ''),
        'ai_access': members[0]['access']})
