# main/urls.py
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

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
    path("login/", views.RememberLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # динамические компоненты и AJAX (ЛЗ 9)
    path("slots/<int:pk>/seats/", views.slot_seats_view, name="slot_seats"),
    path("submission/<int:pk>/status/", views.submission_status_view, name="submission_status"),
    # состояние приложения: сессии и cookies (ЛЗ 8)
    path("theme/<str:theme>/", views.set_theme_view, name="set_theme"),
    path("state/", views.state_view, name="state"),
    path("state/reset/", views.state_reset_view, name="state_reset"),
]
