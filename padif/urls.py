from django.urls import path

from . import api, views

app_name = "padif"

urlpatterns = [
    path("", views.workspace, name="workspace"),
    path("documents/<int:document_id>/", views.document_detail, name="document_detail"),
    path("documents/<int:document_id>/commit/", views.commit_version, name="commit_version"),
    path("documents/<int:document_id>/upload/", views.upload_version, name="upload_version"),
    path("documents/<int:document_id>/diff/", views.diff_fragment, name="diff_fragment"),
    path(
        "documents/<int:document_id>/versions/<int:version_id>/annotations/",
        views.create_annotation,
        name="create_annotation",
    ),
    path(
        "documents/<int:document_id>/annotations/<int:annotation_id>/status/",
        views.update_annotation,
        name="update_annotation",
    ),
    path(
        "documents/<int:document_id>/annotations/<int:annotation_id>/replies/",
        views.create_annotation_reply,
        name="create_annotation_reply",
    ),
    path("api/capabilities/", api.capabilities, name="agent-capabilities"),
    path("api/documents/", api.documents, name="agent-documents"),
    path("api/documents/<int:document_id>/workspace/", api.workspace, name="agent-workspace"),
    path("api/documents/<int:document_id>/diff/", api.diff, name="agent-diff"),
    path("api/documents/<int:document_id>/versions/", api.commit_version, name="agent-commit-version"),
    path("api/versions/<int:version_id>/annotations/", api.create_annotation, name="agent-create-annotation"),
    path("api/annotations/<int:annotation_id>/", api.update_annotation, name="agent-update-annotation"),
    path("api/annotations/<int:annotation_id>/replies/", api.create_reply, name="agent-create-reply"),
]
