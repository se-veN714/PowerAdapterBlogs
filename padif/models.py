from django.conf import settings
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
                fields=["document", "semantic_version"],
                name="padif_unique_document_semantic_version",
            )
        ]
        verbose_name = "PAdif 版本"
        verbose_name_plural = "PAdif 版本"

    def __str__(self) -> str:
        return f"{self.document.title} v{self.semantic_version}"
