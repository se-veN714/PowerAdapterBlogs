from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.forms import Form, modelform_factory
from django.http import Http404
from django.urls import reverse
from django.views.generic import (
    CreateView,
    DeleteView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from boards.content_forms import (
    CodingProjectForm,
    MusicRecordForm,
    SkateClipForm,
    SkateClipMediaUploadForm,
)
from boards.models import (
    AppleRecord,
    Board,
    CodingProject,
    SkateClip,
    SkateClipMedia,
    SpotifyRecord,
)
from boards.policies import can_manage_board_content
from boards.skate_upload import (
    SkateUploadRejected,
    ingest_skate_source,
    requeue_existing_skate_source,
)


MUSIC_MODELS = {
    "spotify": SpotifyRecord,
    "apple": AppleRecord,
}


class BoardContentManagerMixin(LoginRequiredMixin):
    board_slug = None
    board = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        try:
            self.board = Board.objects.get(slug=self.board_slug, is_active=True)
        except Board.DoesNotExist as exc:
            raise PermissionDenied("目标板块不可用。") from exc
        if not can_manage_board_content(request.user, self.board):
            raise PermissionDenied("当前账号没有该板块的内容管理权限。")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["board"] = self.board
        return context


class MusicModelMixin(BoardContentManagerMixin):
    board_slug = "music"
    provider = None
    form_class = MusicRecordForm

    def dispatch(self, request, *args, **kwargs):
        self.provider = kwargs.get("provider")
        if self.provider not in MUSIC_MODELS:
            raise PermissionDenied("未知音乐数据来源。")
        self.model = MUSIC_MODELS[self.provider]
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.model.objects.filter(board=self.board)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["provider"] = self.provider
        return context

    def get_success_url(self):
        return reverse("boards:music-manage-list", args=[self.provider])


class MusicRecordListView(MusicModelMixin, ListView):
    template_name = "pages/boards/manage/music/list.html"
    context_object_name = "records"
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().order_by(
            "-year",
            "-month",
            "display_order",
            "pk",
        )
        query = self.request.GET.get(
            "query",
            self.request.GET.get("q", ""),
        ).strip()
        year = self.request.GET.get("year", "").strip()
        month = self.request.GET.get("month", "").strip()
        kind = self.request.GET.get("kind", "").strip()
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(label__icontains=query)
                | Q(value__icontains=query)
            )
        if year.isdigit():
            queryset = queryset.filter(year=int(year))
        if month.isdigit():
            queryset = queryset.filter(month=int(month))
        if kind:
            queryset = queryset.filter(kind=kind)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["records"] = context["page_obj"]
        context["filters"] = {
            "query": self.request.GET.get(
                "query",
                self.request.GET.get("q", ""),
            ),
            "year": self.request.GET.get("year", ""),
            "month": self.request.GET.get("month", ""),
            "kind": self.request.GET.get("kind", ""),
        }
        context["can_create"] = True
        return context


class MusicRecordCreateView(MusicModelMixin, CreateView):
    template_name = "pages/boards/manage/music/form.html"

    def get_form_class(self):
        return modelform_factory(self.model, form=MusicRecordForm)

    def form_valid(self, form):
        form.instance.board = self.board
        messages.success(self.request, "音乐记录已创建。")
        return super().form_valid(form)


class MusicRecordUpdateView(MusicModelMixin, UpdateView):
    template_name = "pages/boards/manage/music/form.html"

    def get_form_class(self):
        return modelform_factory(self.model, form=MusicRecordForm)

    def form_valid(self, form):
        form.instance.board = self.board
        messages.success(self.request, "音乐记录已更新。")
        return super().form_valid(form)


class MusicRecordDeleteView(MusicModelMixin, DeleteView):
    template_name = "pages/boards/manage/music/delete_confirm.html"
    form_class = Form

    def form_valid(self, form):
        messages.success(self.request, "音乐记录已删除。")
        return super().form_valid(form)


class SkateClipMixin(BoardContentManagerMixin):
    board_slug = "skateboard"
    model = SkateClip
    form_class = SkateClipForm

    def get_queryset(self):
        return (
            SkateClip.objects.filter(homie__board=self.board)
            .select_related("homie", "media")
        )

    def get_success_url(self):
        return reverse("boards:skate-manage-list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clip = context.get("object")
        try:
            existing_media = clip.media if clip and clip.pk else None
        except SkateClipMedia.DoesNotExist:
            existing_media = None
        context.update(
            {
                "max_upload_bytes": settings.SKATE_CLIP_MAX_UPLOAD_BYTES,
                "max_upload_mib": settings.SKATE_CLIP_MAX_UPLOAD_BYTES // (1024 * 1024),
                "max_duration_ms": settings.SKATE_CLIP_MAX_DURATION_MS,
                "amap_enabled": bool(
                    settings.AMAP_JS_API_ENABLED
                    and settings.AMAP_JS_API_KEY
                    and settings.AMAP_JS_SECURITY_JSCODE
                ),
                "amap_api_key": settings.AMAP_JS_API_KEY,
                "amap_service_host": settings.AMAP_JS_SERVICE_HOST,
                "existing_media": existing_media,
            }
        )
        return context


class SkateClipFormMediaMixin:
    """Add optional source ingestion to the normal clip CRUD form."""

    def form_valid(self, form):
        creating = getattr(self, "object", None) is None
        process_requested = self.request.POST.get("intent") == "process"
        source = form.cleaned_data.get("source") if process_requested else None
        has_existing_source = bool(
            not creating
            and SkateClipMedia.objects.filter(
                clip=self.object,
                source_file__gt="",
            ).exists()
        )
        if process_requested and not source and not has_existing_source:
            form.add_error("source", "上传并处理需要选择一个视频原片。")
            return self.form_invalid(form)
        if (
            process_requested
            and source
            and getattr(self, "object", None) is not None
            and SkateClipMedia.objects.filter(clip=self.object).exists()
            and not form.cleaned_data.get("confirm_replace")
        ):
            form.add_error(
                "confirm_replace",
                "该 Clip 已有一个源视频。请确认替换；系统不会追加第二个视频。",
            )
            return self.form_invalid(form)

        response = super().form_valid(form)
        if source:
            try:
                ingest_skate_source(
                    clip=self.object,
                    uploaded=source,
                    uploaded_by=self.request.user,
                )
            except SkateUploadRejected as exc:
                # 元数据保留为私有草稿，避免上传失败后公开一个无媒体占位。
                if not self.object.video_url and self.object.is_public:
                    self.object.is_public = False
                    self.object.save(update_fields=["is_public", "updated_at"])
                messages.error(
                    self.request,
                    f"片段资料已保存为私有草稿，但原片被拒绝：{exc.public_message}",
                )
            else:
                messages.success(
                    self.request,
                    f"滑板片段已{'创建' if creating else '更新'}；原片校验通过，已进入待处理队列。",
                )
        elif process_requested:
            try:
                requeue_existing_skate_source(clip=self.object)
            except SkateUploadRejected as exc:
                messages.error(
                    self.request,
                    f"片段资料已更新，但无法重新排队：{exc.public_message}",
                )
            else:
                messages.success(
                    self.request,
                    "滑板片段已更新；现有私有原片已重新进入待处理队列。",
                )
        else:
            messages.success(
                self.request,
                f"滑板片段已{'创建' if creating else '更新'}。",
            )
        return response


class SkateClipManageListView(SkateClipMixin, ListView):
    template_name = "pages/boards/manage/skateboard/list.html"
    context_object_name = "records"
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().order_by(
            "homie__node_index",
            "order",
            "pk",
        )
        query = self.request.GET.get("query", "").strip()
        homie = self.request.GET.get("homie", "").strip()
        status = self.request.GET.get("status", "").strip()
        visibility = self.request.GET.get("visibility", "").strip()
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(spot__icontains=query)
                | Q(notes__icontains=query)
            )
        if homie.isdigit():
            queryset = queryset.filter(homie_id=int(homie))
        if status:
            queryset = queryset.filter(status=status)
        if visibility == "public":
            queryset = queryset.filter(is_public=True)
        elif visibility == "private":
            queryset = queryset.filter(is_public=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["records"] = context["page_obj"]
        context["homies"] = self.board.homies.order_by("node_index", "pk")
        context["filters"] = {
            "query": self.request.GET.get("query", ""),
            "homie": self.request.GET.get("homie", ""),
            "status": self.request.GET.get("status", ""),
            "visibility": self.request.GET.get("visibility", ""),
        }
        context["can_create"] = True
        return context


class SkateClipCreateView(SkateClipFormMediaMixin, SkateClipMixin, CreateView):
    template_name = "pages/boards/manage/skateboard/form.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["homie"].queryset = self.board.homies.order_by(
            "node_index",
            "pk",
        )
        return form

class SkateClipUpdateView(SkateClipFormMediaMixin, SkateClipMixin, UpdateView):
    template_name = "pages/boards/manage/skateboard/form.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["homie"].queryset = self.board.homies.order_by(
            "node_index",
            "pk",
        )
        return form

class SkateClipDeleteView(SkateClipMixin, DeleteView):
    template_name = "pages/boards/manage/skateboard/delete_confirm.html"
    form_class = Form

    def form_valid(self, form):
        messages.success(self.request, "滑板片段已删除。")
        return super().form_valid(form)


class SkateClipMediaUploadView(SkateClipMixin, FormView):
    """对已存在 Clip 上传或替换私有原片（S1 三层校验的服务端核心）。

    流程：Policy 鉴权 → 大小快速失败 → 写入私有存储（UUID 名）→
    FFprobe 权威裁决 → 通过才落库（uploaded 状态 + 探测元数据）。
    FFprobe 失败时删除已写文件并把有界错误码回显给管理员；
    数据库写入为短事务，探测与文件 IO 均在事务外。
    """

    template_name = "pages/boards/manage/skateboard/media_upload.html"
    form_class = SkateClipMediaUploadForm

    def _load_clip(self):
        # self.board 由基类 dispatch（set_common_data）就绪后再查询。
        self.clip = (
            SkateClip.objects.filter(homie__board=self.board)
            .select_related("homie")
            .filter(pk=self.kwargs.get("pk"))
            .first()
        )
        if self.clip is None:
            raise Http404("Clip 不存在。")

    def get(self, request, *args, **kwargs):
        self._load_clip()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self._load_clip()
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["replacing"] = SkateClipMedia.objects.filter(clip=self.clip).exists()
        return kwargs

    def form_valid(self, form):
        try:
            ingest_skate_source(
                clip=self.clip,
                uploaded=form.cleaned_data["source"],
                uploaded_by=self.request.user,
            )
        except SkateUploadRejected as exc:
            messages.error(self.request, f"上传被拒绝：{exc.public_message}")
            return self.form_invalid(form)

        messages.success(
            self.request,
            "原片已上传并校验通过，已进入待处理队列。",
        )
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["clip"] = self.clip
        try:
            media = self.clip.media
        except SkateClipMedia.DoesNotExist:
            media = None
        context["media"] = media
        context["max_upload_bytes"] = settings.SKATE_CLIP_MAX_UPLOAD_BYTES
        context["max_upload_mib"] = settings.SKATE_CLIP_MAX_UPLOAD_BYTES // (1024 * 1024)
        context["max_duration_ms"] = settings.SKATE_CLIP_MAX_DURATION_MS
        return context


class CodingProjectMixin(BoardContentManagerMixin):
    board_slug = "coding"
    model = CodingProject
    form_class = CodingProjectForm

    def get_queryset(self):
        return CodingProject.objects.filter(board=self.board)

    def get_success_url(self):
        return reverse("boards:coding-manage-list")


class CodingProjectListView(CodingProjectMixin, ListView):
    template_name = "pages/boards/manage/coding/list.html"
    context_object_name = "records"
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().order_by("order", "pk")
        query = self.request.GET.get(
            "query",
            self.request.GET.get("q", ""),
        ).strip()
        project_type = self.request.GET.get("project_type", "").strip()
        year = self.request.GET.get("year", "").strip()
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(stack__icontains=query)
            )
        if project_type in CodingProject.ProjectType.values:
            queryset = queryset.filter(project_type=project_type)
        if year.isdigit():
            queryset = queryset.filter(year=int(year))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["records"] = context["page_obj"]
        context["filters"] = {
            "query": self.request.GET.get(
                "query",
                self.request.GET.get("q", ""),
            ),
            "project_type": self.request.GET.get("project_type", ""),
            "year": self.request.GET.get("year", ""),
        }
        context["can_create"] = True
        return context


class CodingProjectCreateView(CodingProjectMixin, CreateView):
    template_name = "pages/boards/manage/coding/form.html"

    def form_valid(self, form):
        form.instance.board = self.board
        messages.success(self.request, "项目已创建。")
        return super().form_valid(form)


class CodingProjectUpdateView(CodingProjectMixin, UpdateView):
    template_name = "pages/boards/manage/coding/form.html"

    def form_valid(self, form):
        form.instance.board = self.board
        messages.success(self.request, "项目已更新。")
        return super().form_valid(form)


class CodingProjectDeleteView(CodingProjectMixin, DeleteView):
    template_name = "pages/boards/manage/coding/delete_confirm.html"
    form_class = Form

    def form_valid(self, form):
        messages.success(self.request, "项目已删除。")
        return super().form_valid(form)


class PadifLocalView(TemplateView):
    template_name = "pages/coding/padif_local.html"
