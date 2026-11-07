"""OAuth connection lifecycle and bounded, transactionally saved write receipts."""
from django.conf import settings
from django.db import models


class RequestStatus(models.TextChoices):
    PENDING = 'pending', '待审核'
    APPROVED = 'approved', '已批准'
    REJECTED = 'rejected', '已驳回'
    WITHDRAWN = 'withdrawn', '已撤回'
    INVALIDATED = 'invalidated', '已失效'


class AgentAccessRequest(models.Model):
    Status = RequestStatus

    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='agent_access_requests')
    module_key = models.CharField(max_length=32, default='padif')
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_agent_requests')
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    invalidated_reason = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        permissions = [('review_agent_access', '可审核 Agent 开通资格')]
        constraints = [models.UniqueConstraint(fields=['applicant', 'module_key'], condition=models.Q(status='pending'), name='unique_pending_module_request')]


class AgentQualification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='agent_qualifications')
    module_key = models.CharField(max_length=32, default='padif')
    revision = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    management_note = models.TextField(blank=True)
    managed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'module_key'], name='unique_user_module_qualification')]


class Connection(models.Model):
    module_key = models.CharField(max_length=32, default='padif')
    family = models.UUIDField(unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    application = models.ForeignKey('oauth2_provider.Application', on_delete=models.CASCADE)
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class WriteReceipt(models.Model):
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE)
    request_id = models.CharField(max_length=128)
    input_digest = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['connection', 'request_id'], name='mcp_unique_write_request')]
