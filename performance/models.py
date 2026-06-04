from django.db import models
from django.conf import settings
from django.utils import timezone


class PerformanceReview(models.Model):
    RATING_CHOICES = [
        (1, 'Poor'),
        (2, 'Below Average'),
        (3, 'Average'),
        (4, 'Good'),
        (5, 'Excellent'),
    ]
    PERIOD_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('half_yearly', 'Half Yearly'),
        ('annual', 'Annual'),
    ]

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='performance_reviews')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='given_reviews')
    review_period = models.CharField(max_length=20, choices=PERIOD_CHOICES, default='monthly')
    period_start = models.DateField()
    period_end = models.DateField()
    rating = models.IntegerField(choices=RATING_CHOICES, default=3)
    attendance_score = models.IntegerField(default=0, help_text='Out of 20')
    productivity_score = models.IntegerField(default=0, help_text='Out of 20')
    quality_score = models.IntegerField(default=0, help_text='Out of 20')
    teamwork_score = models.IntegerField(default=0, help_text='Out of 20')
    communication_score = models.IntegerField(default=0, help_text='Out of 20')
    comments = models.TextField(blank=True)
    self_evaluation = models.TextField(blank=True)
    goals_achieved = models.TextField(blank=True)
    goals_next_period = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} - {self.review_period} ({self.period_start})"

    @property
    def total_score(self):
        return (self.attendance_score + self.productivity_score +
                self.quality_score + self.teamwork_score + self.communication_score)

    @property
    def rating_label(self):
        return dict(self.RATING_CHOICES).get(self.rating, 'Unknown')


class KPI(models.Model):
    STATUS_CHOICES = [
        ('on_track', 'On Track'),
        ('achieved', 'Achieved'),
        ('missed', 'Missed'),
        ('in_progress', 'In Progress'),
    ]

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='kpis')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target = models.CharField(max_length=200)
    achieved = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    due_date = models.DateField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} - {self.title}"
