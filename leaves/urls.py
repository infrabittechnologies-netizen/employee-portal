from django.urls import path

from . import views

app_name = 'leaves'

urlpatterns = [
    # Employee self-service
    path('apply/', views.apply_leave_view, name='apply_leave'),
    path('my-leaves/', views.my_leaves_view, name='my_leaves'),
    path('calendar/', views.leave_calendar_view, name='leave_calendar'),

    # Admin / manager actions (specific named paths before the generic <int:pk>/)
    path('pending/', views.pending_leaves_view, name='pending_leaves'),
    path('types/', views.admin_leave_type_view, name='leave_types'),

    # Per-application actions  (must follow the named paths above)
    path('<int:pk>/', views.leave_detail_view, name='leave_detail'),
    path('<int:pk>/cancel/', views.cancel_leave_view, name='cancel_leave'),
    path('<int:pk>/review/', views.review_leave_view, name='review_leave'),
]
