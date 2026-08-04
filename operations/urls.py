from django.urls import path

from .views import SecurityOperationsView

app_name = "operations"

urlpatterns = [
    path("security/", SecurityOperationsView.as_view(), name="security"),
]
