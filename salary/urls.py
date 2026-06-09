from django.urls import path
from . import views

app_name = 'salary'

urlpatterns = [
    path('my-salary/', views.my_salary_view, name='my_salary'),
    path('payslip/<int:pk>/', views.payslip_detail_view, name='payslip_detail'),
    path('payslip/<int:pk>/download/', views.download_payslip_view, name='download_payslip'),
    path('generate/', views.generate_payslip_view, name='generate_payslip'),
    path('add-deduction/', views.add_deduction_view, name='add_deduction'),
    path('add-bonus/', views.add_bonus_view, name='add_bonus'),
    path('commission/<int:pk>/pay/', views.pay_commission_view, name='pay_commission'),
    path('report/', views.salary_report_view, name='salary_report'),
    path('process-payroll/', views.process_payroll_view, name='process_payroll'),
]
