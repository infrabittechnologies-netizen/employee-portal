from django.db import models
from django.conf import settings


class Holiday(models.Model):
    name = models.CharField(max_length=100)
    date = models.DateField(unique=True)
    description = models.TextField(blank=True)
    is_optional = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"{self.name} ({self.date})"


class Announcement(models.Model):
    TARGET_CHOICES = [
        ('all', 'All Employees'),
        ('department', 'Specific Department'),
        ('manager', 'Managers Only'),
    ]

    title = models.CharField(max_length=200)
    content = models.TextField()
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    posted_on = models.DateTimeField(auto_now_add=True)
    target = models.CharField(max_length=20, choices=TARGET_CHOICES, default='all')
    department = models.ForeignKey('accounts.Department', on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-posted_on']

    def __str__(self):
        return self.title
