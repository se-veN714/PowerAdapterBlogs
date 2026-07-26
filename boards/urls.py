from django.urls import path

from boards.views import BoardAccessRequestView, SkateboardBoardPreviewView

app_name = "boards"

urlpatterns = [
    path("access/", BoardAccessRequestView.as_view(), name="access-requests"),
    # 本地预览：直接查看 Skateboard Board Index 前端效果；生产路由由后端集成接入契约后提供
    path("skateboard/", SkateboardBoardPreviewView.as_view(), name="skateboard-preview"),
]
