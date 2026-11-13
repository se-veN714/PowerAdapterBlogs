from django.urls import path
from .views import PadifAuthorizationView, PadifTokenView, PadifRevokeView, PadifRegistrationView, disconnect
from .review_views import apply, withdraw
from .article_views import apply_articles, withdraw_article, relinquish_article, adjust_article, review_article
from .upload_views import upload_file

app_name = 'agent_mcp'
urlpatterns = [
    path('uploads/<uuid:upload_id>/', upload_file, name='upload-file'),
    path('apply/', apply, name='apply'),
    path('requests/<int:request_id>/withdraw/', withdraw, name='withdraw'),
    path('articles/<int:document_id>/operations/', adjust_article, name='adjust-article'),
    path('articles/apply/', apply_articles, name='apply-articles'),
    path('articles/requests/<int:request_id>/withdraw/', withdraw_article, name='withdraw-article'),
    path('articles/requests/<int:request_id>/review/', review_article, name='review-article'),
    path('articles/<int:document_id>/relinquish/', relinquish_article, name='relinquish-article'),
    path('register/', PadifRegistrationView.as_view(), name='register'),
    path('authorize/', PadifAuthorizationView.as_view(), name='authorize'),
    path('token/', PadifTokenView.as_view(), name='token'),
    path('revoke/', PadifRevokeView.as_view(), name='revoke'),
    path('connections/<int:connection_id>/revoke/', disconnect, name='disconnect'),
]
