from __future__ import annotations

import json
import re

from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from functools import wraps

from django.http import JsonResponse, Http404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from accounts.agent_auth import (
    AGENT_SCOPE_PADIF_ANNOTATE,
    AGENT_SCOPE_PADIF_READ,
    AGENT_SCOPE_PADIF_VERSION,
    authenticate_agent_token,
)

from .core.differ import build_stats, diff_sentences, summarize
from .models import Annotation, AnnotationReply, Document, Version
from .permissions import can_use_padif, visible_documents, action_document_id, require_document, agent_permission_payload
from .services import (BranchError, commit_document_version, effective_head, resolve_branch,
                       create_branch as create_branch_service, publish_branch as publish_branch_service)


def agent_api_required(scope: str):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            header = request.headers.get("Authorization", "")
            scheme, _, value = header.partition(" ")
            if scheme.lower() != "bearer" or not value:
                return JsonResponse({"error": "AUTH_REQUIRED"}, status=401)
            token, error = authenticate_agent_token(value.strip(), required_scope=scope)
            if error == "insufficient_scope":
                return JsonResponse({"error": "INSUFFICIENT_SCOPE"}, status=403)
            if token is None or not can_use_padif(token.user):
                return JsonResponse({"error": "INVALID_TOKEN"}, status=401)
            request.agent_token = token
            request.agent_user = token.user
            request.agent_scopes = token.scopes
            try:
                with transaction.atomic():
                    document_id = action_document_id(kwargs)
                    if kwargs and document_id is None:
                        raise Http404
                    if document_id is not None:
                        documents = Document.objects.filter(pk=document_id)
                        if scope != AGENT_SCOPE_PADIF_READ:
                            documents = documents.select_for_update()
                        document = documents.first()
                        if document is None:
                            raise Http404
                        require_document(token.user, document, write=scope != AGENT_SCOPE_PADIF_READ, agent=True, operation=scope)
                    if view.__name__ == 'publish_branch':
                        return JsonResponse({'error': 'MAIN_REQUIRES_WEB_CONFIRMATION'}, status=403)
                    return view(request, *args, **kwargs)
            except Http404:
                return JsonResponse({'error': 'DOCUMENT_NOT_FOUND'}, status=404)
            except PermissionDenied:
                return JsonResponse({'error': 'DOCUMENT_PERMISSION_DENIED'}, status=403)

        return wrapped

    return decorator


def _payload(request):
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _version_payload(version):
    return {
        "id": version.pk,
        "branch_id": version.branch_id,
        "branch_name": version.branch.name,
        "parent_version_id": version.parent_id,
        "semantic_version": version.semantic_version,
        "commit_message": version.commit_message,
        "version_kind": version.version_kind,
        "created_by": version.created_by.username,
        "created_at": version.created_at.isoformat(),
    }


def _annotation_payload(annotation):
    return {
        "id": annotation.pk,
        "version_id": annotation.version_id,
        "kind": annotation.kind,
        "body": annotation.body,
        "start_line": annotation.start_line,
        "end_line": annotation.end_line,
        "selected_text": annotation.selected_text,
        "status": annotation.status,
        "author": annotation.author.username,
        "created_at": annotation.created_at.isoformat(),
        "resolution_note": annotation.resolution_note,
        "resolved_by": annotation.resolved_by.username if annotation.resolved_by else None,
        "resolved_at": annotation.resolved_at.isoformat() if annotation.resolved_at else None,
        "replies": [
            {
                "id": reply.pk,
                "body": reply.body,
                "author": reply.author.username,
                "created_at": reply.created_at.isoformat(),
            }
            for reply in annotation.replies.select_related("author").all()
        ],
    }


def _diff_op_payload(op):
    payload = {"op": op.op, "text": op.text}
    for field in ("old_line", "new_line"):
        value = getattr(op, field, None)
        if value is not None:
            payload[field] = value
    if op.inner:
        payload["inner"] = [_diff_op_payload(item) for item in op.inner]
    return payload


def _annotate_diff_lines(ops, old_content: str, new_content: str) -> None:
    old_cursor = 0
    new_cursor = 0
    old_lines = old_content.replace("\r\n", "\n").split("\n")
    new_lines = new_content.replace("\r\n", "\n").split("\n")
    for op in ops:
        text = getattr(op, "text", "")
        if op.op in {"delete", "replace"}:
            for index in range(old_cursor, len(old_lines)):
                if text and text.strip() in old_lines[index]:
                    op.old_line = index + 1
                    old_cursor = index
                    break
        search_text = text
        if op.op == "replace" and op.inner:
            inserted = "".join(item.text for item in op.inner if item.op in {"equal", "insert"})
            if inserted:
                search_text = inserted
        if op.op in {"insert", "replace", "moved", "equal"}:
            for index in range(new_cursor, len(new_lines)):
                if search_text and search_text.strip() in new_lines[index]:
                    op.new_line = index + 1
                    new_cursor = index
                    break


def _diff_payload(old: Version, new: Version) -> dict[str, object]:
    ops = diff_sentences(old.content, new.content)
    _annotate_diff_lines(ops, old.content, new.content)
    return {
        "from_version": _version_payload(old),
        "to_version": _version_payload(new),
        "stats": build_stats(old.content, new.content),
        "from_summary": summarize(old.content),
        "to_summary": summarize(new.content),
        "ops": [_diff_op_payload(op) for op in ops],
    }


def capabilities(request):
    if request.method != "GET":
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)

    def templated(route_name, placeholder):
        url = request.build_absolute_uri(reverse(route_name, args=[0]))
        return url.replace("/0/", f"/{{{placeholder}}}/")

    return JsonResponse(
        {
            "service": "PAdif Agent API",
            "schema_version": "1",
            "auth": {
                "device_start": request.build_absolute_uri(reverse("accounts:agent-device-start")),
                "device_token": request.build_absolute_uri(reverse("accounts:agent-device-token")),
                "authorize": request.build_absolute_uri(reverse("accounts:agent-authorize")),
            },
            "authorization": {
                "header": "Authorization: Bearer <access_token>",
                "scopes": [
                    {"name": AGENT_SCOPE_PADIF_READ, "description": "读取文档、版本、批注和结构化差异"},
                    {"name": AGENT_SCOPE_PADIF_ANNOTATE, "description": "创建批注、回复和处理批注"},
                    {"name": AGENT_SCOPE_PADIF_VERSION, "description": "追加文档版本"},
                ],
            },
            "branching": {
                "workspace_query": "branch", "default_branch": "main",
                "write_scope": AGENT_SCOPE_PADIF_VERSION,
                "publish_requires": ["owner_web_confirmation"],
                "publish_semantics": "web_only_no_agent_main_writes",
            },
            "resources": {
                "documents": request.build_absolute_uri(reverse("padif:agent-documents")),
                "workspace": templated("padif:agent-workspace", "document_id"),
                "diff": templated("padif:agent-diff", "document_id"),
                "commit_version": templated("padif:agent-commit-version", "document_id"),
                "create_branch": templated("padif:agent-create-branch", "document_id"),
                "publish_branch": request.build_absolute_uri(reverse("padif:agent-publish-branch", args=[0, 0])).replace("/documents/0/", "/documents/{document_id}/").replace("/branches/0/", "/branches/{branch_id}/"),
                "create_annotation": templated("padif:agent-create-annotation", "version_id"),
                "update_annotation": templated("padif:agent-update-annotation", "annotation_id"),
                "create_reply": templated("padif:agent-create-reply", "annotation_id"),
            },
            "errors": [
                "AUTH_REQUIRED",
                "INVALID_TOKEN",
                "INSUFFICIENT_SCOPE",
                "DOCUMENT_NOT_FOUND", "DOCUMENT_PERMISSION_DENIED", "MAIN_REQUIRES_WEB_CONFIRMATION",
                "STALE_BASE_VERSION",
                "STALE_SOURCE_VERSION", "BRANCH_NOT_FOUND", "BRANCH_ARCHIVED",
                "EMPTY_BRANCH", "CONFIRMATION_REQUIRED", "BRANCH_NAME_EXISTS",
                "INVALID_JSON",
                "INVALID_DIFF_INPUT",
            ],
        }
    )


@agent_api_required(AGENT_SCOPE_PADIF_READ)
def documents(request):
    if request.method != "GET":
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)
    queryset = visible_documents(request.agent_user, agent=True).select_related("current_version", "created_by")
    return JsonResponse(
        {
            "documents": [
                {
                    "id": document.pk,
                    "title": document.title,
                    "source_name": document.source_name,
                    "created_by": document.created_by.username,
                    "created_at": document.created_at.isoformat(),
                    "updated_at": document.updated_at.isoformat(),
                    "current_version_id": document.current_version_id,
                    "current_version": document.current_version.semantic_version
                    if document.current_version
                    else None,
                }
                for document in queryset
            ]
        }
    )


@agent_api_required(AGENT_SCOPE_PADIF_READ)
def diff(request, document_id):
    if request.method != "GET":
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)
    document = Document.objects.filter(pk=document_id).first()
    if document is None:
        return JsonResponse({"error": "DOCUMENT_NOT_FOUND"}, status=404)
    try:
        old_id = int(request.GET.get("from_version", ""))
        new_id = int(request.GET.get("to_version", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "INVALID_DIFF_INPUT"}, status=400)
    versions = document.versions.filter(pk__in=[old_id, new_id])
    by_id = {version.pk: version for version in versions}
    if len(by_id) != 2:
        return JsonResponse({"error": "VERSION_NOT_FOUND"}, status=404)
    return JsonResponse({"diff": _diff_payload(by_id[old_id], by_id[new_id])})


@agent_api_required(AGENT_SCOPE_PADIF_READ)
def workspace(request, document_id):
    if request.method != "GET":
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)
    document = Document.objects.select_related("current_version").filter(pk=document_id).first()
    if document is None:
        return JsonResponse({"error": "DOCUMENT_NOT_FOUND"}, status=404)
    try:
        branch = _request_branch(document, request.GET.get("branch"))
    except ValidationError as exc:
        return _branch_error(exc)
    versions = document.versions.select_related("created_by", "branch").all()
    current = effective_head(branch)
    return JsonResponse({
        "document": {"id": document.pk, "title": document.title, "source_name": document.source_name},
        "permissions": agent_permission_payload(request.agent_user, document, getattr(request, "agent_scopes", [])),
        "current_version": {**_version_payload(current), "content": current.content} if current else None,
        "versions": [_version_payload(version) for version in versions],
        "annotations": [_annotation_payload(item) for item in current.annotations.select_related("author", "resolved_by").all()] if current else [],
        "selected_branch": _branch_payload(branch),
        "branches": [_branch_payload(item) for item in document.branches.all()],
    })


def _branch_payload(branch):
    head = effective_head(branch)
    return {"id": branch.pk, "name": branch.name, "is_default": branch.is_default,
            "forked_from_version_id": branch.forked_from_id,
            "head_version_id": head.pk if head else None,
            "head_semantic_version": head.semantic_version if head else None,
            "archived_at": branch.archived_at.isoformat() if branch.archived_at else None}


def _branch_error(exc):
    return JsonResponse({"error": getattr(exc, "error_code", "INVALID_BRANCH_INPUT"),
                         "messages": exc.messages, **getattr(exc, "details", {})}, status=getattr(exc, "status", 400))


def _positive_id(value):
    return type(value) is int and value > 0


def _request_branch(document, name):
    if name is not None and (not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64):
        raise BranchError("INVALID_BRANCH_INPUT", "分支名无效。")
    return resolve_branch(document, name=name)


@csrf_exempt
@agent_api_required(AGENT_SCOPE_PADIF_VERSION)
def commit_version(request, document_id):
    if request.method != "POST":
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)
    payload = _payload(request)
    if payload is None:
        return JsonResponse({"error": "INVALID_JSON"}, status=400)
    document = Document.objects.filter(pk=document_id).first()
    if document is None:
        return JsonResponse({"error": "DOCUMENT_NOT_FOUND"}, status=404)
    if "base_version_id" in payload and not _positive_id(payload["base_version_id"]):
        return JsonResponse({"error": "INVALID_VERSION_INPUT"}, status=400)
    if "branch" in payload and payload["branch"] is None:
        return JsonResponse({"error": "INVALID_BRANCH_INPUT"}, status=400)
    try:
        branch = _request_branch(document, payload.get("branch"))
        if branch.is_default:
            return JsonResponse({'error': 'MAIN_REQUIRES_WEB_CONFIRMATION'}, status=403)
        result = commit_document_version(document_id=document.pk, user=request.agent_user,
            content=payload.get("content"), commit_message=payload.get("commit_message"),
            version_kind=payload.get("version_kind", Version.Kind.PATCH),
            branch_id=branch.pk, base_version_id=payload.get("base_version_id"))
    except ValidationError as exc:
        return _branch_error(exc)
    return JsonResponse({"version": _version_payload(result.version), "branch": _branch_payload(branch), "gentle_warning": result.gentle_warning}, status=201)


@csrf_exempt
@agent_api_required(AGENT_SCOPE_PADIF_VERSION)
def create_branch(request, document_id):
    if request.method != "POST":
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)
    payload = _payload(request)
    if payload is None:
        return JsonResponse({"error": "INVALID_JSON"}, status=400)
    if not Document.objects.filter(pk=document_id).exists():
        return JsonResponse({"error": "DOCUMENT_NOT_FOUND"}, status=404)
    if (not _positive_id(payload.get("fork_from_version_id")) or not isinstance(payload.get("name"), str)
            or not isinstance(payload.get("description", ""), str) or "is_default" in payload):
        return JsonResponse({"error": "INVALID_BRANCH_INPUT"}, status=400)
    try:
        branch = create_branch_service(document_id=document_id, user=request.agent_user,
            name=payload["name"], description=payload.get("description", ""), fork_from_version_id=payload["fork_from_version_id"])
    except ValidationError as exc:
        return _branch_error(exc)
    return JsonResponse({"branch": _branch_payload(branch)}, status=201)


@csrf_exempt
@agent_api_required(AGENT_SCOPE_PADIF_VERSION)
def publish_branch(request, document_id, branch_id):
    if request.method != "POST":
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)
    payload = _payload(request)
    if payload is None:
        return JsonResponse({"error": "INVALID_JSON"}, status=400)
    if not Document.objects.filter(pk=document_id).exists():
        return JsonResponse({"error": "DOCUMENT_NOT_FOUND"}, status=404)
    if not _positive_id(payload.get("base_version_id")) or not _positive_id(payload.get("source_version_id")) or payload.get("confirm_replace") is not True:
        return JsonResponse({"error": "CONFIRMATION_REQUIRED"}, status=400)
    if not isinstance(payload.get("commit_message"), str) or not payload["commit_message"].strip():
        return JsonResponse({"error": "INVALID_VERSION_INPUT"}, status=400)
    try:
        result = publish_branch_service(document_id=document_id, branch_id=branch_id, user=request.agent_user,
            commit_message=payload["commit_message"], version_kind=payload.get("version_kind", Version.Kind.PATCH),
            base_version_id=payload["base_version_id"], source_version_id=payload["source_version_id"], confirm_replace=True)
    except ValidationError as exc:
        return _branch_error(exc)
    return JsonResponse({"version": _version_payload(result.version), "branch": _branch_payload(result.version.branch), "gentle_warning": result.gentle_warning}, status=201)


@csrf_exempt
@agent_api_required(AGENT_SCOPE_PADIF_ANNOTATE)
def create_annotation(request, version_id):
    if request.method != "POST":
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)
    payload = _payload(request)
    if payload is None:
        return JsonResponse({"error": "INVALID_JSON"}, status=400)
    version = Version.objects.filter(pk=version_id).first()
    if version is None:
        return JsonResponse({"error": "VERSION_NOT_FOUND"}, status=404)
    kind = payload.get("kind")
    body = payload.get("body")
    start_line = payload.get("start_line")
    end_line = payload.get("end_line", start_line)
    if kind not in Annotation.Kind.values or not isinstance(body, str) or not body.strip():
        return JsonResponse({"error": "INVALID_ANNOTATION_INPUT"}, status=400)
    if not isinstance(start_line, int) or not isinstance(end_line, int) or start_line < 1 or end_line < start_line:
        return JsonResponse({"error": "INVALID_SOURCE_RANGE"}, status=400)
    annotation = Annotation.objects.create(
        version=version,
        author=request.agent_user,
        kind=kind,
        body=body.strip(),
        start_line=start_line,
        end_line=end_line,
        selected_text=str(payload.get("selected_text") or ""),
    )
    return JsonResponse({"annotation": _annotation_payload(annotation)}, status=201)


@csrf_exempt
@agent_api_required(AGENT_SCOPE_PADIF_ANNOTATE)
def update_annotation(request, annotation_id):
    if request.method not in {"PATCH", "POST"}:
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)
    payload = _payload(request)
    if payload is None:
        return JsonResponse({"error": "INVALID_JSON"}, status=400)
    annotation = (
        Annotation.objects.select_related("version", "version__document")
        .filter(pk=annotation_id)
        .first()
    )
    if annotation is None:
        return JsonResponse({"error": "ANNOTATION_NOT_FOUND"}, status=404)
    status = payload.get("status")
    note = payload.get("resolution_note")
    if status not in {Annotation.Status.RESOLVED, Annotation.Status.REJECTED}:
        return JsonResponse({"error": "INVALID_ANNOTATION_STATUS"}, status=400)
    if not isinstance(note, str) or not note.strip():
        return JsonResponse({"error": "RESOLUTION_NOTE_REQUIRED"}, status=400)
    annotation.status = status
    annotation.resolution_note = note.strip()
    annotation.resolved_by = request.agent_user
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
    return JsonResponse({"annotation": _annotation_payload(annotation)})


@csrf_exempt
@agent_api_required(AGENT_SCOPE_PADIF_ANNOTATE)
def create_reply(request, annotation_id):
    if request.method != "POST":
        return JsonResponse({"error": "METHOD_NOT_ALLOWED"}, status=405)
    payload = _payload(request)
    annotation = Annotation.objects.filter(pk=annotation_id).first()
    if annotation is None:
        return JsonResponse({"error": "ANNOTATION_NOT_FOUND"}, status=404)
    body = payload.get("body") if payload else None
    if not isinstance(body, str) or not body.strip():
        return JsonResponse({"error": "INVALID_REPLY_INPUT"}, status=400)
    reply = AnnotationReply.objects.create(
        annotation=annotation,
        author=request.agent_user,
        body=body.strip(),
    )
    return JsonResponse(
        {
            "reply": {
                "id": reply.pk,
                "body": reply.body,
                "author": reply.author.username,
                "created_at": reply.created_at.isoformat(),
            }
        },
        status=201,
    )
