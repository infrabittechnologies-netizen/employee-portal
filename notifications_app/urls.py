from django.urls import path
from . import views

app_name = 'notifications_app'

urlpatterns = [
    path('list/', views.notification_list_view, name='notification_list'),
    path('<int:pk>/read/', views.mark_read_view, name='mark_read'),
    path('mark-all-read/', views.mark_all_read_view, name='mark_all_read'),
    path('count/', views.notification_count_view, name='notification_count'),
]
