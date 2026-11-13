from __future__ import annotations

from functools import wraps
from urllib.parse import urlencode
from typing import Callable, TypeVar, cast

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Max, Q
from django.db.models.functions import Coalesce
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse

from .core.differ import build_stats, diff_sentences, summarize
from .forms import (
    BranchCreateForm,
    BranchPublishForm,
    AnnotationForm,
    AnnotationReplyForm,
    AnnotationStatusForm,
    DiffSelectionForm,
    DocumentUploadForm,
    VersionCommitForm,
    VersionUploadForm,
)
from .models import Annotation, Document, Version
from .permissions import can_use_padif, visible_documents, require_document, document_role
from .worldlines import build_worldlines
from .services import (
    BranchError,
    archive_branch as archive_branch_service,
    create_branch as create_branch_service,
    publish_branch as publish_branch_service,
    effective_head,
    resolve_branch,
    commit_document_version,
    create_document_from_upload,
    read_markdown_upload,
)

ViewFunction = TypeVar("ViewFunction", bound=Callable[..., HttpResponse])


def padif_access_required(view: ViewFunction) -> ViewFunction:
    @wraps(view)
    def wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not can_use_padif(request.user):
            raise PermissionDenied("你尚未获得 PAdif 使用权限。")
        document_id = kwargs.get('document_id')
        if document_id is None:
            return view(request, *args, **kwargs)
        with transaction.atomic():
            queryset = visible_documents(request.user)
            if request.method == 'POST':
                queryset = Document.objects.select_for_update().filter(pk__in=queryset.values('pk'))
            document = get_object_or_404(queryset, pk=document_id)
            require_document(request.user, document, write=request.method == 'POST', owner=view.__name__ == 'publish_branch')
            return view(request, *args, **kwargs)

    return cast(ViewFunction, wrapped)


@padif_access_required
def workspace(request: HttpRequest) -> HttpResponse:
    document_form = DocumentUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and document_form.is_valid():
        try:
            result = create_document_from_upload(
                user=request.user,
                upload=document_form.cleaned_data["markdown_file"],
                title=document_form.cleaned_data["title"],
                commit_message=document_form.cleaned_data["commit_message"],
            )
        except ValidationError as exc:
            document_form.add_error("markdown_file", exc)
        else:
            messages.success(request, "文档已导入，初始版本为 v1.0.0。")
            return redirect("padif:document_detail", document_id=result.document.pk)
    documents = visible_documents(request.user).select_related("current_version", "created_by")
    return render(
        request,
        "padif/workspace.html",
        {"documents": documents, "document_form": document_form},
    )


def _selected_branch(document, request):
    try:
        if request.method == "POST" and "branch_id" in request.POST:
            raw = request.POST["branch_id"]
            if not raw.isdigit() or int(raw) < 1:
                raise Http404("分支不存在。")
            return resolve_branch(document, branch_id=int(raw))
        return resolve_branch(document, name=request.GET.get("branch", request.POST.get("branch_context")))
    except BranchError as exc:
        raise Http404(exc.messages[0]) from exc


def _branch_redirect(document, branch):
    url = reverse("padif:document_detail", args=[document.pk])
    return redirect(url if branch.is_default else url + "?" + urlencode({"branch": branch.name}))


def _version_rail_context(document, selected, *, full_history=False, viewed=None):
    main = resolve_branch(document)
    branches = list(document.branches.filter(is_default=False).select_related("forked_from__branch").annotate(
        last_activity=Coalesce(Max("versions__created_at"), F("created_at")),
        latest_version_id=Max("versions__id"),
    ).order_by("-last_activity", "-pk"))
    candidates = [item for item in branches if item.archived_at is None or item.pk == selected.pk]
    visible = candidates[:3]
    if not selected.is_default and selected.pk not in {item.pk for item in visible}:
        visible = candidates[:2] + [next(item for item in branches if item.pk == selected.pk)]
        visible.sort(key=lambda item: (item.last_activity, item.pk), reverse=True)
    heads = {item.pk: item for item in document.versions.filter(
        pk__in=[item.latest_version_id for item in visible if item.latest_version_id]
    ).select_related("created_by")}
    # Read only ancestry metadata, not the manuscripts of every branch.
    ancestry = {pk: (branch_id, parent_id) for pk, branch_id, parent_id in
                document.versions.values_list("pk", "branch_id", "parent_id")}
    attached = {}
    unattached = []
    for item in visible:
        anchor = item.forked_from_id
        visited = set()
        while anchor in ancestry and ancestry[anchor][0] != main.pk and anchor not in visited:
            visited.add(anchor)
            anchor = ancestry[anchor][1]
        card = {"branch": item, "head": heads.get(item.latest_version_id), "selected": item.pk == selected.pk}
        if anchor in ancestry and ancestry[anchor][0] == main.pk:
            attached.setdefault(anchor, []).append(card)
        else:
            unattached.append(card)
    main_versions = main.versions.select_related("created_by", "branch").order_by("-id")
    latest = list(main_versions if full_history else main_versions[:5])
    shown = {item.pk for item in latest}
    anchors = list(main_versions.filter(pk__in=set(attached) - shown))
    if viewed and viewed.branch_id == main.pk and viewed.pk not in {item.pk for item in latest + anchors}:
        anchors.append(viewed)
    rows = [{"version": item, "anchor_only": item.pk not in shown, "branches": attached.get(item.pk, [])}
            for item in sorted(latest + anchors, key=lambda item: item.pk, reverse=True)]
    recent_versions = []
    for item in visible:
        recent_versions.extend(item.versions.select_related("branch").defer("content").order_by("-id")[:3])
    if viewed and viewed.branch_id != main.pk:
        recent_versions.append(viewed)
    selected_card = next((card for card in [item for group in attached.values() for item in group] + unattached if card["selected"]), None)
    cards = [item for group in attached.values() for item in group] + unattached
    return {
        "worldlines": build_worldlines(main, rows, cards, recent_versions), "rail_selected_card": selected_card,
        "rail_main": main, "rail_rows": rows, "rail_unattached": unattached,
        "rail_visible_count": len(visible), "rail_branch_total": len(branches),
        "rail_all_branches": branches, "rail_full_history": full_history,
        "rail_has_older": not full_history and main.versions.count() > 5,
    }


def _article_access_state(document, user):
    from .access_presentation import article_access_state
    return article_access_state(user, document_role(user, document),
        document.agent_grants.filter(user=user).first(),
        document.agent_requests.filter(applicant=user, status='pending').first())


def _document_context(document, *, user, branch=None, viewed=None, commit_form=None, upload_form=None, annotation_form=None, full_history=False):
    branch = branch or resolve_branch(document)
    head = effective_head(branch)
    current = viewed or head
    bound_draft = bool(commit_form is not None and commit_form.is_bound)
    if bound_draft:
        raw_base = commit_form.data.get('base_version_id', '')
        if str(raw_base).isascii() and str(raw_base).isdecimal() and len(str(raw_base)) <= 19 and 0 < int(raw_base) < 2**63:
            original = document.versions.filter(Q(branch=branch) | Q(pk=branch.forked_from_id), pk=int(raw_base)).first()
            current = original or current
    historical = bool(current and head and current.pk != head.pk)
    conflicted = historical and bound_draft
    initial = {"branch_id": branch.pk, "base_version_id": current.pk if current else None, "version_kind": "patch"}
    diff_initial = {"mode": "inline"}
    if current and current.parent_id:
        diff_initial.update(from_version=current.parent_id, to_version=current.pk)
    access = _article_access_state(document, user)
    return {
        **_version_rail_context(document, branch, full_history=full_history, viewed=current),
        "document": document, "current_version": current, "selected_branch": branch,
        "head_version": head, "is_historical": historical,
        "editor_conflicted": conflicted, "editor_bound_draft": bound_draft,
        "editor_branches": document.branches.all(),
        "editor_versions": document.versions.filter(Q(branch=branch) | Q(pk=branch.forked_from_id)).select_related('branch').defer('content').order_by('-pk'),
        "branches": document.branches.filter(archived_at__isnull=True),
        "archived_branches": document.branches.filter(archived_at__isnull=False),
        "branch_versions": branch.versions.select_related("created_by").prefetch_related("forked_branches"),
        "annotations": current.annotations.select_related("author").prefetch_related("replies__author").all() if current else [],
        "documents": visible_documents(user).select_related("current_version", "created_by"),
        "document_role": document_role(user, document),
        "can_manage_collaboration": document.created_by_id == user.pk,
        "can_write_document": document_role(user, document) in {'owner', 'collaborator'},
        "can_edit_version": not branch.archived_at and (not historical or conflicted) and (document_role(user, document) == 'owner' or (document_role(user, document) == 'collaborator' and not branch.is_default)),
        "document_ai_enabled": access['effective'],
        "ai_access": access,
        "document_form": DocumentUploadForm(),
        "commit_form": commit_form if commit_form is not None else VersionCommitForm(initial={**initial, "content": current.content if current else ""}),
        "upload_form": upload_form if upload_form is not None else VersionUploadForm(document=document, initial=initial),
        "annotation_form": annotation_form if annotation_form is not None else AnnotationForm(),
        "diff_form": DiffSelectionForm(document=document, initial=diff_initial),
    }


@padif_access_required
def document_detail(request, document_id):
    document = get_object_or_404(Document, pk=document_id)
    branch = _selected_branch(document, request)
    viewed = None
    raw_version = request.GET.get('version')
    if raw_version is not None:
        if not raw_version.isascii() or not raw_version.isdecimal() or len(raw_version) > 19 or not 0 < int(raw_version) < 2**63:
            raise Http404('版本不存在。')
        viewed = get_object_or_404(document.versions.select_related('branch'), pk=int(raw_version))
        if 'branch' not in request.GET:
            branch = viewed.branch
        if viewed.branch_id != branch.pk and viewed.pk != branch.forked_from_id:
            raise Http404('版本不属于所选分支。')
    return render(request, "padif/document_detail.html", _document_context(
        document, user=request.user, branch=branch, viewed=viewed, full_history=request.GET.get("history") == "all",
    ))


def _commit_response(request, document_id, *, upload=False):
    if request.method != "POST":
        return HttpResponse(status=405)
    document = get_object_or_404(Document, pk=document_id)
    branch = _selected_branch(document, request)
    form = VersionUploadForm(request.POST, request.FILES, document=document) if upload else VersionCommitForm(request.POST)
    status = 400
    if form.is_valid():
        if upload and form.cleaned_data.get("target_branch") is not None:
            branch = form.cleaned_data["target_branch"]
        try:
            content = read_markdown_upload(form.cleaned_data["markdown_file"])[1] if upload else form.cleaned_data["content"]
            result = commit_document_version(
                document_id=document.pk, user=request.user, content=content,
                commit_message=form.cleaned_data["commit_message"], version_kind=form.cleaned_data["version_kind"],
                branch_id=branch.pk, base_version_id=form.cleaned_data["base_version_id"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            status = getattr(exc, "status", 400)
        else:
            if not upload and request.POST.get('draft_revision'):
                from uuid import UUID
                from .models import EditorDraft
                try:
                    revision = UUID(request.POST['draft_revision'])
                except ValueError:
                    revision = None
                if revision:
                    EditorDraft.objects.filter(user=request.user, document=document, branch=branch,
                        base_version_id=form.cleaned_data['base_version_id'], revision=revision,
                        content=form.cleaned_data['content']).delete()
            if result.gentle_warning:
                messages.warning(request, "本次改动可能只有空白或标点差异，版本仍已保存。")
            messages.success(request, f"已保存 v{result.version.semantic_version} · {branch.name}。")
            return _branch_redirect(document, branch)
    kwargs = {"upload_form" if upload else "commit_form": form}
    return render(request, "padif/document_detail.html", _document_context(document, user=request.user, branch=branch, **kwargs), status=status)


@padif_access_required
def commit_version(request, document_id):
    return _commit_response(request, document_id)


@padif_access_required
def upload_version(request, document_id):
    return _commit_response(request, document_id, upload=True)


@padif_access_required
def create_branch(request, document_id):
    if request.method != "POST":
        return HttpResponse(status=405)
    document = get_object_or_404(Document, pk=document_id)
    form = BranchCreateForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            branch = create_branch_service(document_id=document.pk, user=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
            status = getattr(exc, "status", 400)
        else:
            messages.success(request, f"已创建分支 {branch.name}。")
            return _branch_redirect(document, branch)
    return render(request, "padif/branch_action.html", {"document": document, "form": form, "action_title": "创建分支"}, status=status)


@padif_access_required
def publish_branch(request, document_id, branch_id):
    document = get_object_or_404(Document, pk=document_id)
    branch = get_object_or_404(document.branches, pk=branch_id)
    if request.method not in {"GET", "POST"}:
        return HttpResponse(status=405)
    main = effective_head(resolve_branch(document))
    source = branch.versions.order_by("-id").first()
    if branch.is_default or not source or branch.archived_at:
        return HttpResponse("该分支不能发布。", status=409 if branch.archived_at else 400)
    form = BranchPublishForm(request.POST if request.method == "POST" else None, initial={"base_version_id": main.pk if main else None, "source_version_id": source.pk, "version_kind": "patch"})
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                result = publish_branch_service(document_id=document.pk, branch_id=branch.pk, user=request.user, **form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc)
                status = getattr(exc, "status", 400)
            else:
                messages.success(request, f"已发布 {branch.name} 为主线 v{result.version.semantic_version}。")
                return redirect("padif:document_detail", document_id=document.pk)
    return render(request, "padif/branch_action.html", {"document": document, "branch": branch, "form": form, "action_title": "发布到主线", "publish": True, "stale": status == 409, "main_head": main, "source_head": source}, status=status)


@padif_access_required
def archive_branch(request, document_id, branch_id):
    document = get_object_or_404(Document, pk=document_id)
    branch = get_object_or_404(document.branches, pk=branch_id)
    if request.method not in {"GET", "POST"}:
        return HttpResponse(status=405)
    if branch.is_default:
        return HttpResponse("主线不能归档。", status=400)
    if request.method == "POST":
        archive_branch_service(document_id=document.pk, branch_id=branch.pk, user=request.user)
        messages.success(request, f"分支 {branch.name} 已归档，历史和批注仍保留。")
        return redirect("padif:document_detail", document_id=document.pk)
    return render(request, "padif/branch_action.html", {"document": document, "branch": branch, "action_title": "归档分支"})


@padif_access_required
def diff_fragment(request: HttpRequest, document_id: int) -> HttpResponse:
    document = get_object_or_404(Document, pk=document_id)
    form = DiffSelectionForm(request.GET, document=document)
    if not form.is_valid():
        return render(request, "padif/diff_errors.html", {"form": form}, status=400)
    old = form.cleaned_data["from_version"]
    new = form.cleaned_data["to_version"]
    ops = diff_sentences(old.content, new.content)
    old_cursor = 0
    new_cursor = 0
    old_lines = old.content.replace("\r\n", "\n").split("\n")
    new_lines = new.content.replace("\r\n", "\n").split("\n")
    for op in ops:
        text = getattr(op, "text", "")
        if op.op in {"delete", "replace"}:
            for index in range(old_cursor, len(old_lines)):
                if text and text.strip() in old_lines[index]:
                    op.old_line = index + 1
                    old_cursor = index
                    break
        if op.op in {"insert", "replace", "moved", "equal"}:
            for index in range(new_cursor, len(new_lines)):
                if text and text.strip() in new_lines[index]:
                    op.new_line = index + 1
                    new_cursor = index
                    break
    context = {
        "old": old,
        "new": new,
        "mode": form.cleaned_data["mode"],
        "ops": ops,
        "stats": build_stats(old.content, new.content),
        "old_summary": summarize(old.content),
        "new_summary": summarize(new.content),
    }
    return render(request, "padif/diff_fragment.html", context)


@padif_access_required
def create_annotation(request: HttpRequest, document_id: int, version_id: int) -> HttpResponse:
    if request.method != "POST":
        raise PermissionDenied
    document = get_object_or_404(Document, pk=document_id)
    version = get_object_or_404(Version, pk=version_id, document=document)
    form = AnnotationForm(request.POST)
    if form.is_valid():
        annotation = form.save(commit=False)
        annotation.version = version
        annotation.author = request.user
        annotation.save()
        messages.success(request, "批注已添加。")
        return _branch_redirect(document, _selected_branch(document, request))
    return render(
        request,
        "padif/document_detail.html",
        _document_context(document, user=request.user, branch=_selected_branch(document, request), annotation_form=form),
        status=400,
    )


@padif_access_required
def update_annotation(request: HttpRequest, document_id: int, annotation_id: int) -> HttpResponse:
    if request.method != "POST":
        raise PermissionDenied
    document = get_object_or_404(Document, pk=document_id)
    annotation = get_object_or_404(
        Annotation.objects.filter(version__document=document),
        pk=annotation_id,
    )
    form = AnnotationStatusForm(request.POST)
    if form.is_valid():
        annotation.status = form.cleaned_data["status"]
        annotation.resolution_note = form.cleaned_data["resolution_note"]
        annotation.resolved_by = request.user
        annotation.resolved_at = timezone.now()
        annotation.save(
            update_fields=[
                "status",
                "resolution_note",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )
        messages.success(request, f"批注已标记为{annotation.get_status_display()}。")
        return _branch_redirect(document, _selected_branch(document, request))
    return render(
        request,
        "padif/document_detail.html",
        _document_context(document, user=request.user, branch=_selected_branch(document, request)),
        status=400,
    )


@padif_access_required
def create_annotation_reply(request: HttpRequest, document_id: int, annotation_id: int) -> HttpResponse:
    if request.method != "POST":
        raise PermissionDenied
    document = get_object_or_404(Document, pk=document_id)
    annotation = get_object_or_404(
        Annotation.objects.filter(version__document=document),
        pk=annotation_id,
    )
    form = AnnotationReplyForm(request.POST)
    if form.is_valid():
        reply = form.save(commit=False)
        reply.annotation = annotation
        reply.author = request.user
        reply.save()
        messages.success(request, "批注回复已添加。")
        return _branch_redirect(document, _selected_branch(document, request))
    return render(
        request,
        "padif/document_detail.html",
        _document_context(document, user=request.user, branch=_selected_branch(document, request)),
        status=400,
    )
