# main/urls.py
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    # слоты
    path("", views.slot_list_view, name="slot_list"),
    path("slots/new/", views.slot_create_view, name="slot_create"),
    path("slots/<int:pk>/edit/", views.slot_update_view, name="slot_update"),
    path("slots/<int:pk>/delete/", views.slot_delete_view, name="slot_delete"),
    # записи на защиту
    path("book/<int:slot_id>/", views.book_slot_view, name="book_slot"),
    path("submissions/", views.submission_list_view, name="submission_list"),
    path("submission/<int:pk>/edit/", views.submission_update_view, name="submission_update"),
    path("submission/<int:pk>/delete/", views.submission_delete_view, name="submission_delete"),
    # авторизация
    path("register/", views.register_view, name="register"),
    path("login/", auth_views.LoginView.as_view(
        template_name="main/login.html", authentication_form=LoginForm,
        redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
