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
    path('commission/<int:pk>/edit/', views.edit_commission_view, name='edit_commission'),
    path('commission/<int:pk>/delete/', views.delete_commission_view, name='delete_commission'),
    # Per-employee salary management (employee detail / report page)
    path('employee/<int:pk>/base-salary/', views.update_base_salary_view, name='update_base_salary'),
    path('employee/<int:pk>/deduction/add/', views.emp_add_deduction_view, name='emp_add_deduction'),
    path('deduction/<int:pk>/edit/', views.emp_edit_deduction_view, name='emp_edit_deduction'),
    path('deduction/<int:pk>/delete/', views.emp_delete_deduction_view, name='emp_delete_deduction'),
    path('employee/<int:pk>/bonus/add/', views.emp_add_bonus_view, name='emp_add_bonus'),
    path('bonus/<int:pk>/edit/', views.emp_edit_bonus_view, name='emp_edit_bonus'),
    path('bonus/<int:pk>/delete/', views.emp_delete_bonus_view, name='emp_delete_bonus'),
    path('report/', views.salary_report_view, name='salary_report'),
    path('process-payroll/', views.process_payroll_view, name='process_payroll'),
]
