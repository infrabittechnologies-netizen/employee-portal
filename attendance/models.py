from django.db import models
from django.conf import settings
from django.utils import timezone

from .schedule import is_late_checkin, net_work_hours


class Attendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('half_day', 'Half Day'),
        ('holiday', 'Holiday'),
        ('leave', 'On Leave'),
    ]

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField(default=timezone.now)
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    work_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    notes = models.TextField(blank=True)
    is_late = models.BooleanField(default=False)

    class Meta:
        unique_together = ('employee', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.employee} - {self.date} ({self.status})"

    def save(self, *args, **kwargs):
        if self.check_in:
            self.is_late = is_late_checkin(self.check_in)
            self.status = 'late' if self.is_late else 'present'
        if self.check_in and self.check_out:
            self.work_hours = net_work_hours(self.check_in, self.check_out)
        super().save(*args, **kwargs)


class AttendanceBreak(models.Model):
    """Records when an employee manually resumed work after a scheduled break."""
    attendance = models.ForeignKey(
        Attendance, on_delete=models.CASCADE, related_name='break_restarts'
    )
    break_number  = models.IntegerField()         # 1 or 2
    scheduled_end = models.TimeField()            # e.g. time(19, 15) for Break 1
    resumed_at    = models.DateTimeField()        # when employee clicked "Restart Work"

    class Meta:
        unique_together = ('attendance', 'break_number')
        ordering = ['break_number']

    def __str__(self):
        return f"{self.attendance.employee} – Break {self.break_number} resumed at {self.resumed_at}"

    @property
    def delay_minutes(self):
        """Minutes between scheduled break end and actual restart."""
        import datetime
        local_resumed = timezone.localtime(self.resumed_at)
        resume_dt     = datetime.datetime.combine(local_resumed.date(), local_resumed.time())
        sched_dt      = datetime.datetime.combine(local_resumed.date(), self.scheduled_end)
        return max(0, int((resume_dt - sched_dt).total_seconds() / 60))
