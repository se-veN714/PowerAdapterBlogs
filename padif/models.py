from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


class Document(models.Model):
    title = models.CharField(max_length=200, verbose_name="标题")
    source_name = models.CharField(max_length=255, blank=True, verbose_name="来源文件名")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="padif_documents",
        verbose_name="创建人",
    )
    current_version = models.ForeignKey(
        "Version",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for_documents",
        verbose_name="当前版本",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["-updated_at", "-pk"]
        verbose_name = "PAdif 文档"
        verbose_name_plural = "PAdif 文档"
        permissions = [("use_padif", "可以使用 PAdif 文案交接工具")]

    def __str__(self) -> str:
        return self.title


class DocumentCollaborator(models.Model):
    class Role(models.TextChoices):
        VIEWER = 'viewer', '访客'
        COLLABORATOR = 'collaborator', '协作者'

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='collaborators')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='padif_collaborations')
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=1)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['document', 'user'], name='padif_unique_collaborator')]


class DocumentAgentGrant(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='agent_grants')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='padif_agent_grants')
    is_enabled = models.BooleanField(default=False)
    allowed_operations = models.JSONField(default=list)
    operations_source = models.CharField(max_length=24, default='explicit')
    revision = models.PositiveIntegerField(default=1)
    source = models.CharField(max_length=16, default='legacy')
    source_request = models.ForeignKey('DocumentAgentRequest', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    revoked_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['document', 'user'], name='padif_unique_document_ai')]


class DocumentAgentRequest(models.Model):
    from agent_mcp.models import RequestStatus as Status

    document = models.ForeignKey(Document, null=True, on_delete=models.SET_NULL, related_name='agent_requests')
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='document_agent_requests')
    module_key = models.CharField(max_length=32, default='padif')
    reason = models.TextField()
    request_kind = models.CharField(max_length=16, default='initial')
    requested_operations = models.JSONField(default=list)
    basis_operations = models.JSONField(default=list)
    base_grant_revision = models.PositiveIntegerField(default=0)
    operations_source = models.CharField(max_length=24, default='explicit')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    role = models.CharField(max_length=16)
    role_revision = models.PositiveIntegerField()
    qualification_revision = models.PositiveIntegerField()
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decision_note = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    closed_at = models.DateTimeField(null=True, blank=True)
    invalidated_reason = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['applicant', 'document'], condition=models.Q(status='pending'), name='unique_pending_document_ai_request')]


class Branch(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="branches")
    name = models.SlugField(max_length=64, validators=[RegexValidator(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")])
    description = models.CharField(max_length=300, blank=True)
    is_default = models.BooleanField(default=False)
    forked_from = models.ForeignKey("Version", null=True, blank=True, on_delete=models.SET_NULL, related_name="forked_branches")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="padif_branches")
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(fields=["document", "name"], name="padif_unique_branch_name_per_document"),
            models.UniqueConstraint(fields=["document"], condition=models.Q(is_default=True), name="padif_one_default_branch_per_document"),
        ]

    def clean(self):
        if self.is_default and (self.name != "main" or self.archived_at or self.forked_from_id):
            raise ValidationError("默认分支必须为 main，不能归档或设置分叉源。")
        if not self.is_default and (self.name == "main" or not self.forked_from_id):
            raise ValidationError("普通分支必须提供分叉源，且不能使用 main。")
        if self.forked_from_id and self.forked_from.document_id != self.document_id:
            raise ValidationError("分叉源必须属于同一文档。")

    def __str__(self):
        return self.name


class Version(models.Model):
    class Kind(models.TextChoices):
        MAJOR = "major", "Major"
        MINOR = "minor", "Minor"
        PATCH = "patch", "Patch"

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="文档",
    )
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="versions")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    content = models.TextField(verbose_name="正文快照")
    commit_message = models.CharField(max_length=300, verbose_name="提交说明")
    semantic_version = models.CharField(max_length=32, verbose_name="语义版本")
    version_kind = models.CharField(
        max_length=8,
        choices=Kind.choices,
        verbose_name="版本级别",
    )
    diff_stats = models.JSONField(default=dict, blank=True, verbose_name="差异统计")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="padif_versions",
        verbose_name="提交人",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="提交时间")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "semantic_version"],
                name="padif_unique_branch_semantic_version",
            )
        ]
        verbose_name = "PAdif 版本"
        verbose_name_plural = "PAdif 版本"

    def __str__(self) -> str:
        return f"{self.document.title} v{self.semantic_version} · {self.branch.name}"

    @property
    def is_on_default_branch(self):
        return self.branch.is_default

    def clean(self):
        if self.branch_id and self.branch.document_id != self.document_id:
            raise ValidationError("版本分支必须属于同一文档。")
        if self.parent_id and (self.parent.document_id != self.document_id or (self.pk and self.parent_id >= self.pk)):
            raise ValidationError("前驱必须是同文档的较早版本。")


class Annotation(models.Model):
    class Kind(models.TextChoices):
        SUGGESTION = "suggestion", "修改建议"
        EXPLANATION = "explanation", "解释"
        QUESTION = "question", "提问"

    class Status(models.TextChoices):
        OPEN = "open", "开放"
        RESOLVED = "resolved", "已处理"
        REJECTED = "rejected", "驳回"

    version = models.ForeignKey(
        Version,
        on_delete=models.CASCADE,
        related_name="annotations",
        verbose_name="版本",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="padif_annotations",
        verbose_name="作者",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, verbose_name="类型")
    body = models.TextField(verbose_name="批注内容")
    start_line = models.PositiveIntegerField(verbose_name="起始行")
    end_line = models.PositiveIntegerField(verbose_name="结束行")
    selected_text = models.TextField(blank=True, verbose_name="选中文字")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        verbose_name="状态",
    )
    resolution_note = models.TextField(blank=True, verbose_name="处理说明")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="padif_resolved_annotations",
        verbose_name="处理人",
    )
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="处理时间")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_line", "created_at", "pk"]
        verbose_name = "PAdif 批注"
        verbose_name_plural = "PAdif 批注"

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.version} · {self.start_line}"


class AnnotationReply(models.Model):
    annotation = models.ForeignKey(
        Annotation,
        on_delete=models.CASCADE,
        related_name="replies",
        verbose_name="批注",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="padif_annotation_replies",
        verbose_name="作者",
    )
    body = models.TextField(verbose_name="回复内容")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "PAdif 批注回复"
        verbose_name_plural = "PAdif 批注回复"

    def __str__(self) -> str:
        return f"回复 · {self.annotation_id} · {self.author}"
