from django.contrib.auth.models import AbstractUser
from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('employee', 'Employee'),
    ]

    employee_id = models.CharField(max_length=20, unique=True, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')
    joining_date = models.DateField(null=True, blank=True)
    profile_picture = models.ImageField(upload_to='profiles/', null=True, blank=True)
    address = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    manager = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='subordinates')
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ---- Multi-tenant ownership --------------------------------------------
    # The admin account that "owns" this user. Each non-superuser admin is a
    # separate tenant: they only ever see users (and their attendance, leaves,
    # salary, performance) whose owner is themselves. ``owner`` points at the
    # owning admin; an admin's own ``owner`` is themselves (set on creation).
    # Superusers are global and bypass all tenant scoping.
    owner = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='owned_users',
    )

    # ---- Device lock (one registered device per account) -------------------
    # The first device an employee signs in from is bound to the account for
    # life. Any other device is rejected at login until an admin resets it.
    device_id = models.CharField(max_length=64, blank=True, null=True)
    device_user_agent = models.CharField(max_length=300, blank=True)
    device_registered_at = models.DateTimeField(null=True, blank=True)
    # Last IP/time this device was seen — used to spot a copied cookie being
    # used from two places (impossible-travel / concurrent-use detection).
    device_last_ip = models.CharField(max_length=45, blank=True)
    device_last_seen = models.DateTimeField(null=True, blank=True)

    # ---- Single active session per account ---------------------------------
    # The session key of the latest sign-in. A new login supersedes the old
    # one, and any request from a stale session is signed out.
    current_session_key = models.CharField(max_length=40, blank=True, null=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.employee_id or 'No ID'})"

    @property
    def is_admin(self):
        return self.role == 'admin' or self.is_superuser

    @property
    def is_manager_role(self):
        return self.role in ('admin', 'manager') or self.is_superuser

    def get_profile_picture_url(self):
        if self.profile_picture:
            return self.profile_picture.url
        return '/static/images/default_avatar.png'

    class Meta:
        ordering = ['first_name', 'last_name']


class TenantSchedule(models.Model):
    """Per-tenant work-schedule configuration.

    Keyed to the tenant *root* admin (the CustomUser whose ``owner`` is the
    tenant boundary). When a tenant has NO row here, the portal falls back to
    the hardcoded DEFAULT schedule in ``attendance/schedule.py`` — so existing
    tenants (e.g. Admin A) keep their exact current behaviour untouched.

    ``breaks`` is a JSON list of objects:
        {"start": "13:00", "end": "14:00", "label": "Lunch Break",
         "deductible": false}
    ``deductible=False`` means time inside the window is free (no salary
    deduction, no break-overstay deduction) but its status is still shown.
    ``working_days`` is a comma-separated list of Python weekday ints
    (Monday=0 … Sunday=6), e.g. "0,1,2,3,4,5" for Mon–Sat.
    """
    admin = models.OneToOneField(
        'CustomUser', on_delete=models.CASCADE, related_name='tenant_schedule',
    )
    work_start = models.TimeField(help_text='Shift start time, e.g. 09:00')
    work_end = models.TimeField(help_text='Shift end time, e.g. 18:00')
    checkin_open = models.TimeField(
        help_text='Earliest allowed check-in time, e.g. 08:55',
    )
    checkout_max = models.TimeField(
        help_text='Latest allowed check-out / auto-logout time, e.g. 18:30',
    )
    working_days = models.CharField(
        max_length=20, default='0,1,2,3,4',
        help_text='Comma-separated weekday ints (Mon=0 … Sun=6).',
    )
    breaks = models.JSONField(
        default=list, blank=True,
        help_text='List of {start,end,label,deductible} break windows.',
    )
    break_early_restart_minutes = models.PositiveIntegerField(default=5)
    commission_enabled = models.BooleanField(
        default=True, help_text='Show/allow the Sales Commission feature.',
    )
    enforce_working_hours = models.BooleanField(
        default=False,
        help_text=(
            'When on, employees may sign in to the portal at any time but can '
            'only perform attendance actions (check-in, check-out, resume work) '
            'during the allowed working-hours window. Outside that window every '
            'action is blocked with a notice.'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Schedule for {self.admin.username}'

    @property
    def working_day_set(self):
        out = set()
        for part in (self.working_days or '').split(','):
            part = part.strip()
            if part.isdigit():
                out.add(int(part))
        return out
