from django.urls import path

from boards.views import (
    BoardAccessRequestView,
    BoardIndexView,
    HomieLineView,
)

app_name = "boards"

urlpatterns = [
    path("access/", BoardAccessRequestView.as_view(), name="access-requests"),
    # 单一路由：按 Board.slug 分派三板索引（skateboard / music / coding）
    path("<slug:slug>/", BoardIndexView.as_view(), name="index"),
    # htmx 端点：返回单个 Homie 的 Selected Line 片段（skateboard 专用）
    path(
        "<slug:slug>/homie/<int:node_index>/",
        HomieLineView.as_view(),
        name="homie-line",
    ),
]
