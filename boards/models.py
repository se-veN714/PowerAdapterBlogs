"""Boards 应用的模型。

- Board：首页 Editorial 板块的元数据，亦作为三块 Board Index 的注册表
  （skateboard / music / coding，由 slug 唯一标识，分派时直接用 slug）。
- BoardMembership：用户在单个 Board 中的权限角色（与展示内容无关）。
- BoardAccessRequest：权限申请的不可变审核记录。
- BoardMembershipEvent：Membership 状态变更的 append-only 关系型历史。
- 三块内容模型（Skateboard / Music / Coding）：其所属板块由模型类型固定，
  通过 `board` FK 的 default 自动写入对应 Board，Admin 中不可手动选择。

按 BOARD_INDEX_BACKEND_GUIDE.md 决策：
- 决策 2：不引入 board_type 字段，分派完全基于 Board.slug。
- 决策 3：SkateHomie 与 BoardMembership 分离，仅通过 M2M 作展示/归属标注。
- 决策 4：Music 区分 Spotify 与 Apple Music，各自一个平铺 Record 模型（共享抽象基类），
  不再拆分 Snapshot/Entry 容器——assembler 按 (year, month) 在 Python 层分组。
- 决策 5：内容仅由 superuser（站长）在 Admin 维护，无公开投稿。
"""

import functools
from pathlib import Path
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.db.models import Q

from PowerAdapterBlogs.image_validation import validate_uploaded_image


# ---------------------------------------------------------------------------
# Board 解析辅助：content 模型的 board 由模型类型固定，default 调用时按 slug 解析，
# 不经过 Admin 表单，杜绝“任意板块可选”的错误。
# ---------------------------------------------------------------------------


def _board_for_slug(slug):
    """按 slug 解析固定的归属 Board（每次 save 一次查询，开销可忽略）。"""
    return Board.objects.get(slug=slug)


def _board_default(slug):
    """生成可直接用作 ForeignKey.default 的零参 callable。

    返回 functools.partial 而非 lambda，因为 Django 迁移序列化器无法序列化 lambda。
    """
    return functools.partial(_board_for_slug, slug)


def board_content_cover_upload_to(instance, filename):
    """Store uploaded Board artwork under a random server-side filename."""
    extension = Path(filename).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        extension = ".upload"
    model_name = instance._meta.model_name
    return f"boards/{instance.BOARD_SLUG}/{model_name}/{uuid.uuid4().hex}{extension}"


class FixedBoardContentModel(models.Model):
    """Base class for content whose model type determines its Board."""

    BOARD_SLUG = None

    class Meta:
        abstract = True

    def _validate_fixed_board(self):
        if not self.BOARD_SLUG:
            raise TypeError(f"{type(self).__name__} must declare BOARD_SLUG")
        database = self._state.db
        belongs_to_expected_board = (
            self.board_id is not None
            and Board.objects.using(database)
            .filter(pk=self.board_id, slug=self.BOARD_SLUG)
            .exists()
        )
        if not belongs_to_expected_board:
            raise ValidationError({"board": f"内容必须归属 {self.BOARD_SLUG} 板块。"})

    def clean(self):
        super().clean()
        self._validate_fixed_board()

    def save(self, *args, **kwargs):
        self._validate_fixed_board()
        return super().save(*args, **kwargs)


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
        blank=True,
        verbose_name="描述",
        help_text="支持 HTML，用于 editorial-body",
    )
    glitch_color = models.CharField(
        max_length=32,
        default="#4ed7af",
        verbose_name="Glitch 颜色",
        help_text="鼠标悬停 editorial-visual 时的颜色叠加，CSS 颜色值",
    )
    keywords = models.CharField(
        max_length=256,
        blank=True,
        verbose_name="关键词",
        help_text="逗号分隔，竖排展示在第四栏",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="排序",
        help_text="数字越小越靠前",
    )
    category = models.ForeignKey(
        "Blogs.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="关联分类",
        help_text="点击 Enter World 跳转到该分类文章列表",
    )
    is_active = models.BooleanField(default=True, verbose_name="启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["sort_order", "pk"]
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
        return [k.strip() for k in self.keywords.split(",") if k.strip()]

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
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["board_id", "user_id"]
        permissions = [
            ("manage_all_board_memberships", "可管理所有板块成员"),
        ]
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


class BoardAccessRequest(models.Model):
    """An immutable review request for creating or changing one membership."""

    class Status(models.TextChoices):
        PENDING = "pending", "待审核"
        APPROVED = "approved", "已批准"
        REJECTED = "rejected", "已驳回"

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="access_requests",
        verbose_name="板块",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="board_access_requests",
        verbose_name="申请人",
    )
    requested_role = models.CharField(
        max_length=16,
        choices=BoardMembership.Role.choices,
        verbose_name="申请角色",
    )
    reason = models.TextField(blank=True, verbose_name="申请说明")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="状态",
    )
    previous_role = models.CharField(
        max_length=16,
        choices=BoardMembership.Role.choices,
        blank=True,
        verbose_name="审核时原角色",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_board_access_requests",
        verbose_name="审核人",
    )
    decision_note = models.TextField(blank=True, verbose_name="审核说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="申请时间")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="审核时间")

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["board", "applicant"],
                condition=Q(status="pending"),
                name="unique_pending_board_access_request",
            ),
        ]
        verbose_name = "板块权限申请"
        verbose_name_plural = "板块权限申请"

    def __str__(self):
        return (
            f"{self.board.name} / {self.applicant.username} / "
            f"{self.get_requested_role_display()} / {self.get_status_display()}"
        )


class BoardMembershipEvent(models.Model):
    """Append-only relational history for one Membership state transition."""

    class EventType(models.TextChoices):
        GRANTED = "granted", "授予"
        ROLE_CHANGED = "role_changed", "角色变更"
        DEACTIVATED = "deactivated", "停用"
        REACTIVATED = "reactivated", "恢复"
        MANAGER_TRANSFERRED = "manager_transferred", "Manager 交接"

    class Source(models.TextChoices):
        ACCESS_REQUEST = "access_request", "权限申请"
        SELF_SERVICE = "self_service", "成员自助"
        DASHBOARD = "dashboard", "Dashboard"
        SUPER_ADMIN = "super_admin", "Super admin break-glass"
        SYSTEM_MIGRATION = "system_migration", "系统迁移"

    membership = models.ForeignKey(
        BoardMembership,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
        verbose_name="板块成员关系",
    )
    board = models.ForeignKey(
        Board,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="membership_events",
        verbose_name="板块",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="board_membership_events",
        verbose_name="成员",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="performed_board_membership_events",
        verbose_name="操作者",
    )
    access_request = models.ForeignKey(
        BoardAccessRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="membership_events",
        verbose_name="关联申请",
    )
    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        verbose_name="事件类型",
    )
    source = models.CharField(
        max_length=32,
        choices=Source.choices,
        verbose_name="来源",
    )
    previous_role = models.CharField(
        max_length=16,
        choices=BoardMembership.Role.choices,
        blank=True,
        verbose_name="原角色",
    )
    new_role = models.CharField(
        max_length=16,
        choices=BoardMembership.Role.choices,
        blank=True,
        verbose_name="新角色",
    )
    previous_is_active = models.BooleanField(
        null=True,
        verbose_name="原启用状态",
    )
    new_is_active = models.BooleanField(verbose_name="新启用状态")
    reason = models.TextField(blank=True, verbose_name="原因")
    board_id_snapshot = models.PositiveBigIntegerField(verbose_name="板块 ID 快照")
    board_slug_snapshot = models.SlugField(
        max_length=64,
        verbose_name="板块标识快照",
    )
    user_id_snapshot = models.PositiveBigIntegerField(verbose_name="用户 ID 快照")
    username_snapshot = models.CharField(max_length=150, verbose_name="用户名快照")
    actor_id_snapshot = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        verbose_name="操作者 ID 快照",
    )
    actor_username_snapshot = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="操作者名称快照",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ["-created_at", "-pk"]
        default_permissions = ("view",)
        indexes = [
            models.Index(
                fields=["board_id_snapshot", "-created_at"],
                name="board_event_board_time_idx",
            ),
            models.Index(
                fields=["user_id_snapshot", "-created_at"],
                name="board_event_user_time_idx",
            ),
        ]
        verbose_name = "板块成员事件"
        verbose_name_plural = "板块成员事件"

    def __str__(self):
        return (
            f"{self.board_slug_snapshot} / {self.username_snapshot} / "
            f"{self.get_event_type_display()}"
        )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("板块成员事件为不可变记录，不能修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("板块成员事件为不可变记录，不能删除。")


# ---------------------------------------------------------------------------
# Skateboard Board Index 内容模型：成员节点 + 动作片段。
# ---------------------------------------------------------------------------


class ClipCategory(models.TextChoices):
    ROTATION = "rotation", "Rotation"
    DISPLACEMENT = "displacement", "Displacement"
    HEIGHT = "height", "Height"


class ClipStatus(models.TextChoices):
    LANDED = "landed", "Landed"
    UNFINISHED = "unfinished", "Unfinished"
    WIP = "wip", "WIP"
    FAILED = "failed", "Failed"


class HudType(models.TextChoices):
    ARC = "arc", "Arc"
    SPEED = "speed", "Speed"
    MEASURE = "measure", "Measure"
    RING = "ring", "Ring"


class Stance(models.TextChoices):
    REGULAR = "regular", "Regular"
    GOOFY = "goofy", "Goofy"


class SkateHomie(FixedBoardContentModel):
    """Skateboard Crew 的一个成员节点（展示内容实体）。

    与 BoardMembership 分离；通过 memberships M2M 仅作展示关联。
    所属板块固定为 skateboard（由模型类型决定，不可在 Admin 手动选择）。

    注意：成员"当前选中"状态**不存数据库**——前端 htmx 端点不写 is_active，
    而 JS 点击处理器被 !htmxDriven 门控会导致数据驱动模式下点击不更新视觉态。
    选中完全由前端控制（默认首个节点，JS 切换 active 视觉态）。
    """

    BOARD_SLUG = "skateboard"

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="homies",
        verbose_name="板块",
        default=_board_default("skateboard"),
        help_text="由模型类型固定为 skateboard，不可手动选择",
    )
    node_index = models.PositiveSmallIntegerField(verbose_name="节点编号")
    name = models.CharField(max_length=64, verbose_name="成员名")
    call_sign = models.CharField(max_length=32, blank=True, verbose_name="称呼")
    location = models.CharField(max_length=64, blank=True, verbose_name="地区")
    joined_at = models.DateField(verbose_name="加入时间")
    stance = models.CharField(
        max_length=16,
        choices=Stance.choices,
        default=Stance.REGULAR,
        verbose_name="站姿",
        help_text="Regular=左脚在前，Goofy=右脚在前",
    )
    role_label = models.CharField(max_length=32, blank=True, verbose_name="角色标签")
    avatar = models.ImageField(
        upload_to="skateboard/avatars/",
        validators=[validate_uploaded_image],
        blank=True,
        null=True,
        verbose_name="头像",
    )
    memberships = models.ManyToManyField(
        BoardMembership,
        blank=True,
        related_name="homies",
        verbose_name="关联成员",
        help_text="仅作展示/归属标注，不作为授权依据",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["node_index"]
        verbose_name = "滑板成员"
        verbose_name_plural = "滑板成员"
        constraints = [
            models.UniqueConstraint(
                fields=["board", "node_index"],
                name="unique_homie_node_per_board",
            ),
        ]

    def __str__(self):
        return f"{self.node_index:02d} {self.name}"


class SkateClip(models.Model):
    """某个成员的一个滑板动作片段。"""

    homie = models.ForeignKey(
        SkateHomie,
        on_delete=models.CASCADE,
        related_name="clips",
        verbose_name="成员",
    )
    order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")
    title = models.CharField(max_length=80, verbose_name="动作名")
    category = models.CharField(
        max_length=32,
        choices=ClipCategory.choices,
        blank=True,
        verbose_name="分类",
    )
    spot = models.CharField(max_length=128, blank=True, verbose_name="地点")
    filmed_at = models.DateField(null=True, blank=True, verbose_name="拍摄日期")
    duration = models.DurationField(null=True, blank=True, verbose_name="时长")
    status = models.CharField(
        max_length=16,
        choices=ClipStatus.choices,
        default=ClipStatus.LANDED,
        verbose_name="状态",
    )
    notes = models.TextField(blank=True, verbose_name="备注")
    video_url = models.URLField(blank=True, verbose_name="视频")
    thumbnail_url = models.URLField(blank=True, verbose_name="封面")
    hud_type = models.CharField(
        max_length=16,
        choices=HudType.choices,
        blank=True,
        verbose_name="HUD 类型",
    )
    hud_label = models.CharField(max_length=64, blank=True, verbose_name="HUD 文案")
    timecode = models.CharField(max_length=16, blank=True, verbose_name="时间码")
    is_public = models.BooleanField(default=True, verbose_name="公开")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "滑板动作片段"
        verbose_name_plural = "滑板动作片段"

    def __str__(self):
        return f"{self.order:02d} {self.title}"


# ---------------------------------------------------------------------------
# Skateboard Clip 媒体资产：私有上传 → FFprobe/FFmpeg 派生 → 状态机。
# PostgreSQL 只存元数据与 Storage key，视频二进制永不进数据库；
# 私有原片目录不出公开 URL，公开页面只消费 state=ready 的派生资源。
# ---------------------------------------------------------------------------


class SkateClipMediaState(models.TextChoices):
    UPLOADED = "uploaded", "Uploaded"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class SkateClipOrientation(models.TextChoices):
    PORTRAIT = "portrait", "Portrait"
    LANDSCAPE = "landscape", "Landscape"
    SQUARE = "square", "Square"


class SkateClipSourceStorage(FileSystemStorage):
    """私有原片存储：生成公开 URL 属于编程错误，直接失败。

    独立于 MEDIA_ROOT（开发 static() 与生产 Nginx 都触达不到），
    上限、探测与派生参数集中在 settings 的 SKATE_CLIP_* 命名空间。
    """

    def url(self, name):
        raise ValueError(
            "Skate clip private source files must never be exposed via a public URL."
        )


def skate_source_storage():
    """私有原片 Storage 工厂（FileField 用 callable 以免配置进迁移）。"""
    return SkateClipSourceStorage(location=settings.SKATE_CLIP_SOURCE_ROOT)


def skate_delivery_storage():
    """派生资源 Storage 工厂：MEDIA_ROOT/skate/ 下仅放可公开的派生文件。"""
    return FileSystemStorage(
        location=settings.SKATE_CLIP_DELIVERY_ROOT,
        base_url=settings.SKATE_CLIP_DELIVERY_URL,
    )


def _skate_source_upload_to(instance, filename):
    """服务端 UUID 命名私有原片，不信任上传文件名作路径。

    扩展名仅作显示保留（小写、限长），内容安全裁决由 S1 FFprobe 负责。
    """
    suffix = Path(filename).suffix.lower()[:16]
    if suffix and not suffix[1:].isalnum():
        suffix = ".bin"
    return f"{uuid.uuid4().hex}{suffix}"


def _skate_main_upload_to(instance, filename):
    return f"delivery/{instance.media_key}/main.webm"


def _skate_preview_upload_to(instance, filename):
    return f"preview/{instance.media_key}/preview.webm"


def _skate_poster_upload_to(instance, filename):
    return f"poster/{instance.media_key}.webp"


def derive_skate_orientation(width, height):
    """按 FFprobe 权威宽高派生画面方向；缺失或非法时返回空串。"""
    try:
        width = int(width or 0)
        height = int(height or 0)
    except (TypeError, ValueError):
        return ""
    if width <= 0 or height <= 0:
        return ""
    if width > height:
        return SkateClipOrientation.LANDSCAPE
    if width < height:
        return SkateClipOrientation.PORTRAIT
    return SkateClipOrientation.SQUARE


class SkateClipMedia(models.Model):
    """SkateClip 的媒体资产（一对一），承载上传-处理-发布生命周期。

    状态机（SKATEBOARD_GUIDE §8）：uploaded → processing → ready/failed；
    failed 经 Manager 明确重试回 uploaded；替换原片或升级 pipeline 回
    uploaded。ready 只在三类派生资源全部落盘并校验后写入。旧兼容字段
    SkateClip.video_url/thumbnail_url 在迁移兼容期保留不删，公开展示在
    media ready 后优先使用本表探测值。
    """

    clip = models.OneToOneField(
        SkateClip,
        on_delete=models.CASCADE,
        related_name="media",
        verbose_name="所属片段",
    )
    media_key = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        verbose_name="资产键",
        help_text="服务端生成的稳定标识，决定派生文件目录名",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_skate_media",
        verbose_name="上传者",
        help_text="仅审计用途；用户删除后媒体行保留",
    )
    source_file = models.FileField(
        storage=skate_source_storage,
        upload_to=_skate_source_upload_to,
        max_length=255,
        blank=True,
        verbose_name="私有原片",
        help_text="仅服务端与 Worker 可读，永不生成公开 URL",
    )
    main_file = models.FileField(
        storage=skate_delivery_storage,
        upload_to=_skate_main_upload_to,
        max_length=255,
        blank=True,
        verbose_name="正式播放 WebM",
    )
    preview_file = models.FileField(
        storage=skate_delivery_storage,
        upload_to=_skate_preview_upload_to,
        max_length=255,
        blank=True,
        verbose_name="红黑预览 WebM",
    )
    poster_file = models.ImageField(
        storage=skate_delivery_storage,
        upload_to=_skate_poster_upload_to,
        max_length=255,
        blank=True,
        verbose_name="封面 WebP",
    )
    state = models.CharField(
        max_length=16,
        choices=SkateClipMediaState.choices,
        default=SkateClipMediaState.UPLOADED,
        db_index=True,
        verbose_name="处理状态",
    )
    duration_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="时长(毫秒)",
        help_text="FFprobe 权威时长，替代人工 duration",
    )
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name="画面宽")
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name="画面高")
    orientation = models.CharField(
        max_length=16,
        choices=SkateClipOrientation.choices,
        blank=True,
        verbose_name="画面方向",
        help_text="由探测宽高派生，不手工填写",
    )
    frame_rate = models.CharField(
        max_length=32,
        blank=True,
        verbose_name="帧率",
        help_text="FFprobe r_frame_rate 文本（如 30000/1001），不解析为浮点",
    )
    source_size = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        verbose_name="原片字节数",
    )
    source_sha256 = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="原片 SHA-256",
        help_text="重复检测、审计与处理输入一致性",
    )
    pipeline_version = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="流水线版本",
        help_text="风格/编码算法升级后可从原片批量重建派生资源",
    )
    error_code = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="错误码",
        help_text="面向管理员的有界错误码，不含内部命令或路径",
    )
    error_detail = models.TextField(
        blank=True,
        verbose_name="错误详情",
        help_text="有界诊断摘要；公开页面不得渲染此字段",
    )
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name="处理完成时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "片段媒体资产"
        verbose_name_plural = "片段媒体资产"

    def __str__(self):
        return f"clip#{self.clip_id} media ({self.get_state_display()})"

    @property
    def is_ready(self):
        return self.state == SkateClipMediaState.READY

    def apply_probe(self, *, duration_ms, width, height, frame_rate=""):
        """写入 FFprobe 权威探测结果并派生画面方向（S1/S2 调用）。"""
        self.duration_ms = duration_ms
        self.width = width
        self.height = height
        self.frame_rate = frame_rate
        self.orientation = derive_skate_orientation(width, height)


# ---------------------------------------------------------------------------
# Music Board Index 内容模型：听歌场域时间序列化分析。
# ---------------------------------------------------------------------------


class MusicScope(models.TextChoices):
    YEARLY = "yearly", "Yearly"
    MONTHLY = "monthly", "Monthly"


class MusicRecordBase(FixedBoardContentModel):
    """某 provider 在某周期的一条音乐指标记录（平铺，无快照/条目拆分）。

    同一 (year, month) 的多条记录组成一个"快照组"——由 assembler 在 Python
    层按 (year, month) 分组重建，不再用 FK 容器。kind 区分指标语义：
    total（主值）/ tag（归档标签）/ core_artist（年度核心艺人，value=排名）/
    period_artist（当前周期艺人，value=风格标签）/ cross_scale（跨尺度关系，
    value=年度描述，value2=月度描述）/ companion / gravity（常伴/近期引力，
    value=起始，value2=统计，note=注记）。

    所属板块固定为 music（由模型类型决定，不可在 Admin 手动选择）。
    """

    BOARD_SLUG = "music"

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        verbose_name="板块",
        default=_board_default("music"),
        help_text="由模型类型固定为 music，不可手动选择",
    )
    title = models.CharField(max_length=128, verbose_name="标题")
    scope = models.CharField(
        max_length=16,
        choices=MusicScope.choices,
        default=MusicScope.YEARLY,
        verbose_name="周期",
    )
    year = models.PositiveSmallIntegerField(verbose_name="年份")
    month = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="月份")
    label = models.CharField(max_length=64, verbose_name="指标")
    value = models.CharField(max_length=64, verbose_name="值")
    value2 = models.CharField(max_length=64, blank=True, verbose_name="次值")
    unit = models.CharField(max_length=16, blank=True, verbose_name="单位")
    kind = models.CharField(max_length=32, blank=True, verbose_name="类型")
    note = models.TextField(blank=True, verbose_name="注记")
    rank = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="排名",
    )
    play_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="播放次数",
    )
    minutes = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        verbose_name="收听分钟",
    )
    cover = models.ImageField(
        upload_to=board_content_cover_upload_to,
        validators=[validate_uploaded_image],
        blank=True,
        verbose_name="封面",
    )
    external_url = models.URLField(blank=True, verbose_name="外部链接")
    display_order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        abstract = True
        ordering = ["-year", "-month", "display_order", "pk"]
        verbose_name = "音乐记录"
        verbose_name_plural = "音乐记录"


class SpotifyRecord(MusicRecordBase):
    class Meta(MusicRecordBase.Meta):
        verbose_name = "Spotify 记录"
        verbose_name_plural = "Spotify 记录"


class AppleRecord(MusicRecordBase):
    class Meta(MusicRecordBase.Meta):
        verbose_name = "Apple Music 记录"
        verbose_name_plural = "Apple Music 记录"


# ---------------------------------------------------------------------------
# Coding Board Index 内容模型：项目档案索引。
# ---------------------------------------------------------------------------


class CodingProject(FixedBoardContentModel):
    """Selected Projects 中的一个项目。

    所属板块固定为 coding（由模型类型决定，不可在 Admin 手动选择）。
    """

    BOARD_SLUG = "coding"

    class ProjectType(models.TextChoices):
        GITHUB = "github", "GitHub 项目"
        LOCAL_TOOL = "local_tool", "本地浏览器工具"
        EXTERNAL = "external", "外部项目"

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="projects",
        verbose_name="板块",
        default=_board_default("coding"),
        help_text="由模型类型固定为 coding，不可手动选择",
    )
    index = models.PositiveSmallIntegerField(verbose_name="序号")
    name = models.CharField(max_length=64, verbose_name="项目名")
    description = models.TextField(blank=True, verbose_name="简述")
    stack = models.CharField(max_length=128, blank=True, verbose_name="技术栈")
    year = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="年份")
    status = models.CharField(max_length=32, blank=True, verbose_name="状态")
    project_type = models.CharField(
        max_length=16,
        choices=ProjectType.choices,
        default=ProjectType.GITHUB,
        verbose_name="项目类型",
    )
    repository_url = models.URLField(blank=True, verbose_name="仓库链接")
    demo_url = models.URLField(blank=True, verbose_name="演示链接")
    url = models.URLField(
        blank=True,
        verbose_name="兼容主链接",
        help_text="历史数据兼容字段；新数据优先填写仓库链接或演示链接。",
    )
    cover = models.ImageField(
        upload_to=board_content_cover_upload_to,
        validators=[validate_uploaded_image],
        blank=True,
        verbose_name="封面",
    )
    is_featured = models.BooleanField(default=False, verbose_name="精选")
    is_active = models.BooleanField(default=True, verbose_name="展示")
    order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "编码项目"
        verbose_name_plural = "编码项目"

    def __str__(self):
        return f"{self.index:02d} {self.name}"


class CodingPrinciple(FixedBoardContentModel):
    """Working Principles 中的一条原则。

    所属板块固定为 coding（由模型类型决定，不可在 Admin 手动选择）。
    """

    BOARD_SLUG = "coding"

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="principles",
        verbose_name="板块",
        default=_board_default("coding"),
        help_text="由模型类型固定为 coding，不可手动选择",
    )
    index = models.PositiveSmallIntegerField(verbose_name="序号")
    title = models.CharField(max_length=64, verbose_name="原则标题")
    body = models.TextField(blank=True, verbose_name="原则正文")
    order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "编码原则"
        verbose_name_plural = "编码原则"

    def __str__(self):
        return f"{self.index:02d} {self.title}"


class CodingExperiment(FixedBoardContentModel):
    """Small Experiments 中的一次小型实验。

    所属板块固定为 coding（由模型类型决定，不可在 Admin 手动选择）。
    """

    BOARD_SLUG = "coding"

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="experiments",
        verbose_name="板块",
        default=_board_default("coding"),
        help_text="由模型类型固定为 coding，不可手动选择",
    )
    date = models.DateField(verbose_name="日期")
    title = models.CharField(max_length=128, verbose_name="实验名")
    order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")

    class Meta:
        ordering = ["-date", "pk"]
        verbose_name = "小型实验"
        verbose_name_plural = "小型实验"

    def __str__(self):
        return f"{self.date} {self.title}"


__all__ = [
    "Board",
    "BoardMembership",
    "BoardAccessRequest",
    "FixedBoardContentModel",
    "SkateHomie",
    "SkateClip",
    "ClipCategory",
    "ClipStatus",
    "HudType",
    "Stance",
    "MusicScope",
    "MusicRecordBase",
    "SpotifyRecord",
    "AppleRecord",
    "CodingProject",
    "CodingPrinciple",
    "CodingExperiment",
]
