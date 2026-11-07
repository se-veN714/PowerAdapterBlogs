"""Canonical routes for the first-party Devenir dashboard."""

from django.urls import path

from PowerAdapterBlogs import dashboard_views
from agent_mcp.review_views import AgentAccessReviewView

app_name = "dashboard"

urlpatterns = [
    path("agents/", AgentAccessReviewView.as_view(), name="agents"),
    path("", dashboard_views.overview, name="overview"),
    path("posts/", dashboard_views.posts, name="posts"),
    path("audit/", dashboard_views.audit, name="audit"),
    path("comments/", dashboard_views.comments, name="comments"),
    path("media/", dashboard_views.media, name="media"),
    path("settings/", dashboard_views.settings, name="settings"),
]
