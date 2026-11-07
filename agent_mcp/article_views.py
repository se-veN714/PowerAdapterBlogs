from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import redirect
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from padif.agent_requests import submit_document_requests, withdraw_document_request, relinquish_document_ai, adjust_document_operations
from .access import require_module


@login_required
@require_POST
def apply_articles(request):
    try:
        require_module(request.POST.get('module_key', 'padif'))
        ids = request.POST.getlist('document_ids')
        if any(not value.isdigit() for value in ids):
            raise ValidationError('请选择有效文章。')
        submit_document_requests(request.user, [int(value) for value in ids], request.POST.get('reason', ''),
            operations={int(value): request.POST.getlist('operations_' + value) if request.POST.get('operations_form') == '1' else ['padif:read'] for value in ids})
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, '文章 AI+ 申请已逐篇提交，请等待创建者审核。')
    return redirect('accounts:agent-token-management')


@login_required
@require_POST
def withdraw_article(request, request_id):
    try:
        withdraw_document_request(request_id, request.user)
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, '文章 AI+ 申请已撤回。')
    return redirect('accounts:agent-token-management')


@login_required
@require_POST
def relinquish_article(request, document_id):
    try:
        relinquish_document_ai(document_id, request.user, request.POST.get('note', ''))
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, '已放弃本文 AI+，人类协作角色及其他文章授权不变。')
    return redirect('accounts:agent-token-management')


@login_required
@require_POST
def adjust_article(request, document_id):
    wants_json = 'application/json' in request.headers.get('Accept', '')
    try:
        raw_revision = request.POST.get('revision', '')
        if not raw_revision.isdigit():
            raise ValidationError('无效的授权修订号，请刷新后重试。')
        item = adjust_document_operations(document_id, request.user, request.POST.getlist('operations'),
            int(raw_revision), request.POST.get('note', ''))
    except (ValidationError, PermissionDenied) as error:
        text = '; '.join(error.messages) if isinstance(error, ValidationError) else str(error)
        if wants_json:
            return JsonResponse({'error': text}, status=400 if isinstance(error, ValidationError) else 403)
        messages.error(request, text)
    else:
        text = '设置已提交；新增操作等待创建者审批，现有保留项继续有效。' if item else '权限设置已更新。'
        if wants_json:
            from .presentation import portal_context
            context = portal_context(request.user)
            doc = next((doc for doc in context['agent_documents'] if doc.pk == document_id), None)
            return JsonResponse({'message': text, 'row_html': render_to_string('pages/accounts/_agent_article_row.html', {**context, 'doc': doc}, request=request) if doc else '',
                'granted_count': context['agent_article_count'], 'pending_count': context['agent_pending_article_count']})
        messages.success(request, text)
    return redirect('accounts:agent-token-management')
