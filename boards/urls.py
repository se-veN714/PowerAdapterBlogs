from django.urls import path

from boards.views import (
    BoardAccessRequestView,
    CodingPreviewView,
    MusicPreviewView,
    SkateboardBoardPreviewView,
)

app_name = "boards"

urlpatterns = [
    path("access/", BoardAccessRequestView.as_view(), name="access-requests"),
    # 本地预览：直接查看 Skateboard Board Index 前端效果；生产路由由后端集成接入契约后提供
    path("skateboard/", SkateboardBoardPreviewView.as_view(), name="skateboard-preview"),
    # 本地预览：直接查看 Music 页面前端效果；生产路由由后端在 music/ 接入真实数据契约后提供
    path("music/", MusicPreviewView.as_view(), name="music-preview"),
    # 本地预览：直接查看 Coding 页面前端效果；生产路由由后端接入真实项目数据契约后提供
    path("coding/", CodingPreviewView.as_view(), name="coding-preview"),
]
