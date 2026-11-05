from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar, cast

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .core.differ import build_stats, diff_sentences, summarize
from .forms import (
    AnnotationForm,
    AnnotationReplyForm,
    AnnotationStatusForm,
    DiffSelectionForm,
    DocumentUploadForm,
    VersionCommitForm,
    VersionUploadForm,
)
from .models import Annotation, Document, Version
from .permissions import can_use_padif
from .services import (
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
    documents = Document.objects.select_related("current_version", "created_by")
    return render(
        request,
        "padif/workspace.html",
        {"documents": documents, "document_form": document_form},
    )


def _document_context(
    document: Document,
    *,
    commit_form: VersionCommitForm | None = None,
    upload_form: VersionUploadForm | None = None,
    annotation_form: AnnotationForm | None = None,
) -> dict[str, object]:
    current_content = document.current_version.content if document.current_version else ""
    annotations = (
        document.current_version.annotations.select_related("author")
        .prefetch_related("replies__author")
        .all()
        if document.current_version
        else []
    )
    return {
        "document": document,
        "current_version": document.current_version,
        "annotations": annotations,
        "documents": Document.objects.select_related("current_version", "created_by"),
        "document_form": DocumentUploadForm(),
        "commit_form": commit_form
        or VersionCommitForm(initial={"content": current_content, "version_kind": "patch"}),
        "upload_form": upload_form or VersionUploadForm(initial={"version_kind": "patch"}),
        "annotation_form": annotation_form or AnnotationForm(),
        "diff_form": DiffSelectionForm(document=document),
    }


@padif_access_required
def document_detail(request: HttpRequest, document_id: int) -> HttpResponse:
    document = get_object_or_404(
        Document.objects.select_related("current_version", "created_by"),
        pk=document_id,
    )
    return render(request, "padif/document_detail.html", _document_context(document))


@padif_access_required
def commit_version(request: HttpRequest, document_id: int) -> HttpResponse:
    if request.method != "POST":
        raise PermissionDenied
    document = get_object_or_404(Document, pk=document_id)
    form = VersionCommitForm(request.POST)
    if form.is_valid():
        result = commit_document_version(
            document_id=document.pk,
            user=request.user,
            content=form.cleaned_data["content"],
            commit_message=form.cleaned_data["commit_message"],
            version_kind=form.cleaned_data["version_kind"],
        )
        if result.gentle_warning:
            messages.warning(request, "本次改动可能只有空白或标点差异，版本仍已保存。")
        messages.success(request, f"已保存 v{result.version.semantic_version}。")
        return redirect("padif:document_detail", document_id=document.pk)
    return render(
        request,
        "padif/document_detail.html",
        _document_context(document, commit_form=form),
        status=400,
    )


@padif_access_required
def upload_version(request: HttpRequest, document_id: int) -> HttpResponse:
    if request.method != "POST":
        raise PermissionDenied
    document = get_object_or_404(
        Document.objects.select_related("current_version", "created_by"),
        pk=document_id,
    )
    form = VersionUploadForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            source_name, content = read_markdown_upload(form.cleaned_data["markdown_file"])
        except ValidationError as exc:
            form.add_error("markdown_file", exc)
        else:
            result = commit_document_version(
                document_id=document.pk,
                user=request.user,
                content=content,
                commit_message=form.cleaned_data["commit_message"],
                version_kind=form.cleaned_data["version_kind"],
            )
            if result.gentle_warning:
                messages.warning(request, "该文件与上一版可能只有空白或标点差异，版本仍已保存。")
            messages.success(
                request,
                f"已将 {source_name} 添加为 v{result.version.semantic_version}。",
            )
            return redirect("padif:document_detail", document_id=document.pk)
    return render(
        request,
        "padif/document_detail.html",
        _document_context(document, upload_form=form),
        status=400,
    )


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
        return redirect("padif:document_detail", document_id=document.pk)
    return render(
        request,
        "padif/document_detail.html",
        _document_context(document, annotation_form=form),
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
        return redirect("padif:document_detail", document_id=document.pk)
    return render(
        request,
        "padif/document_detail.html",
        _document_context(document),
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
        return redirect("padif:document_detail", document_id=document.pk)
    return render(
        request,
        "padif/document_detail.html",
        _document_context(document),
        status=400,
    )
