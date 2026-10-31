from django.urls import path

from . import views

app_name = "padif"

urlpatterns = [
    path("", views.workspace, name="workspace"),
    path("documents/<int:document_id>/", views.document_detail, name="document_detail"),
    path("documents/<int:document_id>/commit/", views.commit_version, name="commit_version"),
    path("documents/<int:document_id>/upload/", views.upload_version, name="upload_version"),
    path("documents/<int:document_id>/diff/", views.diff_fragment, name="diff_fragment"),
]
