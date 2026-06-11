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

    # ---- Device lock (one registered device per account) -------------------
    # The first device an employee signs in from is bound to the account for
    # life. Any other device is rejected at login until an admin resets it.
    device_id = models.CharField(max_length=64, blank=True, null=True)
    device_user_agent = models.CharField(max_length=300, blank=True)
    device_registered_at = models.DateTimeField(null=True, blank=True)

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
