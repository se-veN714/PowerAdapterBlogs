from django.contrib import admin

from .models import Annotation, AnnotationReply, Document, Version


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "created_by", "current_version", "updated_at")
    search_fields = ("title", "source_name", "created_by__username")
    list_select_related = ("created_by", "current_version")


@admin.register(Version)
class VersionAdmin(admin.ModelAdmin):
    list_display = ("document", "semantic_version", "version_kind", "created_by", "created_at")
    list_filter = ("version_kind", "created_at")
    search_fields = ("document__title", "commit_message", "created_by__username")
    list_select_related = ("document", "created_by")


@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    list_display = ("version", "kind", "start_line", "end_line", "status", "author", "created_at")
    list_filter = ("kind", "status", "created_at")
    search_fields = ("body", "selected_text", "version__document__title", "author__username")
    list_select_related = ("version", "author")


@admin.register(AnnotationReply)
class AnnotationReplyAdmin(admin.ModelAdmin):
    list_display = ("annotation", "author", "created_at")
    search_fields = ("body", "author__username", "annotation__version__document__title")
    list_select_related = ("annotation", "author")
