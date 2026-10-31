from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from .core.differ import build_stats
from .core.versioning import bump, gentle_warn, suggest_kind
from .models import Document, Version

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
    stats = build_stats("", content)
    version = Version.objects.create(
        document=document,
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


@transaction.atomic
def commit_document_version(
    *,
    document_id: int,
    user: ActingUser,
    content: str,
    commit_message: str,
    version_kind: str,
) -> CommitResult:
    document = Document.objects.select_for_update().get(pk=document_id)
    previous = document.versions.order_by("-id").first()
    previous_content = previous.content if previous else ""
    previous_number = previous.semantic_version if previous else None
    stats = build_stats(previous_content, content)
    version = Version.objects.create(
        document=document,
        content=content,
        commit_message=commit_message.strip(),
        semantic_version=bump(previous_number, version_kind),
        version_kind=version_kind,
        diff_stats=stats,
        created_by=user,
    )
    document.current_version = version
    document.save(update_fields=["current_version", "updated_at"])
    return CommitResult(
        document,
        version,
        gentle_warn(previous_content, content),
        suggest_kind(stats),
    )
