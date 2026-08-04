from django.urls import path

from boards.views import (
    BoardAccessRequestView,
    BoardIndexView,
    HomieLineView,
    SkateClipListView,
    withdraw_membership,
)
from boards.content_views import (
    CodingProjectCreateView,
    CodingProjectDeleteView,
    CodingProjectListView,
    CodingProjectUpdateView,
    MusicRecordCreateView,
    MusicRecordDeleteView,
    MusicRecordListView,
    MusicRecordUpdateView,
    PadifLocalView,
    SkateClipCreateView,
    SkateClipDeleteView,
    SkateClipManageListView,
    SkateClipUpdateView,
)

app_name = "boards"

urlpatterns = [
    path("coding/padif-local/", PadifLocalView.as_view(), name="padif-local"),
    path(
        "manage/skateboard/clips/",
        SkateClipManageListView.as_view(),
        name="skate-manage-list",
    ),
    path(
        "manage/skateboard/clips/new/",
        SkateClipCreateView.as_view(),
        name="skate-manage-create",
    ),
    path(
        "manage/skateboard/clips/<int:pk>/edit/",
        SkateClipUpdateView.as_view(),
        name="skate-manage-update",
    ),
    path(
        "manage/skateboard/clips/<int:pk>/delete/",
        SkateClipDeleteView.as_view(),
        name="skate-manage-delete",
    ),
    path(
        "manage/music/<str:provider>/",
        MusicRecordListView.as_view(),
        name="music-manage-list",
    ),
    path(
        "manage/music/<str:provider>/new/",
        MusicRecordCreateView.as_view(),
        name="music-manage-create",
    ),
    path(
        "manage/music/<str:provider>/<int:pk>/edit/",
        MusicRecordUpdateView.as_view(),
        name="music-manage-update",
    ),
    path(
        "manage/music/<str:provider>/<int:pk>/delete/",
        MusicRecordDeleteView.as_view(),
        name="music-manage-delete",
    ),
    path(
        "manage/coding/projects/",
        CodingProjectListView.as_view(),
        name="coding-manage-list",
    ),
    path(
        "manage/coding/projects/new/",
        CodingProjectCreateView.as_view(),
        name="coding-manage-create",
    ),
    path(
        "manage/coding/projects/<int:pk>/edit/",
        CodingProjectUpdateView.as_view(),
        name="coding-manage-update",
    ),
    path(
        "manage/coding/projects/<int:pk>/delete/",
        CodingProjectDeleteView.as_view(),
        name="coding-manage-delete",
    ),
    path("access/", BoardAccessRequestView.as_view(), name="access-requests"),
    path(
        "access/membership/<int:pk>/withdraw/",
        withdraw_membership,
        name="withdraw-membership",
    ),
    path(
        "skateboard/clips/",
        SkateClipListView.as_view(),
        name="skate-clip-list",
    ),
    # 单一路由：按 Board.slug 分派三板索引（skateboard / music / coding）
    path("<slug:slug>/", BoardIndexView.as_view(), name="index"),
    # htmx 端点：返回单个 Homie 的 Selected Line 片段（skateboard 专用）
    path(
        "<slug:slug>/homie/<int:node_index>/",
        HomieLineView.as_view(),
        name="homie-line",
    ),
]
