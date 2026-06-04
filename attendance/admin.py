from django.contrib import admin

from .models import Attendance


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    # -----------------------------------------------------------------------
    # List view configuration
    # -----------------------------------------------------------------------
    list_display = (
        'employee',
        'date',
        'check_in',
        'check_out',
        'work_hours',
        'status',
        'is_late',
        'ip_address',
    )
    list_display_links = ('employee', 'date')
    list_filter = (
        'status',
        'date',
        'is_late',
        'employee__department',
    )
    search_fields = (
        'employee__username',
        'employee__first_name',
        'employee__last_name',
        'employee__employee_id',
        'ip_address',
        'location',
    )
    date_hierarchy = 'date'
    ordering = ('-date', 'employee')

    # -----------------------------------------------------------------------
    # Detail view configuration
    # -----------------------------------------------------------------------
    readonly_fields = ('work_hours', 'is_late')
    fieldsets = (
        (
            'Employee & Date',
            {
                'fields': ('employee', 'date'),
            },
        ),
        (
            'Time & Work Hours',
            {
                'fields': ('check_in', 'check_out', 'work_hours'),
            },
        ),
        (
            'Status',
            {
                'fields': ('status', 'is_late'),
            },
        ),
        (
            'Location & Network',
            {
                'fields': ('ip_address', 'location'),
                'classes': ('collapse',),
            },
        ),
        (
            'Notes',
            {
                'fields': ('notes',),
                'classes': ('collapse',),
            },
        ),
    )

    # -----------------------------------------------------------------------
    # Bulk actions
    # -----------------------------------------------------------------------
    actions = ['mark_as_present', 'mark_as_absent', 'mark_as_late']

    @admin.action(description='Mark selected records as Present')
    def mark_as_present(self, request, queryset):
        updated = queryset.update(status='present', is_late=False)
        self.message_user(request, f'{updated} record(s) marked as Present.')

    @admin.action(description='Mark selected records as Absent')
    def mark_as_absent(self, request, queryset):
        updated = queryset.update(status='absent')
        self.message_user(request, f'{updated} record(s) marked as Absent.')

    @admin.action(description='Mark selected records as Late')
    def mark_as_late(self, request, queryset):
        updated = queryset.update(status='late', is_late=True)
        self.message_user(request, f'{updated} record(s) marked as Late.')
