from django.contrib import admin
from .models import Payslip, SalaryBonus, SalaryDeduction, SalaryComponent


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = (
        'employee',
        'month',
        'year',
        'basic_salary',
        'total_allowances',
        'total_deductions',
        'net_salary',
        'status',
        'generated_on',
    )
    list_filter = ('status', 'year', 'month')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name')
    ordering = ('-year', '-month')
    readonly_fields = ('generated_on',)


@admin.register(SalaryDeduction)
class SalaryDeductionAdmin(admin.ModelAdmin):
    list_display = (
        'employee',
        'reason',
        'amount',
        'month',
        'year',
        'date',
        'applied_by',
    )
    list_filter = ('reason', 'year', 'month')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name')
    ordering = ('-year', '-month', '-date')


@admin.register(SalaryBonus)
class SalaryBonusAdmin(admin.ModelAdmin):
    list_display = (
        'employee',
        'title',
        'amount',
        'month',
        'year',
        'date',
        'applied_by',
    )
    list_filter = ('year', 'month')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name', 'title')
    ordering = ('-year', '-month', '-date')


@admin.register(SalaryComponent)
class SalaryComponentAdmin(admin.ModelAdmin):
    list_display = ('name', 'component_type', 'value', 'is_percentage')
    list_filter = ('component_type', 'is_percentage')
    search_fields = ('name',)
