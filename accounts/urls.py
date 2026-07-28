# -*- coding: utf-8 -*-
# @File    : urls.py
# @Time    : 2025/7/11 12:09
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了XXX功能的类和函数。
"""
# here put the import lib
from django.urls import path
from django.contrib.auth.views import LogoutView

from accounts.views import (
    AcceptAccountInvitationView,
    AccountPasswordChangeView,
    BoardAccessEmailVerificationView,
    LoginView,
    MfaChallengeView,
    MfaConfirmEnrollmentView,
    MfaSettingsView,
    MyProfileRedirectView,
    PasswordEmailVerificationView,
    ProfileDetailView,
    ProfileUpdateView,
)

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('security/mfa/', MfaSettingsView.as_view(), name='mfa-settings'),
    path(
        'security/mfa/confirm/',
        MfaConfirmEnrollmentView.as_view(),
        name='mfa-confirm',
    ),
    path('security/mfa/challenge/', MfaChallengeView.as_view(), name='mfa-challenge'),
    path('profile/', MyProfileRedirectView.as_view(), name='my-profile'),
    path('u/<str:username>/', ProfileDetailView.as_view(), name='profile-detail'),
    path('settings/profile/', ProfileUpdateView.as_view(), name='profile-update'),
    path(
        'password/change/verify/',
        PasswordEmailVerificationView.as_view(),
        name='password-email-verify',
    ),
    path(
        'security/email/board-access/',
        BoardAccessEmailVerificationView.as_view(),
        name='board-access-email-verify',
    ),
    path(
        'password/change/',
        AccountPasswordChangeView.as_view(),
        name='password-change',
    ),
    path(
        'invitation/<str:token>/',
        AcceptAccountInvitationView.as_view(),
        name='accept-invitation',
    ),
    path('logout/', LogoutView.as_view(next_page='index'), name='logout'),
]
