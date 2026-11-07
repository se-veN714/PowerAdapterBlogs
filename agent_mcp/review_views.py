from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponseBadRequest
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from PowerAdapterBlogs.dashboard_views import dashboard_access_required
from PowerAdapterBlogs.dashboard_context import dashboard_shell_context
from .access import (can_review_agents, submit_agent_request, decide_agent_request, revoke_agent_qualification, withdraw_agent_request,
    grant_agent_qualification, update_agent_qualification, require_module)
from padif.permissions import can_use_padif
from .models import AgentAccessRequest, AgentQualification


@login_required
@require_POST
def apply(request):
    try:
        submit_agent_request(request.user, request.POST.get('reason', ''), request.POST.get('module_key'))
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, 'PAdif 板块申请已提交；审核通过后，请继续申请文章 AI+。')
    return redirect('accounts:agent-token-management')


@login_required
@require_POST
def withdraw(request, request_id):
    try:
        withdraw_agent_request(request_id, request.user)
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, 'PAdif 板块申请已撤回。')
    return redirect('accounts:agent-token-management')


@method_decorator(never_cache, name='dispatch')
@method_decorator(dashboard_access_required, name='dispatch')
class AgentAccessReviewView(ListView):
    template_name = 'pages/dashboard/agents.html'
    context_object_name = 'access_requests'
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if not can_review_agents(request.user):
            raise PermissionDenied('当前账号没有 Agent 审核权限。')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = AgentAccessRequest.objects.filter(module_key='padif').select_related('applicant', 'reviewed_by').order_by('-created_at', '-pk')
        status = self.request.GET.get('status', 'pending')
        if status in AgentAccessRequest.Status.values:
            queryset = queryset.filter(status=status)
        query = self.request.GET.get('q', '').strip()[:254]
        return queryset.filter(Q(applicant__username__icontains=query) | Q(applicant__email__iexact=query)) if query else queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(dashboard_shell_context(self.request, active='agents', title='Agent 授权管理'))
        context['status_choices'] = [('all', '全部记录'), *AgentAccessRequest.Status.choices]
        context['selected_status'] = self.request.GET.get('status', 'pending')
        query = self.request.GET.get('q', '').strip()[:254]
        context['search_query'] = query
        selected = self.request.GET.get('qualification_status', 'all')
        context['qualification_status'] = selected if selected in {'all', 'active', 'revoked'} else 'all'
        qualifications = AgentQualification.objects.filter(module_key='padif').select_related('user', 'managed_by').order_by('user__username', 'pk')
        if selected in {'active', 'revoked'}:
            qualifications = qualifications.filter(is_active=selected == 'active')
        if query:
            qualifications = qualifications.filter(Q(user__username__icontains=query) | Q(user__email__iexact=query))
        page = Paginator(qualifications, 20).get_page(self.request.GET.get('qualification_page'))
        for grant in page:
            grant.can_manage = grant.user_id != self.request.user.pk and not grant.user.is_superuser
            grant.can_reopen = grant.can_manage and not grant.is_active and can_use_padif(grant.user)
        context['qualifications'] = page
        context['qualification_page'] = page
        active_users = set(AgentQualification.objects.filter(module_key='padif', is_active=True).values_list('user_id', flat=True))
        for item in context['access_requests']:
            item.qualification_active = item.applicant_id in active_users
        accounts = list(get_user_model().objects.filter(Q(username__icontains=query) | Q(email__iexact=query)).order_by('username', 'pk')[:10]) if query else []
        grants = {grant.user_id: grant for grant in AgentQualification.objects.filter(user__in=accounts, module_key='padif')}
        pending = set(AgentAccessRequest.objects.filter(applicant__in=accounts, module_key='padif', status='pending').values_list('applicant_id', flat=True))
        for account in accounts:
            grant = grants.get(account.pk)
            account.agent_revision = grant.revision if grant else 0
            account.agent_qualified = bool(grant and grant.is_active)
            account.agent_was_revoked = bool(grant and grant.revoked_at)
            account.agent_pending = account.pk in pending
            account.can_grant_agent = account.pk != self.request.user.pk and not account.is_superuser and not account.agent_qualified and can_use_padif(account)
            if account.is_superuser:
                account.agent_block_reason = '超级管理员使用系统内置资格'
            elif account.pk == self.request.user.pk:
                account.agent_block_reason = '不能管理自己的开通资格'
            elif not account.is_active:
                account.agent_block_reason = '账号未启用，无法开通'
            elif not can_use_padif(account):
                account.agent_block_reason = '缺少 PAdif 使用能力，请先在账号权限管理中开通'
            else:
                account.agent_block_reason = '已开通，可在下方修改说明或撤销' if account.agent_qualified else ''
            local, separator, domain = account.email.partition('@')
            account.masked_email = local[:2] + '***@' + domain if separator else '未设置邮箱'
        context['found_accounts'] = accounts
        parameters = {'q': query, 'status': context['selected_status'], 'qualification_status': context['qualification_status']}
        context['pagination_query'] = urlencode(parameters)
        return context

    def post(self, request, *args, **kwargs):
        action, note = request.POST.get('action'), request.POST.get('note', '')
        item = None
        try:
            require_module(request.POST.get('module_key') if action in {'grant', 'update'} else request.POST.get('module_key', 'padif'))
            if action in {'grant', 'update', 'revoke'} and request.POST.get('user_id', '').isascii() and request.POST.get('user_id', '').isdecimal():
                user_id = int(request.POST['user_id'])
                get_object_or_404(get_user_model(), pk=user_id)
            elif action in {'approve', 'reject', 'revoke'}:
                request_id = request.POST.get('request_id', '')
                if not request_id.isascii() or not request_id.isdecimal():
                    return HttpResponseBadRequest('无效的申请编号。')
                item = get_object_or_404(AgentAccessRequest, pk=request_id, module_key='padif')
                user_id = item.applicant_id
            else:
                raise ValidationError('无效的授权操作或账号编号。')
            revision = request.POST.get('revision')
            if revision is not None and (not revision.isascii() or not revision.isdecimal()):
                raise ValidationError('无效的资格修订号。')
            expected = int(revision) if revision is not None else None
            if action == 'grant':
                grant_agent_qualification(user_id, request.user, note, expected_revision=expected)
            elif action == 'update':
                update_agent_qualification(user_id, request.user, note, expected_revision=expected)
            elif action == 'revoke':
                revoke_agent_qualification(user_id, request.user, note, expected_revision=expected)
            elif action in {'approve', 'reject'}:
                item = decide_agent_request(item.pk, request.user, action == 'approve', note)
        except ValidationError as error:
            messages.error(request, '; '.join(error.messages))
        else:
            messages.success(request, '申请已失效，请申请人重新提交。' if item and item.status == 'invalidated' else 'PAdif Agent 资格已更新；文章与客户端权限仍需单独授权，审核记录已保留。')
        # Reuse the submitted query only as an encoded local filter, never as a redirect URL.
        query = request.POST.get('q', '').strip()[:254]
        url = reverse('dashboard:agents')
        return redirect(url + '?' + urlencode({'q': query}) if query else 'dashboard:agents')
