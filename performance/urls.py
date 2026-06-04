from django.urls import path
from . import views

app_name = 'performance'

urlpatterns = [
    path('my-performance/', views.my_performance_view, name='my_performance'),
    path('review/create/', views.performance_review_create_view, name='review_create'),
    path('review/<int:pk>/', views.performance_review_detail_view, name='review_detail'),
    path('kpi/', views.kpi_list_view, name='kpi_list'),
    path('kpi/create/', views.kpi_create_view, name='kpi_create'),
    path('kpi/<int:pk>/update/', views.kpi_update_view, name='kpi_update'),
    path('all/', views.all_performance_view, name='all_performance'),
]
