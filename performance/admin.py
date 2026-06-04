from django.contrib import admin
from .models import KPI, PerformanceReview


@admin.register(PerformanceReview)
class PerformanceReviewAdmin(admin.ModelAdmin):
    list_display = (
        'employee',
        'reviewed_by',
        'review_period',
        'period_start',
        'period_end',
        'rating',
        'total_score_display',
        'created_at',
    )
    list_filter = ('review_period', 'rating')
    search_fields = (
        'employee__username',
        'employee__first_name',
        'employee__last_name',
        'reviewed_by__username',
    )
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)

    @admin.display(description='Total Score')
    def total_score_display(self, obj):
        return obj.total_score


@admin.register(KPI)
class KPIAdmin(admin.ModelAdmin):
    list_display = (
        'employee',
        'title',
        'target',
        'achieved',
        'status',
        'due_date',
        'created_at',
    )
    list_filter = ('status',)
    search_fields = (
        'employee__username',
        'employee__first_name',
        'employee__last_name',
        'title',
    )
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
