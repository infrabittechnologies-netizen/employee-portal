from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser, Department


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'employee_count', 'created_at')
    search_fields = ('name', 'description')
    ordering = ('name',)
    readonly_fields = ('created_at',)

    def employee_count(self, obj):
        return obj.employees.filter(is_active=True).count()
    employee_count.short_description = 'Active Employees'


# ---------------------------------------------------------------------------
# CustomUser
# ---------------------------------------------------------------------------

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = (
        'employee_id',
        'username',
        'get_full_name',
        'email',
        'department',
        'designation',
        'role',
        'is_active',
        'date_joined',
    )
    list_display_links = ('employee_id', 'username')
    list_filter = ('role', 'department', 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('employee_id', 'username', 'first_name', 'last_name', 'email', 'designation')
    ordering = ('first_name', 'last_name')
    readonly_fields = ('date_joined', 'last_login')

    # Fieldsets for the change (edit) form
    fieldsets = (
        (None, {
            'fields': ('username', 'password'),
        }),
        ('Personal Information', {
            'fields': (
                'first_name', 'last_name', 'email',
                'phone', 'date_of_birth', 'address',
                'emergency_contact', 'profile_picture',
            ),
        }),
        ('Employment Details', {
            'fields': (
                'employee_id', 'designation', 'department',
                'role', 'manager', 'joining_date', 'basic_salary',
            ),
        }),
        ('Account Permissions', {
            'classes': ('collapse',),
            'fields': (
                'is_active', 'is_staff', 'is_superuser',
                'groups', 'user_permissions',
            ),
        }),
        ('Important Dates', {
            'classes': ('collapse',),
            'fields': ('last_login', 'date_joined'),
        }),
    )

    # Fieldsets for the add (create) form
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
        ('Personal Information', {
            'fields': (
                'first_name', 'last_name', 'email',
                'phone', 'date_of_birth', 'address', 'emergency_contact',
            ),
        }),
        ('Employment Details', {
            'fields': (
                'employee_id', 'designation', 'department',
                'role', 'manager', 'joining_date', 'basic_salary',
            ),
        }),
        ('Account Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser'),
        }),
    )

    def get_full_name(self, obj):
        return obj.get_full_name() or '—'
    get_full_name.short_description = 'Full Name'
    get_full_name.admin_order_field = 'first_name'
