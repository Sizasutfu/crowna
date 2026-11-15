from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views

app_name = "voting"

urlpatterns = [
    path("", views.contest_list, name="contest_list"),
    path(
        "login/",
        LoginView.as_view(template_name="voting/login.html"),
        name="login",
    ),
    path("signup/", views.SignupView.as_view(), name="signup"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("contests/<int:contest_id>/", views.contest_detail, name="contest_detail"),
    path(
        "contestants/<int:contestant_id>/",
        views.contestant_detail,
        name="contestant_detail",
    ),
    path(
        "contests/<int:contest_id>/vote/<int:contestant_id>/",
        views.cast_vote,
        name="cast_vote",
    ),
]