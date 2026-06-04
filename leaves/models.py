from django.db import models
from django.conf import settings
from django.utils import timezone


class LeaveType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    max_days_per_year = models.IntegerField(default=10)
    is_paid = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=10, default='#007bff')

    def __str__(self):
        return self.name


class LeaveApplication(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_applications')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='applications')
    from_date = models.DateField()
    to_date = models.DateField()
    total_days = models.IntegerField(default=0)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    applied_on = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_leaves')
    review_comment = models.TextField(blank=True)
    reviewed_on = models.DateTimeField(null=True, blank=True)
    document = models.FileField(upload_to='leave_docs/', null=True, blank=True)
    is_half_day = models.BooleanField(default=False)

    class Meta:
        ordering = ['-applied_on']

    def __str__(self):
        return f"{self.employee} - {self.leave_type} ({self.from_date} to {self.to_date})"

    def save(self, *args, **kwargs):
        if self.from_date and self.to_date:
            delta = self.to_date - self.from_date
            self.total_days = delta.days + 1
            if self.is_half_day:
                self.total_days = 0.5
        super().save(*args, **kwargs)


class LeaveBalance(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name='balances')
    year = models.IntegerField(default=2025)
    total_allocated = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    used = models.DecimalField(max_digits=5, decimal_places=1, default=0)

    class Meta:
        unique_together = ('employee', 'leave_type', 'year')

    @property
    def remaining(self):
        return self.total_allocated - self.used

    def __str__(self):
        return f"{self.employee} - {self.leave_type} ({self.year}): {self.remaining} remaining"
