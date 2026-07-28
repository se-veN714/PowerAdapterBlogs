from django.urls import path

from .views import (
    AccountModerationView,
    BoardAccessModerationView,
    CommentModerationView,
    ModerationHubView,
)

app_name = "moderation"

urlpatterns = [
    path("", ModerationHubView.as_view(), name="hub"),
    path("accounts/", AccountModerationView.as_view(), name="accounts"),
    path("comments/", CommentModerationView.as_view(), name="comments"),
    path("boards/", BoardAccessModerationView.as_view(), name="boards"),
]
