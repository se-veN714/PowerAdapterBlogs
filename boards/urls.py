from django.urls import path

from boards.views import (
    BoardAccessRequestView,
    BoardIndexView,
    HomieLineView,
    SkateClipListView,
    withdraw_membership,
)

app_name = "boards"

urlpatterns = [
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
