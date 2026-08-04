"""Devenir Dashboard routes owned by the boards app."""

from django.urls import path

from boards.dashboard_views import (
    DashboardManagerTransferView,
    DashboardMembershipDeactivateView,
    DashboardMembershipEventListView,
    DashboardMembershipGrantView,
    DashboardMembershipListView,
    DashboardMembershipReactivateView,
    DashboardMembershipRoleView,
)

app_name = "board-dashboard"

urlpatterns = [
    path("", DashboardMembershipListView.as_view(), name="memberships"),
    path(
        "events/",
        DashboardMembershipEventListView.as_view(),
        name="membership-events",
    ),
    path("grant/", DashboardMembershipGrantView.as_view(), name="membership-grant"),
    path(
        "<int:pk>/events/",
        DashboardMembershipEventListView.as_view(),
        name="membership-event-history",
    ),
    path(
        "<int:pk>/role/",
        DashboardMembershipRoleView.as_view(),
        name="membership-role",
    ),
    path(
        "<int:pk>/deactivate/",
        DashboardMembershipDeactivateView.as_view(),
        name="membership-deactivate",
    ),
    path(
        "<int:pk>/reactivate/",
        DashboardMembershipReactivateView.as_view(),
        name="membership-reactivate",
    ),
    path(
        "<int:pk>/transfer-manager/",
        DashboardManagerTransferView.as_view(),
        name="manager-transfer",
    ),
]
