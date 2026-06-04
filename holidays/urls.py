from django.urls import path
from . import views

app_name = 'holidays'

urlpatterns = [
    path('list/', views.holiday_list_view, name='holiday_list'),
    path('admin/', views.admin_holiday_view, name='admin_holiday'),
    path('announcements/', views.announcement_list_view, name='announcement_list'),
    path('announcements/create/', views.admin_announcement_view, name='admin_announcement'),
    path('announcements/<int:pk>/delete/', views.delete_announcement_view, name='delete_announcement'),
]
