from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from .core.differ import build_stats
from .core.versioning import bump, gentle_warn, suggest_kind
from .models import Branch, Document, Version

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_SUFFIXES = {".md", ".markdown"}


class ActingUser(Protocol):
    pk: object


@dataclass(frozen=True)
class CommitResult:
    document: Document
    version: Version
    gentle_warning: bool
    suggested_kind: str


def read_markdown_upload(upload: UploadedFile) -> tuple[str, str]:
    source_name = Path(upload.name).name
    if Path(source_name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValidationError("仅支持 .md 或 .markdown 文件。")
    if upload.size is not None and upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("文件不能超过 2 MB。")

    data = bytearray()
    for chunk in upload.chunks():
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValidationError("文件不能超过 2 MB。")
    try:
        content = bytes(data).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("文件必须使用 UTF-8 编码。") from exc
    if not content.strip():
        raise ValidationError("文档内容不能为空。")
    return source_name, content


@transaction.atomic
def create_document_from_upload(
    *,
    user: ActingUser,
    upload: UploadedFile,
    title: str,
    commit_message: str,
) -> CommitResult:
    source_name, content = read_markdown_upload(upload)
    clean_title = title.strip() or Path(source_name).stem
    document = Document.objects.create(
        title=clean_title,
        source_name=source_name,
        created_by=user,
    )
    branch = Branch.objects.create(document=document, name="main", is_default=True, created_by=user)
    stats = build_stats("", content)
    version = Version.objects.create(
        document=document,
        branch=branch,
        content=content,
        commit_message=commit_message.strip(),
        semantic_version="1.0.0",
        version_kind=Version.Kind.MAJOR,
        diff_stats=stats,
        created_by=user,
    )
    document.current_version = version
    document.save(update_fields=["current_version", "updated_at"])
    return CommitResult(document, version, False, suggest_kind(stats))


class BranchError(ValidationError):
    def __init__(self, code, message, status=400, **details):
        super().__init__(message)
        self.error_code = code
        self.status = status
        self.details = details


def effective_head(branch):
    return branch.versions.order_by("-id").first() or branch.forked_from


def resolve_branch(document, *, branch_id=None, name=None):
    query = document.branches.all()
    if branch_id is not None:
        query = query.filter(pk=branch_id)
    elif name is not None:
        query = query.filter(name=name)
    else:
        query = query.filter(is_default=True)
    branch = query.first()
    if branch is None:
        raise BranchError("BRANCH_NOT_FOUND", "分支不存在。", 404)
    return branch


def _validate_commit(content, commit_message, version_kind):
    if not isinstance(content, str) or not content.strip():
        raise BranchError("INVALID_VERSION_INPUT", "正文不能为空。")
    if not isinstance(commit_message, str) or not commit_message.strip() or len(commit_message.strip()) > 300:
        raise BranchError("INVALID_VERSION_INPUT", "提交说明不能为空且不能超过 300 字符。")
    if version_kind not in Version.Kind.values:
        raise BranchError("INVALID_VERSION_KIND", "版本级别无效。")


def _append_version(document, branch, user, content, commit_message, version_kind):
    _validate_commit(content, commit_message, version_kind)
    previous = effective_head(branch)
    stats = build_stats(previous.content if previous else "", content)
    version = Version(
        document=document, branch=branch, parent=previous, content=content,
        commit_message=commit_message.strip(),
        semantic_version=bump(previous.semantic_version if previous else None, version_kind),
        version_kind=version_kind, diff_stats=stats, created_by=user,
    )
    version.full_clean()
    version.save()
    if branch.is_default:
        document.current_version = version
        document.save(update_fields=["current_version", "updated_at"])
    else:
        document.save(update_fields=["updated_at"])
    return CommitResult(document, version, gentle_warn(previous.content if previous else "", content), suggest_kind(stats))


@transaction.atomic
def commit_document_version(*, document_id, user, content, commit_message, version_kind,
                            branch_id=None, base_version_id=None):
    document = Document.objects.select_for_update().get(pk=document_id)
    branch = resolve_branch(document, branch_id=branch_id)
    if branch.archived_at:
        raise BranchError("BRANCH_ARCHIVED", "归档分支不能追加版本。", 409)
    previous = effective_head(branch)
    current_id = previous.pk if previous else None
    if base_version_id is not None and base_version_id != current_id:
        raise BranchError("STALE_BASE_VERSION", "目标分支已更新，请重新审阅后提交。", 409, current_version_id=current_id)
    return _append_version(document, branch, user, content, commit_message, version_kind)


@transaction.atomic
def create_branch(*, document_id, user, name, fork_from_version_id, description=""):
    document = Document.objects.select_for_update().get(pk=document_id)
    source = document.versions.filter(pk=fork_from_version_id).first()
    if source is None:
        raise BranchError("VERSION_NOT_FOUND", "分叉源不存在。", 404)
    if document.branches.filter(name=name).exists():
        raise BranchError("BRANCH_NAME_EXISTS", "分支名称已存在。", 409)
    branch = Branch(document=document, name=name, description=description, forked_from=source, created_by=user)
    branch.full_clean()
    branch.save()
    return branch


@transaction.atomic
def publish_branch(*, document_id, branch_id, user, commit_message, version_kind,
                   base_version_id, source_version_id, confirm_replace):
    document = Document.objects.select_for_update().get(pk=document_id)
    branch = resolve_branch(document, branch_id=branch_id)
    if branch.is_default:
        raise BranchError("DEFAULT_BRANCH", "不能将主线发布到自身。")
    if branch.archived_at:
        raise BranchError("BRANCH_ARCHIVED", "归档分支不能发布。", 409)
    source = branch.versions.order_by("-id").first()
    if source is None:
        raise BranchError("EMPTY_BRANCH", "分支无新版本可发布。")
    if confirm_replace is not True or type(base_version_id) is not int or type(source_version_id) is not int:
        raise BranchError("CONFIRMATION_REQUIRED", "请审阅两端版本并确认整稿替换。")
    main = resolve_branch(document)
    target = effective_head(main)
    if (target.pk if target else None) != base_version_id:
        raise BranchError("STALE_BASE_VERSION", "主线已更新，请重新审阅。", 409, current_version_id=target.pk if target else None)
    if source.pk != source_version_id:
        raise BranchError("STALE_SOURCE_VERSION", "源分支已更新，请重新审阅。", 409, source_version_id=source.pk)
    _validate_commit(source.content, commit_message, version_kind)
    return _append_version(document, main, user, source.content, f"publish(branch={branch.name}): {commit_message}", version_kind)


@transaction.atomic
def archive_branch(*, document_id, branch_id, user):
    document = Document.objects.select_for_update().get(pk=document_id)
    branch = resolve_branch(document, branch_id=branch_id)
    if branch.is_default:
        raise BranchError("DEFAULT_BRANCH", "主线不能归档。")
    if branch.archived_at is None:
        branch.archived_at = timezone.now()
        branch.save(update_fields=["archived_at"])
    return branch
