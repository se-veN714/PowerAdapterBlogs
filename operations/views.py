from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import ListView

from security.models import SecureLogEntry
from security.services import audit_secure_log_entries

from .policies import (
    can_run_integrity_audit,
    can_view_security_operations,
)


@method_decorator(never_cache, name="dispatch")
class SecurityOperationsView(LoginRequiredMixin, ListView):
    template_name = "pages/operations/security.html"
    context_object_name = "audit_entries"
    paginate_by = 25

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_view_security_operations(
            request.user
        ):
            raise PermissionDenied("当前账号没有安全审计查看权限。")
        return super().dispatch(request, *args, **kwargs)

    def _filters(self):
        return {
            "status": self.request.GET.get("status", "").strip(),
            "q": self.request.GET.get("q", "").strip()[:100],
        }

    def get_queryset(self):
        queryset = SecureLogEntry.objects.select_related(
            "log_entry",
            "log_entry__user",
            "log_entry__content_type",
        )
        filters = self._filters()
        if filters["status"] == "tampered":
            queryset = queryset.filter(is_tampered=True)
        elif filters["status"] == "intact":
            queryset = queryset.filter(is_tampered=False)
        if filters["q"]:
            query = filters["q"]
            queryset = queryset.filter(
                Q(log_entry__user__username__icontains=query)
                | Q(log_entry__object_repr__icontains=query)
                | Q(log_entry__change_message__icontains=query)
            )
        return queryset.order_by("-log_entry__action_time", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_entries = SecureLogEntry.objects.all()
        context.update(
            {
                "filters": self._filters(),
                "total_count": all_entries.count(),
                "tampered_count": all_entries.filter(is_tampered=True).count(),
                "unverified_count": all_entries.filter(
                    last_verified_at__isnull=True
                ).count(),
                "can_run_integrity_audit": can_run_integrity_audit(
                    self.request.user
                ),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        if not can_run_integrity_audit(request.user):
            raise PermissionDenied("当前账号没有运行完整性审计的权限。")
        try:
            result = audit_secure_log_entries(
                actor=request.user,
                entry_ids=request.POST.getlist("entry_ids"),
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            if result.tampered:
                messages.error(
                    request,
                    f"已核验 {result.checked} 条记录，发现 {result.tampered} 条异常。",
                )
            else:
                messages.success(
                    request,
                    f"已核验 {result.checked} 条记录，未发现完整性异常。",
                )

        query = {
            key: value
            for key, value in self._filters().items()
            if value
        }
        target = reverse("operations:security")
        if query:
            target = f"{target}?{urlencode(query)}"
        return redirect(target)
