from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponseBadRequest
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from PowerAdapterBlogs.dashboard_views import dashboard_access_required
from PowerAdapterBlogs.dashboard_context import dashboard_shell_context
from .access import can_review_agents, submit_agent_request, decide_agent_request, revoke_agent_qualification, withdraw_agent_request
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
        return queryset.filter(status=status) if status in AgentAccessRequest.Status.values else queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(dashboard_shell_context(self.request, active='agents', title='Agent 审核'))
        context['status_choices'] = AgentAccessRequest.Status.choices
        context['selected_status'] = self.request.GET.get('status', 'pending')
        context['qualifications'] = AgentQualification.objects.filter(module_key='padif').filter(is_active=True).select_related('user').order_by('user__username')
        active_users = set(AgentQualification.objects.filter(module_key='padif', is_active=True).values_list('user_id', flat=True))
        for item in context['access_requests']:
            item.qualification_active = item.applicant_id in active_users
        return context

    def post(self, request, *args, **kwargs):
        action, note = request.POST.get('action'), request.POST.get('note', '')
        item = None
        if action == 'revoke' and request.POST.get('user_id', '').isdigit():
            user_id = int(request.POST['user_id'])
        else:
            request_id = request.POST.get('request_id', '')
            if not request_id.isdigit():
                return HttpResponseBadRequest('无效的申请编号。')
            item = get_object_or_404(AgentAccessRequest, pk=request_id, module_key='padif')
            user_id = item.applicant_id
        try:
            if action == 'revoke':
                revoke_agent_qualification(user_id, request.user, note)
            elif action in {'approve', 'reject'}:
                item = decide_agent_request(item.pk, request.user, action == 'approve', note)
            else:
                raise ValidationError('未知审核操作。')
        except ValidationError as error:
            messages.error(request, '; '.join(error.messages))
        else:
            messages.success(request, '申请已失效，请申请人重新提交。' if item and item.status == 'invalidated' else 'PAdif Agent 资格已更新，审核记录已保留。')
        return redirect('dashboard:agents')
