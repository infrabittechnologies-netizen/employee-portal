from django.urls import path

from . import views

app_name = 'attendance'

urlpatterns = [
    # Employee self-service
    path('check-in/',    views.check_in_view,     name='check_in'),
    path('check-out/',   views.check_out_view,    name='check_out'),
    path('restart/',     views.restart_work_view, name='restart_work'),
    path('day-summary/', views.day_summary_api,   name='day_summary'),
    path('my-attendance/', views.my_attendance_view, name='my_attendance'),

    # Manager / admin views
    path('report/', views.attendance_report_view, name='attendance_report'),
    path('mark-absent/', views.mark_absent_view, name='mark_absent'),

    # Detail (must come after named paths to avoid capturing them)
    path('<int:pk>/', views.attendance_detail_view, name='attendance_detail'),
]
