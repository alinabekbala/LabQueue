from django.urls import path

from . import views

urlpatterns = [
    path('', views.slot_list_view, name='slot_list'),
    path('book/<int:slot_id>/', views.book_slot_view, name='book_slot'),
    path(
        'submission/<int:pk>/edit/',
        views.submission_update_view,
        name='submission_update',
    ),
    path(
        'submission/<int:pk>/delete/',
        views.submission_delete_view,
        name='submission_delete',
    ),
]