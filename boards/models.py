"""Boards 应用的模型定义。

Board 模型：首页 Editorial 板块的元数据。
每个板块对应首页一个 editorial-section，包含名称、颜色、关键词等信息。
"""

from django.conf import settings
from django.db import models


class Board(models.Model):
    """首页 Editorial 板块。

    每个板块在首页渲染为一个 editorial-section，包含：
    - 编号（自动按 sort_order 生成）
    - 标题（如 "Skateboard"）
    - 描述文本
    - glitch 悬停颜色（CSS 颜色值）
    - 关键词（竖排展示）
    - 关联博客分类（点击跳转）
    """

    slug = models.SlugField(max_length=64, unique=True, verbose_name="标识符")
    name = models.CharField(max_length=64, verbose_name="板块名称")
    description = models.TextField(
        blank=True, verbose_name="描述",
        help_text="支持 HTML，用于 editorial-body",
    )
    glitch_color = models.CharField(
        max_length=32, default="#4ed7af", verbose_name="Glitch 颜色",
        help_text="鼠标悬停 editorial-visual 时的颜色叠加，CSS 颜色值",
    )
    keywords = models.CharField(
        max_length=256, blank=True, verbose_name="关键词",
        help_text="逗号分隔，竖排展示在第四栏",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0, verbose_name="排序",
        help_text="数字越小越靠前",
    )
    category = models.ForeignKey(
        'Blogs.Category', on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="关联分类",
        help_text="点击 Enter World 跳转到该分类文章列表",
    )
    is_active = models.BooleanField(default=True, verbose_name="启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ['sort_order', 'pk']
        verbose_name = verbose_name_plural = "首页板块"
        permissions = [
            ("apply_board_access", "可申请板块权限"),
        ]

    def __str__(self):
        return f"{self.sort_order:02d} {self.name}"

    @property
    def keywords_list(self):
        """返回关键词列表。"""
        if not self.keywords:
            return []
        return [k.strip() for k in self.keywords.split(',') if k.strip()]

    @property
    def metadata_words(self):
        """返回三个元数据词（用于第一栏竖排展示）。

        优先从 keywords 取前三个，不足则用 name 的变体填充。
        """
        words = self.keywords_list
        if len(words) >= 3:
            return words[:3]
        # 回退：用 name 生成变体
        name_words = self.name.upper().split()
        while len(words) < 3:
            idx = len(words) % len(name_words) if name_words else 0
            words.append(name_words[idx] if name_words else self.name[:6].upper())
        return words[:3]


class BoardMembership(models.Model):
    """A user's single role within one Board.

    Membership rows are updated or deactivated instead of duplicated so that
    later approval and audit flows have one stable record to reference.
    """

    class Role(models.TextChoices):
        CONTRIBUTOR = "contributor", "投稿者"
        EDITOR = "editor", "编辑者"
        REVIEWER = "reviewer", "审核者"
        MANAGER = "manager", "板块管理员"

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="板块",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="board_memberships",
        verbose_name="用户",
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        verbose_name="板块角色",
    )
    is_active = models.BooleanField(default=True, verbose_name="启用")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_board_memberships",
        verbose_name="创建人",
        help_text="自动迁移或系统初始化的记录可以为空。",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ["board_id", "user_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["board", "user"],
                name="unique_board_member",
            ),
        ]
        verbose_name = "板块成员"
        verbose_name_plural = "板块成员"

    def __str__(self):
        return f"{self.board.name} / {self.user.username} / {self.get_role_display()}"
